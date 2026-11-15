"""Snapshots, week numbering and the projected-vs-actual comparison, on sample data (no network)."""

import contextlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from unittest import mock

import history
import projected_vs_actual as pva
from sleeper_scraper import SleeperScraper, stats_row
from tests import fixtures

KICK = "2026-11-15T18:00:00Z"
STATE = fixtures.SLEEPER_STATE


def row(player, team, pos, kickoff=KICK, **values):
    return {"Player": player, "Team": team, "Pos": pos, "Opp": "", "Kickoff (UTC)": kickoff, **values}


def snapshot(taken_at, rows, **extra):
    return {"taken_at": taken_at, "season": "2026", "season_start_date": "2026-09-09", "week": 10, "rows": rows, **extra}


def sample_snapshots():
    early = snapshot("2026-11-15T12:00:00Z", [
        row("Josh Allen", "BUF", "QB", **{"Pass Yds UD Line": 250.5, "Pass Yds UD Over": "-110", "Pass Yds UD Under": "-110"}),
    ])
    late = snapshot("2026-11-15T17:00:00Z", [   # last one before kickoff -> used
        row("Josh Allen", "BUF", "QB", **{
            "Pass Yds UD Line": 260.5, "Pass Yds UD Over": "-110", "Pass Yds UD Under": "-110",
            "Fantasy Pts UD Line": 22.5, "Fantasy Pts SL Line": 24.5, "Fantasy Pts FP Proj": 24.1}),
        row("Garrett Wilson", "NYJ", "WR", **{"Rec Yds SL Line": 65.5, "Rec Yds SL Over": "-150", "Rec Yds SL Under": "+120",
                                              "Fantasy Pts SL Line": 12.5}),
        row("Brian Thomas", "JAX", "WR", **{"Receptions UD Line": 4.5, "Receptions UD Over": "-130", "Receptions UD Under": "+100",
                                            "Fantasy Pts SL Line": 10.5}),
        row("Bam Knight", "ARI", "RB", **{"Rush Yds UD Line": 40.5, "Rush Yds UD Over": "-110", "Rush Yds UD Under": "-110"}),
    ])
    after = snapshot("2026-11-15T19:00:00Z", [  # taken after kickoff -> ignored
        row("Josh Allen", "BUF", "QB", **{"Pass Yds UD Line": 300.5, "Pass Yds UD Over": "-110", "Pass Yds UD Under": "-110"}),
        row("Josh Allen", "BUF", "QB", kickoff="", **{"Fantasy Pts FP Proj": 99.0}),    # no kickoff: earlier row wins
    ])
    return [after, early, late]   # deliberately out of order


def sample_results():
    return pva.Results([r for r in map(stats_row, fixtures.sleeper_stats_week()) if r])


class Weeks(unittest.TestCase):
    def test_nfl_week(self):
        for kickoff, week in [("2026-09-11T00:20:00Z", 1),    # opening Thursday night
                              ("2026-09-15T00:15:00Z", 1),    # week 1 Monday night (Tuesday in UTC)
                              ("2026-11-13T01:15:00Z", 10),   # week 10 Thursday night
                              ("2026-11-17T01:15:00Z", 10),   # week 10 Monday night
                              ("2026-11-20T01:15:00Z", 11)]:
            self.assertEqual(history.nfl_week(kickoff, "2026-09-09"), week, kickoff)
        self.assertIsNone(history.nfl_week("", "2026-09-09"))
        self.assertIsNone(history.nfl_week(KICK, None))

    def test_week_complete_after_tuesday(self):
        tue = datetime(2026, 11, 17, 23, 0, tzinfo=timezone.utc)
        wed = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(history.week_complete("2026-09-09", 10, tue))
        self.assertTrue(history.week_complete("2026-09-09", 10, wed))


class Snapshots(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            taken = datetime(2026, 11, 15, 15, 50, 45, tzinfo=timezone.utc)
            path = history.save_snapshot([{"Player": "A"}], STATE, taken, root=tmp)
            self.assertTrue(path.endswith("2026-11-15T15-50-45Z.json"))
            snap = history.load_snapshots(root=tmp)[0]
            self.assertEqual((snap["taken_at"], snap["season"], snap["week"], snap["rows"]),
                             ("2026-11-15T15:50:45Z", "2026", 10, [{"Player": "A"}]))

    def test_closing_rows_use_last_snapshot_before_kickoff(self):
        closing = pva.closing_rows(sample_snapshots())
        allen = closing[("2026", 10, "josh allen", "BUF")]
        self.assertEqual(allen["Pass Yds UD Line"], 260.5)          # not 250.5 (older) or 300.5 (after kickoff)
        self.assertEqual(allen["Fantasy Pts FP Proj"], 24.1)        # not the kickoff-less 99.0
        self.assertEqual(len(closing), 4)

    def test_season_from_fallback_state(self):
        snap = snapshot("2026-11-15T12:00:00Z", [row("Josh Allen", "BUF", "QB")], season=None, season_start_date=None)
        self.assertEqual(pva.closing_rows([snap]), {})
        self.assertIn(("2026", 10, "josh allen", "BUF"), pva.closing_rows([snap], STATE))


class Actuals(unittest.TestCase):
    def test_stats_row_skips_players_who_did_not_play(self):
        rows = [stats_row(r) for r in fixtures.sleeper_stats_week()]
        self.assertIsNone(rows[3])
        self.assertEqual((rows[0]["name"], rows[0]["team"], rows[0]["stats"]["pass_yd"]), ("Josh Allen", "BUF", 280.0))

    def test_actual_values_per_source_scoring(self):
        stats = {"pts_ppr": 11.55, "pts_half_ppr": 9.05, "rush_yd": 5, "rec_yd": 60, "rush_td": 1}
        self.assertEqual(pva.actual_value("fantasy_points", "UD", stats), 9.05)   # Underdog: half PPR
        self.assertEqual(pva.actual_value("fantasy_points", "SL", stats), 11.55)
        self.assertEqual(pva.actual_value("fantasy_points", "FP", stats), 11.55)
        self.assertEqual(pva.actual_value("rush_rec_yds", "UD", stats), 65)
        self.assertEqual(pva.actual_value("rush_rec_tds", "UD", stats), 1)
        self.assertEqual(pva.actual_value("receiving_rec", "UD", stats), 0)       # missing stat = 0

    def test_results_lookup(self):
        res = sample_results()
        self.assertEqual(res.find("Brian Thomas", "JAX")["name"], "Brian Thomas Jr.")
        self.assertIsNone(res.find("Bam Knight", "ARI"))

    def test_get_results_waits_for_final_then_caches(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(history, "HISTORY_DIR", tmp):
            scraper = mock.Mock(spec=SleeperScraper)
            scraper.fetch_stats.return_value = [{"name": "X", "team": "BUF", "stats": {}}]
            tue = datetime(2026, 11, 17, tzinfo=timezone.utc)
            wed = datetime(2026, 11, 18, tzinfo=timezone.utc)
            self.assertIsNone(pva.get_results("2026", 10, "2026-09-09", scraper, now=tue))
            scraper.fetch_stats.assert_not_called()
            self.assertEqual(len(pva.get_results("2026", 10, "2026-09-09", scraper, now=wed)), 1)
            pva.get_results("2026", 10, "2026-09-09", scraper, now=wed)       # second time: from disk
            self.assertEqual(scraper.fetch_stats.call_count, 1)
            pva.get_results("2026", 10, "2026-09-09", scraper, refresh=True, now=wed)
            self.assertEqual(scraper.fetch_stats.call_count, 2)


class Comparison(unittest.TestCase):
    def setUp(self):
        self.details, self.dnp = pva.compare(pva.closing_rows(sample_snapshots()), {("2026", 10): sample_results()})
        self.d = {(d["Player"], d["Stat"], d["Source"]): d for d in self.details}

    def test_line_vs_actual(self):
        d = self.d[("Josh Allen", "Pass Yds", "Underdog")]
        self.assertEqual((d["Projected"], d["Actual"], d["Actual − Projected"], d["Result"]), (260.5, 280.0, 19.5, "Over"))
        self.assertEqual(d["Favored Side Won"], "")                 # -110/-110: nobody favoured

    def test_fantasy_points_per_source(self):
        self.assertEqual(self.d[("Josh Allen", "Fantasy Pts", "Underdog")]["Actual"], 29.2)
        self.assertEqual(self.d[("Josh Allen", "Fantasy Pts", "FantasyPros")]["Type"], "Projection")
        self.assertEqual(self.d[("Garrett Wilson", "Fantasy Pts", "Sleeper")]["Actual"], 11.55)

    def test_push_and_favourites(self):
        wilson = self.d[("Garrett Wilson", "Rec Yds", "Sleeper")]
        self.assertEqual((wilson["Result"], wilson["Favored Side Won"]), ("Push", ""))
        thomas = self.d[("Brian Thomas", "Receptions", "Underdog")]     # over favoured at -130, he caught 3
        self.assertEqual((thomas["Result"], thomas["Favored Side Won"]), ("Under", "No"))

    def test_players_who_did_not_play_are_left_out(self):
        self.assertEqual(self.dnp, 1)
        self.assertFalse([d for d in self.details if d["Player"] == "Bam Knight"])

    def test_summary(self):
        s = {(r["Source"], r["Stat"]): r for r in pva.summarize(self.details)}
        sl = s[("Sleeper", "Fantasy Pts")]   # Allen 24.5 -> 29.2, Wilson 12.5 -> 11.55, Thomas 10.5 -> 7.0
        self.assertEqual(sl["Players"], 3)
        self.assertAlmostEqual(sl["Avg Actual − Projected"], round((4.7 - 0.95 - 3.5) / 3, 2))
        self.assertAlmostEqual(sl["Avg Miss (abs)"], round((4.7 + 0.95 + 3.5) / 3, 2))
        self.assertEqual((sl["Over %"], sl["Under %"]), (33.3, 66.7))
        self.assertEqual(s[("Underdog", "Receptions")]["Favored Side Won %"], 0.0)

    def test_rank_correlation(self):
        ranks = {r["Source"]: r for r in pva.ranking_accuracy(self.details)}
        self.assertEqual(ranks["Sleeper"]["Rank Correlation"], 1.0)    # 24.5 > 12.5 > 10.5 and 29.2 > 11.55 > 7.0
        self.assertEqual(ranks["Underdog"]["Rank Correlation"], "")    # fewer than 3 players

    def test_spearman(self):
        self.assertAlmostEqual(pva.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(pva.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(pva.spearman([1, 1, 1], [1, 2, 3]))


class FullRun(unittest.TestCase):
    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(history, "HISTORY_DIR", os.path.join(tmp, "h")):
            for s in sample_snapshots():
                history.save_snapshot(s["rows"], STATE, history.parse_time(s["taken_at"]))
            stats = [r for r in map(stats_row, fixtures.sleeper_stats_week()) if r]
            out = os.path.join(tmp, "pva.xlsx")
            with mock.patch.object(SleeperScraper, "fetch_stats", return_value=stats), \
                    mock.patch.object(pva, "week_complete", return_value=True), \
                    contextlib.redirect_stdout(io.StringIO()) as log:
                pva.main(["-o", out])
            with zipfile.ZipFile(out) as z:
                self.assertIn('name="Summary"', z.read("xl/workbook.xml").decode())
            self.assertTrue(os.path.exists(os.path.join(tmp, "pva_details.csv")))
            self.assertIn("1 players with lines didn't play", log.getvalue())
            with open(os.path.join(tmp, "h", "results", "2026_week10.json")) as f:
                self.assertEqual(len(json.load(f)), 3)               # actual stats kept for next time

    def test_no_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(history, "HISTORY_DIR", tmp):
            with self.assertRaises(SystemExit) as e:
                pva.main([])
            self.assertIn("No snapshots yet", str(e.exception))


if __name__ == "__main__":
    unittest.main()
