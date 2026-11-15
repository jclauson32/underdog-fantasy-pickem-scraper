#!/usr/bin/env python3
"""
Projected vs actual: how Underdog's lines, Sleeper's lines and FantasyPros' projections compared with what
players actually did.

Every ppr_rankings.py run saves a snapshot to history/snapshots/. This script takes each player's LAST snapshot
before his game kicked off, fetches the actual box scores once that week is final (from Sleeper's public stats
feed), and compares the two:

    python3 projected_vs_actual.py               # every completed week that has snapshots
    python3 projected_vs_actual.py --week 10     # one week
    python3 projected_vs_actual.py --refresh     # re-download actual stats (stat corrections)

Writes projected_vs_actual.xlsx (+ CSVs) with three sheets:
  * Summary          - per source and stat: how many, average projected vs actual, average miss, how often
                       the over hit, how often the side the odds favoured won
  * Fantasy Pts Rank - per week and source: how well each source's fantasy-points number ordered players
                       (rank correlation with actual fantasy points; 1 = perfect order)
  * Details          - every player, stat and source: projected, odds, actual, difference, over/under

Actual fantasy points use each source's scoring: Underdog's line is compared with half-PPR points, Sleeper's line
and FantasyPros' projection with full-PPR points (Sleeper's default scoring).
"""

import argparse
import os
import sys
from collections import defaultdict

from history import (load_snapshots, load_week, nfl_week, parse_time, save_week, week_complete)
from ppr_rankings import STAT_BANDS, no_vig_over_prob, write_csv, write_xlsx
from sleeper_scraper import SleeperScraper, normalize_name

SOURCES = (("UD", "Underdog", "Line"), ("SL", "Sleeper", "Line"), ("FP", "FantasyPros", "Proj"))

# Our stat keys -> Sleeper box-score fields (summed). Fantasy points depend on the source's scoring.
ACTUAL_FIELDS = {
    "passing_yds": ("pass_yd",), "passing_tds": ("pass_td",), "passing_ints": ("pass_int",),
    "passing_comps": ("pass_cmp",), "passing_att": ("pass_att",), "passing_long": ("pass_lng",),
    "passing_and_rushing_yds": ("pass_yd", "rush_yd"),
    "rushing_yds": ("rush_yd",), "rushing_att": ("rush_att",), "rushing_long": ("rush_lng",),
    "receiving_rec": ("rec",), "receiving_yds": ("rec_yd",), "receiving_tgts": ("rec_tgt",),
    "receiving_long": ("rec_lng",), "rush_rec_yds": ("rush_yd", "rec_yd"), "rush_rec_tds": ("rush_td", "rec_td"),
    "fumbles_lost": ("fum_lost",),
}
FANTASY_POINTS_FIELD = {"UD": "pts_half_ppr", "SL": "pts_ppr", "FP": "pts_ppr"}


def actual_value(stat_key, site, stats):
    if stat_key == "fantasy_points":
        return stats.get(FANTASY_POINTS_FIELD[site], 0.0)
    return sum(stats.get(f, 0) for f in ACTUAL_FIELDS[stat_key])


# --------------------------------------------------------------------------- #
# Projected side: each player's last snapshot before kickoff
# --------------------------------------------------------------------------- #
def closing_rows(snapshots, fallback_state=None):
    """{(season, week, name key, team): row} using each player's latest pre-kickoff snapshot.
    Rows without a kickoff (e.g. a game already off Underdog) only count if nothing earlier had him."""
    fallback_state = fallback_state or {}
    best = {}  # key -> (row, had_kickoff)
    for snap in sorted(snapshots, key=lambda s: s["taken_at"]):
        taken = parse_time(snap["taken_at"])
        season = snap.get("season") or fallback_state.get("season")
        start = snap.get("season_start_date") or fallback_state.get("season_start_date")
        for row in snap["rows"]:
            kickoff = parse_time(row.get("Kickoff (UTC)"))
            if kickoff and taken >= kickoff:
                continue                                    # taken after the game started: not a projection
            week = nfl_week(kickoff, start) if kickoff else snap.get("week")
            if not season or not week:
                continue
            key = (str(season), int(week), normalize_name(row["Player"]), row.get("Team") or "")
            if not kickoff and key in best and best[key][1]:
                continue                                    # keep the earlier snapshot that had his kickoff
            best[key] = (row, kickoff is not None)
    return {k: v[0] for k, v in best.items()}


# --------------------------------------------------------------------------- #
# Actual side
# --------------------------------------------------------------------------- #
class Results:
    """One week's actual stats, findable by player name (+ team)."""

    def __init__(self, rows):
        self.by_name_team, self.by_name = {}, defaultdict(list)
        for r in rows:
            key = normalize_name(r["name"])
            self.by_name_team[(key, r["team"])] = r
            self.by_name[key].append(r)

    def find(self, name, team):
        key = normalize_name(name)
        r = self.by_name_team.get((key, team))
        if r:
            return r
        same = self.by_name.get(key, [])
        return same[0] if len(same) == 1 else None


def get_results(season, week, season_start_date, scraper, refresh=False, now=None):
    """Actual stats for a week (downloaded once and kept in history/results), or None if not final yet."""
    if not refresh:
        cached = load_week("results", season, week)
        if cached is not None:
            return cached
    if not week_complete(season_start_date, week, now):
        return None
    rows = scraper.fetch_stats(season, week)
    save_week("results", season, week, rows)
    return rows


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare(closing, results_by_week):
    """Detail rows: one per player x stat x source that had a number before kickoff and played."""
    details, did_not_play = [], 0
    for (season, week, _, team), row in sorted(closing.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[1]["Player"])):
        results = results_by_week.get((season, week))
        if results is None:
            continue
        actual_row = results.find(row["Player"], team)
        if actual_row is None:
            did_not_play += 1
            continue
        stats = actual_row["stats"]
        for key, label in STAT_BANDS:
            for site, source, kind in SOURCES:
                projected = num(row.get(f"{label} {site} {kind}"))
                if projected is None:
                    continue
                actual = actual_value(key, site, stats)
                over, under = row.get(f"{label} {site} Over", ""), row.get(f"{label} {site} Under", "")
                p_over = no_vig_over_prob(over, under) if kind == "Line" else None
                result = "Over" if actual > projected else "Under" if actual < projected else "Push"
                favored = ""
                if p_over is not None and abs(p_over - 0.5) > 1e-9 and result != "Push":
                    favored = "Yes" if (p_over > 0.5) == (result == "Over") else "No"
                details.append({
                    "Season": season, "Week": week, "Player": row["Player"], "Pos": row.get("Pos", ""),
                    "Team": team, "Opp": row.get("Opp", ""), "Stat": label, "Source": source,
                    "Type": "Line" if kind == "Line" else "Projection",
                    "Projected": projected, "Over Odds": over, "Under Odds": under,
                    "Over % (no-vig)": round(p_over * 100, 1) if p_over is not None else "",
                    "Actual": round(actual, 2), "Actual − Projected": round(actual - projected, 2),
                    "Result": result, "Favored Side Won": favored,
                })
    return details, did_not_play


def summarize(details):
    groups = defaultdict(list)
    for d in details:
        groups[(d["Source"], d["Stat"])].append(d)
    order = {label: i for i, (_, label) in enumerate(STAT_BANDS)}
    src_order = {name: i for i, (_, name, _) in enumerate(SOURCES)}
    rows = []
    for (source, stat), ds in sorted(groups.items(), key=lambda kv: (order[kv[0][1]], src_order[kv[0][0]])):
        n = len(ds)
        diffs = [d["Actual − Projected"] for d in ds]
        fav = [d for d in ds if d["Favored Side Won"]]
        implied = [d["Over % (no-vig)"] for d in ds if d["Over % (no-vig)"] != ""]
        rows.append({
            "Stat": stat, "Source": source, "Type": ds[0]["Type"], "Players": n,
            "Avg Projected": round(sum(d["Projected"] for d in ds) / n, 2),
            "Avg Actual": round(sum(d["Actual"] for d in ds) / n, 2),
            "Avg Actual − Projected": round(sum(diffs) / n, 2),
            "Avg Miss (abs)": round(sum(abs(x) for x in diffs) / n, 2),
            "Over %": round(100 * sum(d["Result"] == "Over" for d in ds) / n, 1),
            "Under %": round(100 * sum(d["Result"] == "Under" for d in ds) / n, 1),
            "Odds Implied Over %": round(sum(implied) / len(implied), 1) if implied else "",
            "Favored Side Won %": round(100 * sum(d["Favored Side Won"] == "Yes" for d in fav) / len(fav), 1) if fav else "",
        })
    return rows


def spearman(xs, ys):
    """Rank correlation (ties get their average rank). 1 = same order, 0 = unrelated."""
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx, vy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return cov / (vx * vy) ** 0.5 if vx and vy else None


def ranking_accuracy(details):
    groups = defaultdict(list)
    for d in details:
        if d["Stat"] == "Fantasy Pts":
            groups[(d["Season"], d["Week"], d["Source"])].append(d)
    rows = []
    for (season, week, source), ds in sorted(groups.items()):
        rho = spearman([d["Projected"] for d in ds], [d["Actual"] for d in ds]) if len(ds) >= 3 else None
        rows.append({"Season": season, "Week": week, "Source": source, "Players": len(ds),
                     "Rank Correlation": round(rho, 3) if rho is not None else "",
                     "Avg Miss (abs)": round(sum(abs(d["Actual − Projected"]) for d in ds) / len(ds), 2)})
    return rows


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--week", type=int, help="only this week")
    ap.add_argument("--season", help="only this season (default: any)")
    ap.add_argument("--refresh", action="store_true", help="re-download actual stats even if saved")
    ap.add_argument("-o", "--output", default="projected_vs_actual.xlsx", help="output .xlsx path")
    ap.add_argument("--no-csv", action="store_true", help="skip the CSV copies")
    args = ap.parse_args(argv)

    snapshots = load_snapshots()
    if not snapshots:
        sys.exit("No snapshots yet. Run ppr_rankings.py before games (it saves one each run), then run this "
                 "after that week's games are final.")

    scraper = SleeperScraper()
    fallback_state = {}
    if any(not s.get("season") or not s.get("season_start_date") for s in snapshots):
        try:
            fallback_state = scraper.fetch_state()
        except Exception as e:  # noqa: BLE001
            print(f"Warning: couldn't load the NFL season state ({e}); snapshots saved without it are skipped")

    closing = closing_rows(snapshots, fallback_state)
    starts = {str(s.get("season") or fallback_state.get("season")): s.get("season_start_date")
              or fallback_state.get("season_start_date") for s in snapshots}
    weeks = sorted({(season, week) for season, week, _, _ in closing
                    if (not args.week or week == args.week) and (not args.season or season == args.season)})
    if not weeks:
        sys.exit("No snapshots match that week/season.")

    results_by_week = {}
    for season, week in weeks:
        try:
            rows = get_results(season, week, starts[season], scraper, args.refresh)
        except Exception as e:  # noqa: BLE001
            print(f"Week {week}: couldn't load actual stats ({e})")
            continue
        if rows is None:
            print(f"Week {week}: games not final yet (actual stats are fetched after Tuesday) - skipped")
            continue
        results_by_week[(season, week)] = Results(rows)
        print(f"Week {week}: {len(rows)} players' actual stats")

    details, dnp = compare({k: v for k, v in closing.items() if (k[0], k[1]) in results_by_week}, results_by_week)
    if not details:
        sys.exit("Nothing to compare yet: no completed week has snapshots taken before kickoff.")
    summary, ranks = summarize(details), ranking_accuracy(details)

    sheets = [("Summary", summary), ("Fantasy Pts Rank", ranks), ("Details", details)]
    write_xlsx(args.output, sheets)
    if not args.no_csv:
        base = os.path.splitext(args.output)[0]
        for name, rows in sheets:
            write_csv(f"{base}_{name.lower().replace(' ', '_')}.csv", rows)
    print(f"\nWrote {args.output}  ({len(details)} comparisons; {dnp} players with lines didn't play and are left out)")

    print("\nFantasy points, projected vs actual:")
    print(f"  {'Source':<12} {'Players':>7} {'Avg miss':>9} {'Actual−proj':>12} {'Over %':>7} {'Rank corr':>10}")
    for s in [s for s in summary if s["Stat"] == "Fantasy Pts"]:
        rc = [r["Rank Correlation"] for r in ranks if r["Source"] == s["Source"] and r["Rank Correlation"] != ""]
        rc_txt = f"{sum(rc) / len(rc):.2f}" if rc else "-"
        print(f"  {s['Source']:<12} {s['Players']:>7} {s['Avg Miss (abs)']:>9} {s['Avg Actual − Projected']:>+12} "
              f"{s['Over %']:>7} {rc_txt:>10}")


if __name__ == "__main__":
    main()
