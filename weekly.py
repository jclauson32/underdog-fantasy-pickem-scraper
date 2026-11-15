"""
Week-by-week data for the interactive page, built from history/ (snapshots and actual results).

For each week: every player's last snapshot before his kickoff (his "closing" lines and projections), plus, once
the week is final, his actual stats in "<stat> Actual" columns and the projected-vs-actual summary.
"""

from projected_vs_actual import (ACTUAL_FIELDS, Results, actual_value, closing_rows, compare, get_results,
                                 ranking_accuracy, summarize)


def slim(row):
    """Drop empty cells: most players have lines for only a few stats, so this keeps the page small."""
    return {k: v for k, v in row.items() if v != "" and v is not None}


def merge_rank_correlation(summary, ranks):
    """Add the average fantasy-points rank correlation per source to its Fantasy Pts summary row."""
    by_source = {}
    for r in ranks:
        if r["Rank Correlation"] != "":
            by_source.setdefault(r["Source"], []).append(r["Rank Correlation"])
    for s in summary:
        vals = by_source.get(s["Source"]) if s["Stat"] == "Fantasy Pts" else None
        s["Rank Correlation"] = round(sum(vals) / len(vals), 3) if vals else ""
    return summary


def build_weeks(snapshots, state, scraper, stat_bands, fetch_results=True, now=None, log=print):
    """[{season, week, label, final, rows, summary}] newest first, plus a season-to-date summary."""
    closing = closing_rows(snapshots, state)
    starts = {}
    for s in snapshots:
        season = str(s.get("season") or state.get("season"))
        starts[season] = s.get("season_start_date") or state.get("season_start_date")

    weeks, all_details = [], []
    for season, week in sorted({(k[0], k[1]) for k in closing}, reverse=True):
        week_rows = {k: v for k, v in closing.items() if (k[0], k[1]) == (season, week)}
        results_rows = None
        if fetch_results and starts.get(season):
            try:
                results_rows = get_results(season, week, starts[season], scraper, now=now)
            except Exception as e:  # noqa: BLE001 - the week still shows, just without actuals
                log(f"Week {week}: couldn't load actual stats ({e})")

        rows, summary = [], []
        if results_rows is not None:
            results = Results(results_rows)
            details, _ = compare(week_rows, {(season, week): results})
            all_details += details
            summary = merge_rank_correlation(summarize(details), ranking_accuracy(details))
            for (_, _, _, team), row in week_rows.items():
                row = dict(row)
                actual = results.find(row["Player"], team)
                row["Played"] = actual is not None
                if actual:
                    for key, label in stat_bands:
                        if key == "fantasy_points" or key in ACTUAL_FIELDS:
                            row[f"{label} Actual"] = round(actual_value(key, "SL", actual["stats"]), 2)
                rows.append(slim(row))
        else:
            rows = [slim(r) for r in week_rows.values()]

        final = results_rows is not None
        weeks.append({"season": season, "week": week, "final": final, "rows": rows, "summary": summary,
                      "label": f"Week {week}" + (" (final)" if final else " (in progress)")})

    season_summary = []
    if all_details:
        season_summary = merge_rank_correlation(summarize(all_details), ranking_accuracy(all_details))
    return weeks, season_summary
