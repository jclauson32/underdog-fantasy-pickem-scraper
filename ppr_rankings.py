#!/usr/bin/env python3
"""
NFL PPR rankings from Underdog Fantasy pick'em lines, compared with Sleeper Picks.

Pulls every live NFL prop from Underdog, turns each player's lines + odds into
a projected full-PPR score, ranks everyone, and writes a spreadsheet.

Standard library only -- no pip installs needed:

    python3 ppr_rankings.py                 # -> nfl_ppr_rankings.xlsx/.html (+ .csv files)
    python3 ppr_rankings.py --open          # ...and open the interactive page in your browser
    python3 ppr_rankings.py -o week11.xlsx  # custom output name

Sheets (also written as CSV files):
  * PPR Rankings        - one row per player, with a PPR projection from each site's lines (and their
                          average, used for the rank) and every stat's line, odds and expected value per site
  * Odds Comparison     - every prop from both sites, one row per player + stat, side by side
  * Underdog Props      - every NFL line on Underdog with all its price fields
  * Sleeper Props       - every NFL line on Sleeper Picks (payouts, pick counts, recent results)
Plus nfl_ppr_rankings.html - interactive page with the rankings and odds comparison:
filter, group and sort by any column.
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

from fantasypros_scraper import STATS as FANTASYPROS_STATS
from fantasypros_scraper import FantasyProsScraper
from sleeper_scraper import SleeperScraper

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

# Stat column groups in the rankings, in display order: (stat key, label). Each gets Line / Over / Under
# per site, plus "Exp" (expected value used for the projection) for stats that feed PPR scoring.
STAT_BANDS = [
    ("fantasy_points", "Fantasy Pts"),
    ("passing_yds", "Pass Yds"),
    ("passing_tds", "Pass TDs"),
    ("passing_ints", "INTs"),
    ("passing_comps", "Completions"),
    ("passing_att", "Pass Att"),
    ("passing_long", "Long Completion"),
    ("passing_and_rushing_yds", "Pass + Rush Yds"),
    ("rushing_yds", "Rush Yds"),
    ("rushing_att", "Rush Att"),
    ("rushing_long", "Long Rush"),
    ("receiving_rec", "Receptions"),
    ("receiving_yds", "Rec Yds"),
    ("receiving_tgts", "Targets"),
    ("receiving_long", "Long Reception"),
    ("rush_rec_yds", "Rush + Rec Yds"),
    ("rush_rec_tds", "Anytime TD"),
    ("fumbles_lost", "Fumbles Lost"),
]
EXP_STATS = set(PPR)
SITES = (("UD", "Underdog"), ("SL", "Sleeper"), ("FP", "FantasyPros"))
NO_TD_SOURCE = "Props, no TD line"
# What each site's Fantasy Points line needs added per expected catch to become full PPR
FP_TO_PPR_PER_REC = {"UD": 0.5, "SL": 0.0}
# Underdog scores Fantasy Points half-PPR; Sleeper's line fits full PPR -- so their lines aren't directly comparable
FANTASY_POINTS_LABEL = "Fantasy Points (UD ½PPR, SL PPR)"


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


def sleeper_site_stats(lines):
    """Sleeper lines -> the same {stat: {line, over, under, p_over}} shape as Underdog's."""
    return {k: {"line": ln["line"], "over": ln["over_american"], "under": ln["under_american"],
                "p_over": no_vig_over_prob(ln["over_american"], ln["under_american"])}
            for k, ln in lines.items()}


def pct(p):
    return round(p * 100, 1) if p is not None else ""


def recent_over_pct(sl):
    """Share of the player's recent games (as listed by Sleeper) that went over the current Sleeper line."""
    vals = [v for v in (sl or {}).get("recent_values", []) if v is not None]
    return round(100 * sum(v > sl["line"] for v in vals) / len(vals)) if vals else ""


def build_comparison(by_app, sleeper):
    """One row per player + stat with Underdog and Sleeper lines/odds side by side.
    Includes stats only one site offers (the other side is blank)."""
    rows, used = [], set()
    team_games = {}  # team -> (opp, game, kickoff) from Underdog, to fill in Sleeper-only rows
    for info in by_app.values():
        if info["team"]:
            team_games[info["team"]] = (info["opp"], info["game"], info["kickoff"])

    def row_for(name, pos, team, opp, game, kickoff, stat, display, ud, sl):
        ud_p = ud["p_over"] if ud else None
        sl_p = no_vig_over_prob(sl["over_american"], sl["under_american"]) if sl else None
        return {
            "Player": name, "Pos": pos, "Team": team, "Opp": opp, "Game": game, "Kickoff (UTC)": kickoff,
            "Stat": display, "Stat Key": stat,
            "Sites": "Both" if ud and sl else ("Underdog" if ud else "Sleeper"),
            "UD Line": ud["line"] if ud else "",
            "UD Over": fmt_american(ud["over"]) if ud else "",
            "UD Under": fmt_american(ud["under"]) if ud else "",
            "UD Over %": pct(ud_p),
            "SL Line": sl["line"] if sl else "",
            "SL Over": sl["over_american"] if sl else "",
            "SL Under": sl["under_american"] if sl else "",
            "SL Over %": pct(sl_p),
            "SL Over Mult": num_or_blank(sl["over_multiplier"]) if sl else "",
            "SL Under Mult": num_or_blank(sl["under_multiplier"]) if sl else "",
            "Line Δ (SL−UD)": round(sl["line"] - ud["line"], 2) if ud and sl else "",
            "Over % Δ (SL−UD)": round((sl_p - ud_p) * 100, 1) if sl_p is not None and ud_p is not None else "",
            "SL Pick Popularity %": pct(sl["popularity"]) if sl and sl["popularity"] is not None else "",
            "SL Picks Over": sl["picks_over"] if sl else "",
            "SL Picks Under": sl["picks_under"] if sl else "",
            "SL Recent Over %": recent_over_pct(sl),
            "SL Recent Results": " ".join("" if v is None else f"{v:g}" for v in sl["recent_values"]) if sl else "",
        }

    display_names = {"fantasy_points": FANTASY_POINTS_LABEL}
    ud_player = {}  # Sleeper id -> Underdog info, so Sleeper-only rows use Underdog's name spelling
    for info in by_app.values():
        for k, v in info["display"].items():
            display_names.setdefault(k, v)
        pid = sleeper.player_id_for(info["name"], info["team"]) if sleeper else None
        if pid:
            ud_player.setdefault(pid, info)
        sl_lines = sleeper.lines_for_id(pid) if pid else {}
        for stat, ud in info["stats"].items():
            sl = sl_lines.get(stat)
            if sl:
                used.add((pid, stat))
            rows.append(row_for(info["name"], info["pos"], info["team"], info["opp"], info["game"],
                                info["kickoff"], stat, display_names.get(stat, stat), ud, sl))

    for sl in (sleeper.sleeper_lines if sleeper else []):  # Sleeper lines Underdog doesn't have
        if (sl["player_id"], sl["stat_key"]) in used:
            continue
        display = display_names.get(sl["stat_key"]) or sl["wager_type"].replace("_", " ").title()
        info = ud_player.get(sl["player_id"])
        if info:
            rows.append(row_for(info["name"], info["pos"], info["team"], info["opp"], info["game"],
                                info["kickoff"], sl["stat_key"], display, None, sl))
        else:
            opp, game, kickoff = team_games.get(sl["team"], ("", "", ""))
            rows.append(row_for(sl["name"], sl["position"], sl["team"], opp, game, kickoff,
                                sl["stat_key"], display, None, sl))

    rows.sort(key=lambda r: (r["Kickoff (UTC)"] or "~", r["Game"], r["Player"], r["Stat"]))
    return rows


def fmt_american(a):
    if a in (None, ""):
        return ""
    try:
        v = int(float(a))
    except ValueError:
        return str(a)
    return f"+{v}" if v > 0 else str(v)


def num_or_blank(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return ""


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

        over_opt = under_opt = {}
        for opt in line.get("options", []):
            if opt.get("choice") == "higher":
                over_opt = opt
            elif opt.get("choice") == "lower":
                under_opt = opt
        over, under = over_opt.get("american_price"), under_opt.get("american_price")

        game = games.get(app.get("match_id"), {})
        team, opp = team_and_opponent(game, app.get("team_id"))
        name = f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
        stat = ast.get("stat")
        value = float(line["stat_value"])
        p_over = no_vig_over_prob(over, under)

        def fantasy_odds(opt, field):
            return ((opt.get("odds") or {}).get("fantasy") or {}).get(field, "")

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
            "Over Decimal": num_or_blank(over_opt.get("decimal_price")),
            "Under Decimal": num_or_blank(under_opt.get("decimal_price")),
            "Over Payout Mult": num_or_blank(over_opt.get("payout_multiplier")),
            "Under Payout Mult": num_or_blank(under_opt.get("payout_multiplier")),
            "Over Fantasy Odds": fmt_american(fantasy_odds(over_opt, "american")),
            "Under Fantasy Odds": fmt_american(fantasy_odds(under_opt, "american")),
            "Over Fantasy Prob %": num_or_blank(fantasy_odds(over_opt, "probability")),
            "Under Fantasy Prob %": num_or_blank(fantasy_odds(under_opt, "probability")),
            "Line Type": line.get("line_type", ""),
            "Jersey": player.get("jersey_number", ""),
            "Updated": max(over_opt.get("updated_at") or "", under_opt.get("updated_at") or "", line.get("updated_at") or ""),
        })

        info = by_app.setdefault(app["id"], {
            "name": name, "pos": player.get("position_name", ""),
            "team": team, "opp": opp, "game": game.get("abbreviated_title", ""),
            "kickoff": game.get("scheduled_at", ""), "stats": {}, "display": {},
        })
        info["display"][stat] = ast.get("display_stat", stat)
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


def project_site(stats, fp_to_ppr_per_rec):
    """One site's lines -> (expected stat values, projected PPR or None, source)."""
    proj = {k: project(k, v["line"], v["p_over"]) for k, v in stats.items()}

    # Derive missing components from combo lines when possible
    if "rushing_yds" not in proj:
        if "rush_rec_yds" in proj and "receiving_yds" in proj:
            proj["rushing_yds"] = max(proj["rush_rec_yds"] - proj["receiving_yds"], 0)
        elif "passing_and_rushing_yds" in proj and "passing_yds" in proj:
            proj["rushing_yds"] = max(proj["passing_and_rushing_yds"] - proj["passing_yds"], 0)
    if "receiving_yds" not in proj and "rush_rec_yds" in proj and "rushing_yds" in stats:
        proj["receiving_yds"] = max(proj["rush_rec_yds"] - proj["rushing_yds"], 0)

    if {"passing_yds", "rushing_yds", "receiving_yds", "receiving_rec"} & proj.keys():
        # Without an anytime-TD line the projection has no touchdown points, so it runs low -- say so
        source = "Props" if "rush_rec_tds" in stats else NO_TD_SOURCE
        return proj, sum(PPR[k] * proj[k] for k in PPR if k in proj), source
    fp = stats.get("fantasy_points")
    if fp:  # no stat props: fall back to the site's own Fantasy Points line, converted to full PPR
        return proj, fp["line"] + fp_to_ppr_per_rec * proj.get("receiving_rec", 0), "Fantasy Pts line"
    return proj, None, ""


def build_rankings(by_app, sleeper=None, fantasypros=None):
    """One row per offensive player on any site, with a PPR projection per site (and their average) and every
    stat per site: Underdog/Sleeper line, odds and expected value; FantasyPros' projected value.
    Ranked by the average of the available projections."""
    sites = [code for code, _ in SITES if code == "UD" or (code == "SL" and sleeper) or (code == "FP" and fantasypros)]
    players = []  # (base info, {site: stats}, FantasyPros projection or None)
    seen_sleeper_ids, seen_fp = set(), set()
    team_games = {i["team"]: i for i in by_app.values() if i["team"]}

    def fp_for(name, team):
        proj = fantasypros.lookup(name, team) if fantasypros else None
        if proj and id(proj) not in seen_fp:
            seen_fp.add(id(proj))
            return proj
        return None

    for info in by_app.values():
        if info["pos"] not in POSITIONS:
            continue
        site_stats = {"UD": info["stats"]}
        if sleeper:
            pid = sleeper.player_id_for(info["name"], info["team"])
            if pid:
                seen_sleeper_ids.add(pid)
                site_stats["SL"] = sleeper_site_stats(sleeper.lines_for_id(pid))
        players.append((info, site_stats, fp_for(info["name"], info["team"])))

    def info_for(name, pos, team):
        g = team_games.get(team, {})
        return {"name": name, "pos": pos, "team": team, "opp": g.get("opp", ""),
                "game": g.get("game", ""), "kickoff": g.get("kickoff", "")}

    if sleeper:  # players only Sleeper offers
        for pid, p in sleeper.players.items():
            if pid in seen_sleeper_ids or p["position"] not in POSITIONS or not sleeper.lines_for_id(pid):
                continue
            players.append((info_for(p["name"], p["position"], p["team"]),
                            {"SL": sleeper_site_stats(sleeper.lines_for_id(pid))}, fp_for(p["name"], p["team"])))
    if fantasypros:  # players only FantasyPros has
        for proj in fantasypros.fantasypros_projections:
            if id(proj) not in seen_fp:
                info = info_for(proj["name"], proj["position"], proj["team"])
                info["opp"] = info["opp"] or proj["opp"]   # game may be off Underdog already (e.g. kicked off)
                players.append((info, {}, proj))

    rows = []
    for info, site_stats, fp in players:
        results = {site: project_site(site_stats.get(site, {}), FP_TO_PPR_PER_REC[site])
                   for site in sites if site != "FP"}
        if "FP" in sites:
            results["FP"] = (fp["stats"], fp["fpts"], "FantasyPros consensus") if fp else ({}, None, "")
        projections = [results[s][1] for s in sites if results[s][1] is not None]
        if not projections:
            continue  # nothing usable (e.g. only a 1Q line)
        row = {
            "Player": info["name"], "Pos": info["pos"], "Team": info["team"], "Opp": info["opp"],
            "Game": info["game"], "Kickoff (UTC)": info["kickoff"],
        }
        for site in sites:
            ppr = results[site][1]
            row[f"{site} Proj PPR"] = round(ppr, 2) if ppr is not None else ""
        row["Avg Proj PPR"] = round(sum(projections) / len(projections), 2)
        for site in sites:
            row[f"{site} Proj Source"] = results[site][2]
        for key, label in STAT_BANDS:
            for site in sites:
                if site == "FP":  # a projection, not a line: one value per stat
                    if key in FANTASYPROS_STATS:
                        row[f"{label} FP Proj"] = results["FP"][0].get(key, "")
                    continue
                v = site_stats.get(site, {}).get(key)
                row[f"{label} {site} Line"] = v["line"] if v else ""
                row[f"{label} {site} Over"] = fmt_american(v["over"]) if v else ""
                row[f"{label} {site} Under"] = fmt_american(v["under"]) if v else ""
                if key == "rush_rec_tds":
                    row[f"{label} {site} %"] = pct(v["p_over"]) if v else ""
                if key in EXP_STATS:
                    exp = results[site][0].get(key)
                    row[f"{label} {site} Exp"] = round(exp, 2) if exp is not None else ""
        rows.append(row)

    rows.sort(key=lambda r: r["Avg Proj PPR"], reverse=True)
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
def all_columns(rows):
    """Every column that appears in any row, in first-seen order (rows can have different keys)."""
    return list(dict.fromkeys(k for r in rows for k in r))


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_columns(rows), restval="")
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
    headers = all_columns(rows)
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


def write_html(path, rankings, comparison, meta=None):
    """Self-contained interactive page (data embedded, no server needed)."""
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "rankings.html")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    payload = json.dumps({"generated": datetime.now().astimezone().isoformat(), "meta": meta or {},
                          "rows": rankings, "comparison": comparison})
    payload = payload.replace("</", "<\\/")  # keep "</script>" out of the inline script
    with open(path, "w", encoding="utf-8") as f:
        f.write(template.replace("/*__DATA__*/null", payload, 1))


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="nfl_ppr_rankings.xlsx", help="output .xlsx path")
    ap.add_argument("--no-csv", action="store_true", help="skip writing the CSV copies")
    ap.add_argument("--open", action="store_true", help="open the interactive HTML page in your browser")
    ap.add_argument("--no-sleeper", action="store_true", help="skip pulling Sleeper lines")
    ap.add_argument("--no-fantasypros", action="store_true", help="skip pulling FantasyPros projections")
    args = ap.parse_args()

    print("Fetching Underdog lines...")
    try:
        data = fetch()
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Failed to fetch {API_URL}: {e}")

    by_app, flat = collect_props(data)
    if not flat:
        sys.exit("No NFL props are posted on Underdog right now.")
    sleeper = None
    if not args.no_sleeper:  # Sleeper is optional: any failure warns and the run continues
        try:
            sleeper = SleeperScraper().scrape()
            print(f"Sleeper: {len(sleeper.sleeper_lines)} NFL lines")
        except Exception as e:  # noqa: BLE001
            print(f"Warning: couldn't load Sleeper lines ({e}); continuing without Sleeper")

    fantasypros = None
    if not args.no_fantasypros:  # optional too
        try:
            fantasypros = FantasyProsScraper().scrape()
            print(f"FantasyPros week {fantasypros.week}: {len(fantasypros.fantasypros_projections)} consensus "
                  f"projections (public pages show the top 10 per position)")
        except Exception as e:  # noqa: BLE001
            print(f"Warning: couldn't load FantasyPros projections ({e}); continuing without FantasyPros")

    rankings = build_rankings(by_app, sleeper, fantasypros)
    counts = ", ".join(f"{sum(1 for r in rankings if r.get(f'{c} Proj PPR', '') != '')} {name}"
                       for c, name in SITES if f"{c} Proj PPR" in rankings[0])
    print(f"Ranked {len(rankings)} players (projections: {counts})")
    comparison = build_comparison(by_app, sleeper)
    flat.sort(key=lambda r: (r["Kickoff (UTC)"], r["Game"], r["Player"], r["Stat"]))

    sheets = [("PPR Rankings", rankings), ("Odds Comparison", comparison), ("Underdog Props", flat)]
    if sleeper:
        sheets.append(("Sleeper Props", sleeper.line_rows()))
    if fantasypros:
        sheets.append(("FantasyPros Projections", fantasypros.projection_rows()))
    sheets = [(n, rows) for n, rows in sheets if rows]
    write_xlsx(args.output, sheets)
    print(f"Wrote {args.output}  (sheets: {', '.join(n for n, _ in sheets)})")

    html_path = os.path.splitext(args.output)[0] + ".html"
    meta = {"sites": [c for c, _ in SITES if f"{c} Proj PPR" in rankings[0]],
            "bands": [{"key": k, "label": label, "exp": k in EXP_STATS, "pct": k == "rush_rec_tds",
                       "fp": k in FANTASYPROS_STATS} for k, label in STAT_BANDS],
            "fantasypros_week": fantasypros.week if fantasypros else None}
    write_html(html_path, rankings, comparison, meta)
    print(f"Wrote {html_path}  (interactive: rankings + odds comparison)")
    if not args.no_csv:
        base = os.path.splitext(args.output)[0]
        for name, rows in sheets:
            suffix = "" if name == "PPR Rankings" else "_" + name.lower().replace(" ", "_")
            write_csv(f"{base}{suffix}.csv", rows)
        print(f"Wrote {len(sheets)} CSV files ({base}*.csv)")

    print(f"\nTop 15 ({datetime.now():%Y-%m-%d %H:%M}):")
    for r in rankings[:15]:
        print(f"{r['Rank']:>3}. {r['Player']:<24} {r['Pos Rank']:<6} {r['Team'] or '':<4} vs {r['Opp'] or '':<4} {r['Avg Proj PPR']:>6.2f}")

    if args.open:
        webbrowser.open("file://" + os.path.abspath(html_path))


if __name__ == "__main__":
    main()
