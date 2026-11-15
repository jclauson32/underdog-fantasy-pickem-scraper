#!/usr/bin/env python3
"""
NFL PPR rankings from Underdog Fantasy pick'em lines.

Pulls every live NFL prop from Underdog, turns each player's lines + odds into
a projected full-PPR score, ranks everyone, and writes a spreadsheet.

Standard library only -- no pip installs needed:

    python3 ppr_rankings.py                 # -> nfl_ppr_rankings.xlsx/.html (+ .csv files)
    python3 ppr_rankings.py --open          # ...and open the interactive page in your browser
    python3 ppr_rankings.py -o week11.xlsx  # custom output name

Sheets / files produced:
  * PPR Rankings  - one row per player, ranked by projected PPR points, with the
                    line and over/under odds for every stat used
  * All NFL Props - every NFL prop line Underdog has up, with both sides' odds
  * nfl_ppr_rankings.html - interactive, self-contained page: filter by
                    position/team/game, group by position/team/game, sort by any column
"""

import argparse
import csv
import io
import json
import math
import os
import sys
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from statistics import NormalDist
from xml.sax.saxutils import escape

API_URL = "https://api.underdogfantasy.com/v1/over_under_lines"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

POSITIONS = {"QB", "RB", "WR", "TE"}

# Full-PPR scoring
PPR = {
    "passing_yds": 0.04,
    "passing_tds": 4,
    "passing_ints": -2,
    "rushing_yds": 0.1,
    "receiving_yds": 0.1,
    "receiving_rec": 1,
    "rush_rec_tds": 6,
    "fumbles_lost": -2,
}

# Stats modelled as counts (Poisson) vs yardage (normal around the line)
COUNT_STATS = {"receiving_rec", "passing_tds", "passing_ints", "rush_rec_tds", "fumbles_lost"}
YARD_STATS = {"passing_yds", "rushing_yds", "receiving_yds", "rush_rec_yds", "passing_and_rushing_yds"}
YARD_SD_RATIO = 0.45  # rough game-to-game spread of yardage as a fraction of the line

# Columns shown in the rankings sheet: (stat key, label)
ODDS_COLUMNS = [
    ("passing_yds", "Pass Yds"),
    ("passing_tds", "Pass TDs"),
    ("passing_ints", "INTs"),
    ("rushing_yds", "Rush Yds"),
    ("receiving_rec", "Receptions"),
    ("receiving_yds", "Rec Yds"),
    ("rush_rec_tds", "Anytime TD"),
    ("fantasy_points", "UD Fantasy Pts"),
]


# --------------------------------------------------------------------------- #
# Odds math
# --------------------------------------------------------------------------- #
def american_to_prob(american):
    try:
        a = float(american)
    except (TypeError, ValueError):
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def no_vig_over_prob(over_american, under_american):
    """Probability of the over with the bookmaker margin removed."""
    po, pu = american_to_prob(over_american), american_to_prob(under_american)
    if po is not None and pu is not None:
        return po / (po + pu)
    if po is not None:  # one-sided market (e.g. fumbles): strip a typical ~5% margin
        return min(po / 1.05, 0.99)
    if pu is not None:
        return max(1 - pu / 1.05, 0.01)
    return None


def poisson_sf(line, lam):
    """P(X > line) for X ~ Poisson(lam)."""
    k_max = math.floor(line)
    cdf, term = 0.0, math.exp(-lam)
    for k in range(k_max + 1):
        if k > 0:
            term *= lam / k
        cdf += term
    return 1 - cdf


def poisson_mean_for(line, p_over):
    """Find the Poisson mean whose P(X > line) equals p_over (bisection)."""
    p_over = min(max(p_over, 0.001), 0.999)
    lo, hi = 1e-6, max(10.0, line * 4 + 10)
    for _ in range(100):
        mid = (lo + hi) / 2
        if poisson_sf(line, mid) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def project(stat, line, p_over):
    """Expected value of a stat given its line and no-vig over probability."""
    if p_over is None:
        return line
    if stat in COUNT_STATS:
        return poisson_mean_for(line, p_over)
    if stat in YARD_STATS:
        z = NormalDist().inv_cdf(min(max(p_over, 0.01), 0.99))
        return max(line + z * YARD_SD_RATIO * line, 0.0)
    return line


# --------------------------------------------------------------------------- #
# Data fetch / shaping
# --------------------------------------------------------------------------- #
def fetch():
    req = urllib.request.Request(API_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fmt_american(a):
    if a in (None, ""):
        return ""
    try:
        v = int(float(a))
    except ValueError:
        return str(a)
    return f"+{v}" if v > 0 else str(v)


def collect_props(data):
    """Return {appearance_id: info} and a flat list of every NFL prop."""
    players = {p["id"]: p for p in data.get("players", [])}
    appearances = {a["id"]: a for a in data.get("appearances", [])}
    games = {g["id"]: g for g in data.get("games", [])}

    by_app, flat = {}, []
    for line in data.get("over_under_lines", []):
        if line.get("status") not in (None, "active"):
            continue
        ast = (line.get("over_under") or {}).get("appearance_stat") or {}
        app = appearances.get(ast.get("appearance_id"))
        if not app:
            continue
        player = players.get(app["player_id"])
        if not player or player.get("sport_id") != "NFL":
            continue

        over = under = None
        for opt in line.get("options", []):
            if opt.get("choice") == "higher":
                over = opt.get("american_price")
            elif opt.get("choice") == "lower":
                under = opt.get("american_price")

        game = games.get(app.get("match_id"), {})
        team, opp = team_and_opponent(game, app.get("team_id"))
        name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
        stat = ast.get("stat")
        value = float(line["stat_value"])
        p_over = no_vig_over_prob(over, under)

        flat.append({
            "Player": name,
            "Pos": player.get("position_name", ""),
            "Team": team,
            "Opp": opp,
            "Game": game.get("abbreviated_title", ""),
            "Kickoff (UTC)": game.get("scheduled_at", ""),
            "Stat": ast.get("display_stat", stat),
            "Stat Key": stat,
            "Line": value,
            "Over Odds": fmt_american(over),
            "Under Odds": fmt_american(under),
            "No-Vig Over %": round(p_over * 100, 1) if p_over is not None else "",
        })

        info = by_app.setdefault(app["id"], {
            "name": name, "pos": player.get("position_name", ""),
            "team": team, "opp": opp, "game": game.get("abbreviated_title", ""),
            "kickoff": game.get("scheduled_at", ""), "stats": {},
        })
        # keep the most balanced line if a stat appears more than once
        prev = info["stats"].get(stat)
        if prev is None or abs((p_over or 0.5) - 0.5) < abs((prev["p_over"] or 0.5) - 0.5):
            info["stats"][stat] = {"line": value, "over": over, "under": under, "p_over": p_over}
    return by_app, flat


def team_and_opponent(game, team_id):
    title = game.get("abbreviated_title", "")
    if " @ " not in title:
        return "", ""
    away, home = title.split(" @ ", 1)
    if team_id == game.get("home_team_id"):
        return home, away
    if team_id == game.get("away_team_id"):
        return away, home
    return "", ""


def build_rankings(by_app):
    rows = []
    for info in by_app.values():
        if info["pos"] not in POSITIONS:
            continue
        s = info["stats"]
        proj = {k: project(k, v["line"], v["p_over"]) for k, v in s.items()}

        # Derive missing components from combo lines when possible
        if "rushing_yds" not in proj:
            if "rush_rec_yds" in proj and "receiving_yds" in proj:
                proj["rushing_yds"] = max(proj["rush_rec_yds"] - proj["receiving_yds"], 0)
            elif "passing_and_rushing_yds" in proj and "passing_yds" in proj:
                proj["rushing_yds"] = max(proj["passing_and_rushing_yds"] - proj["passing_yds"], 0)
        if "receiving_yds" not in proj and "rush_rec_yds" in proj and "rushing_yds" in s:
            proj["receiving_yds"] = max(proj["rush_rec_yds"] - proj["rushing_yds"], 0)

        core = {"passing_yds", "rushing_yds", "receiving_yds", "receiving_rec"}
        has_props = bool(core & proj.keys())
        ppr_from_props = sum(PPR[k] * proj[k] for k in PPR if k in proj)

        # Underdog's own fantasy-points line is half-PPR; convert by adding 0.5/catch
        ud_fp = s.get("fantasy_points")
        ud_ppr = None
        if ud_fp:
            ud_ppr = ud_fp["line"] + 0.5 * proj.get("receiving_rec", 0)

        if has_props:
            ppr, source = ppr_from_props, "Props"
        elif ud_ppr is not None:
            ppr, source = ud_ppr, "UD Fantasy Pts line"
        else:
            continue  # nothing usable (e.g. only a 1Q line)

        row = {
            "Player": info["name"], "Pos": info["pos"], "Team": info["team"],
            "Opp": info["opp"], "Game": info["game"], "Kickoff (UTC)": info["kickoff"],
            "Proj PPR": round(ppr, 2),
            "Proj Source": source,
            "UD Fantasy Pts (½PPR)": ud_fp["line"] if ud_fp else "",
            "UD Pts → PPR": round(ud_ppr, 2) if ud_ppr is not None else "",
            "Exp Pass Yds": round(proj.get("passing_yds", 0), 1),
            "Exp Pass TD": round(proj.get("passing_tds", 0), 2),
            "Exp INT": round(proj.get("passing_ints", 0), 2),
            "Exp Rush Yds": round(proj.get("rushing_yds", 0), 1),
            "Exp Rec": round(proj.get("receiving_rec", 0), 2),
            "Exp Rec Yds": round(proj.get("receiving_yds", 0), 1),
            "Exp TDs": round(proj.get("rush_rec_tds", 0), 2),
        }
        td = s.get("rush_rec_tds")
        row["Anytime TD %"] = round(td["p_over"] * 100, 1) if td and td["p_over"] is not None else ""
        for key, label in ODDS_COLUMNS:
            v = s.get(key)
            row[f"{label} Line"] = v["line"] if v else ""
            row[f"{label} Over"] = fmt_american(v["over"]) if v else ""
            row[f"{label} Under"] = fmt_american(v["under"]) if v else ""
        rows.append(row)

    rows.sort(key=lambda r: r["Proj PPR"], reverse=True)
    pos_rank = {}
    for i, r in enumerate(rows, 1):
        pos_rank[r["Pos"]] = pos_rank.get(r["Pos"], 0) + 1
        r["Rank"] = i
        r["Pos Rank"] = f"{r['Pos']}{pos_rank[r['Pos']]}"
    order = ["Rank", "Pos Rank"]
    return [{k: r[k] for k in order + [c for c in r if c not in order]} for r in rows]


# --------------------------------------------------------------------------- #
# Output: CSV + a minimal .xlsx writer (no openpyxl needed)
# --------------------------------------------------------------------------- #
def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def col_letter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def sheet_xml(rows):
    headers = list(rows[0].keys()) if rows else []
    widths = []
    for h in headers:
        longest = max([len(str(h))] + [len(str(r.get(h, ""))) for r in rows[:500]])
        widths.append(min(max(longest + 2, 6), 40))

    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
              'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>')
    for i, w in enumerate(widths, 1):
        out.write(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
    out.write("</cols><sheetData>")

    def cell(ref, v, style=0):
        st = f' s="{style}"' if style else ""
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f'<c r="{ref}"{st}><v>{v}</v></c>'
        return f'<c r="{ref}"{st} t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'

    out.write('<row r="1">' + "".join(cell(f"{col_letter(i)}1", h, 1) for i, h in enumerate(headers)) + "</row>")
    for n, r in enumerate(rows, 2):
        out.write(f'<row r="{n}">')
        for i, h in enumerate(headers):
            v = r.get(h, "")
            if v != "":
                out.write(cell(f"{col_letter(i)}{n}", v))
        out.write("</row>")
    out.write("</sheetData>")
    if headers:
        out.write(f'<autoFilter ref="A1:{col_letter(len(headers) - 1)}{len(rows) + 1}"/>')
    out.write("</worksheet>")
    return out.getvalue()


def write_xlsx(path, sheets):
    """sheets: list of (name, rows)."""
    ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'<Relationship Id="rId1" Type="{ns}/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{ns}"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, (n, _) in enumerate(sheets, 1))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="{ns}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="{ns}/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill>'
                   '<fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border/></borders>'
                   '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
                   '<cellXfs count="2"><xf fontId="0"/><xf fontId="1" applyFont="1"/></cellXfs>'
                   "</styleSheet>")
        for i, (_, rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet_xml(rows))


def write_html(path, rows):
    """Self-contained interactive page (data embedded, no server needed)."""
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "rankings.html")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    payload = json.dumps({"generated": datetime.now().astimezone().isoformat(), "rows": rows})
    payload = payload.replace("</", "<\\/")  # keep "</script>" out of the inline script
    with open(path, "w", encoding="utf-8") as f:
        f.write(template.replace("/*__DATA__*/null", payload, 1))


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="nfl_ppr_rankings.xlsx", help="output .xlsx path")
    ap.add_argument("--no-csv", action="store_true", help="skip writing the CSV copies")
    ap.add_argument("--open", action="store_true", help="open the interactive HTML page in your browser")
    args = ap.parse_args()

    print("Fetching Underdog lines...")
    try:
        data = fetch()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Failed to fetch {API_URL}: {e}")

    by_app, flat = collect_props(data)
    if not flat:
        sys.exit("No NFL props are posted on Underdog right now.")
    rankings = build_rankings(by_app)
    flat.sort(key=lambda r: (r["Kickoff (UTC)"], r["Game"], r["Player"], r["Stat"]))

    write_xlsx(args.output, [("PPR Rankings", rankings), ("All NFL Props", flat)])
    print(f"Wrote {args.output}  ({len(rankings)} ranked players, {len(flat)} NFL props)")
    html_path = os.path.splitext(args.output)[0] + ".html"
    write_html(html_path, rankings)
    print(f"Wrote {html_path}  (interactive: sort/group/filter)")
    if not args.no_csv:
        base = os.path.splitext(args.output)[0]
        write_csv(f"{base}.csv", rankings)
        write_csv(f"{base}_all_props.csv", flat)
        print(f"Wrote {base}.csv and {base}_all_props.csv")

    print(f"\nTop 15 ({datetime.now():%Y-%m-%d %H:%M}):")
    for r in rankings[:15]:
        print(f"{r['Rank']:>3}. {r['Player']:<24} {r['Pos Rank']:<6} {r['Team']:<4} vs {r['Opp']:<4} {r['Proj PPR']:>6.2f}")

    if args.open:
        webbrowser.open("file://" + os.path.abspath(html_path))


if __name__ == "__main__":
    main()
