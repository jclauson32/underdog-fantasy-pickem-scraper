"""Week-by-week page data: closing lines per week, actual results and summaries (no network)."""

import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import history
import ppr_rankings as pr
import weekly
from sleeper_scraper import stats_row
from tests import fixtures
from tests.test_projected_vs_actual import sample_snapshots

AFTER_WEEK = datetime(2026, 11, 20, tzinfo=timezone.utc)
DURING_WEEK = datetime(2026, 11, 15, 20, tzinfo=timezone.utc)


def scraper():
    s = mock.Mock()
    s.fetch_stats.return_value = [r for r in map(stats_row, fixtures.sleeper_stats_week()) if r]
    return s


class BuildWeeks(unittest.TestCase):
    def build(self, now, sc=None):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(history, "HISTORY_DIR", tmp):
            return weekly.build_weeks(sample_snapshots(), fixtures.SLEEPER_STATE, sc or scraper(), pr.STAT_BANDS,
                                      now=now, log=lambda *_: None)

    def test_in_progress_week(self):
        weeks, season = self.build(DURING_WEEK)
        self.assertEqual([(w["label"], w["final"], len(w["rows"])) for w in weeks], [("Week 10 (in progress)", False, 4)])
        self.assertEqual(season, [])
        allen = [r for r in weeks[0]["rows"] if r["Player"] == "Josh Allen"][0]
        self.assertEqual(allen["Pass Yds UD Line"], 260.5)            # his last pre-kickoff line
        self.assertNotIn("Fantasy Pts Actual", allen)

    def test_final_week_has_actuals_and_summary(self):
        weeks, season = self.build(AFTER_WEEK)
        w = weeks[0]
        self.assertEqual((w["label"], w["final"]), ("Week 10 (final)", True))
        rows = {r["Player"]: r for r in w["rows"]}
        self.assertEqual((rows["Josh Allen"]["Fantasy Pts Actual"], rows["Josh Allen"]["Pass Yds Actual"]), (29.2, 280.0))
        self.assertEqual(rows["Bam Knight"]["Played"], False)
        self.assertNotIn("Fantasy Pts Actual", rows["Bam Knight"])
        sl = [s for s in w["summary"] if (s["Source"], s["Stat"]) == ("Sleeper", "Fantasy Pts")][0]
        self.assertEqual((sl["Players"], sl["Rank Correlation"]), (3, 1.0))
        self.assertEqual(len(season), len(w["summary"]))

    def test_empty_cells_are_dropped(self):
        weeks, _ = self.build(DURING_WEEK)
        self.assertFalse([k for r in weeks[0]["rows"] for k, v in r.items() if v == "" or v is None])

    def test_results_outage_still_shows_week(self):
        sc = mock.Mock()
        sc.fetch_stats.side_effect = OSError("offline")
        weeks, _ = self.build(AFTER_WEEK, sc)
        self.assertEqual((weeks[0]["final"], len(weeks[0]["rows"])), (False, 4))


if __name__ == "__main__":
    unittest.main()
