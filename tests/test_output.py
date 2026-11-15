"""Spreadsheet/CSV/HTML writers and a full offline run of the script."""

import contextlib
import csv
import io
import os
import tempfile
import unittest
import urllib.error
import zipfile
from datetime import datetime, timezone
from unittest import mock
from xml.dom import minidom

import fantasypros_scraper
import history
import ppr_rankings
import sleeper_scraper
from ppr_rankings import write_csv, write_html, write_xlsx
from tests import fixtures

ROWS = [{"Rank": 1, "Player": "A & B <x>", "Line": 12.5, "Note": ""},
        {"Rank": 2, "Player": "</script><b>", "Line": 3, "Note": "ok"}]


class Writers(unittest.TestCase):
    def test_rows_with_different_columns(self):
        rows = [{"a": 1, "b": 2}, {"a": 3, "c": 4}]
        self.assertEqual(ppr_rankings.all_columns(rows), ["a", "b", "c"])
        with tempfile.TemporaryDirectory() as tmp:
            write_csv(os.path.join(tmp, "t.csv"), rows)
            with open(os.path.join(tmp, "t.csv"), newline="") as f:
                self.assertEqual(list(csv.DictReader(f))[1], {"a": "3", "b": "", "c": "4"})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_xlsx_is_valid(self):
        write_xlsx(self.path("t.xlsx"), [("First", ROWS), ("Second", ROWS[:1])])
        with zipfile.ZipFile(self.path("t.xlsx")) as z:
            for name in z.namelist():
                minidom.parseString(z.read(name))          # every part is well-formed XML
            workbook = z.read("xl/workbook.xml").decode()
            sheet = z.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn('name="First"', workbook)
        self.assertIn('name="Second"', workbook)
        self.assertIn("A &amp; B &lt;x&gt;", sheet)          # text escaped
        self.assertIn("<v>12.5</v>", sheet)                  # numbers stay numbers
        self.assertIn('autoFilter ref="A1:D3"', sheet)

    def test_csv_round_trip(self):
        write_csv(self.path("t.csv"), ROWS)
        with open(self.path("t.csv"), newline="", encoding="utf-8") as f:
            back = list(csv.DictReader(f))
        self.assertEqual(back[0]["Player"], "A & B <x>")
        self.assertEqual(back[1]["Line"], "3")

    def test_html_embeds_data_safely(self):
        write_html(self.path("t.html"), ROWS, [], {"note": "x"})
        with open(self.path("t.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertNotIn("/*__DATA__*/null", html)
        self.assertEqual(html.count("</script>"), 1)         # the player name can't close the script tag
        self.assertIn('"note": "x"', html)
        self.assertIn('"comparison": []', html)


class FullRun(unittest.TestCase):
    """Runs main() end to end with the network replaced by the sample data."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "out.xlsx")
        hist = mock.patch.object(history, "HISTORY_DIR", os.path.join(self.tmp.name, "history"))
        hist.start()
        self.addCleanup(hist.stop)
        # Snapshot as if taken the morning of the sample games, so the test doesn't depend on today's date
        morning = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        snap = mock.patch.object(ppr_rankings, "save_snapshot",
                                 lambda rows, state: history.save_snapshot(rows, state, morning))
        snap.start()
        self.addCleanup(snap.stop)
        cache = mock.patch.object(sleeper_scraper, "PLAYERS_CACHE", os.path.join(self.tmp.name, "players.json"))
        cache.start()
        self.addCleanup(cache.stop)

    def run_main(self, sleeper_get, fantasypros_down=False):
        config = sleeper_scraper.SleeperScraper().config
        routes = {config["sleeper_lines_url"]: fixtures.sleeper_lines(),
                  config["sleeper_state_url"]: fixtures.SLEEPER_STATE,
                  config["sleeper_players_url"]: fixtures.SLEEPER_PLAYERS}

        def default_get(_self, url):
            return routes[url]

        pages = fixtures.fantasypros_pages()

        def fantasypros_get(_self, url):
            if fantasypros_down:
                raise urllib.error.URLError("offline")
            return pages[url.split("/")[-1].split(".")[0]]

        argv = ["ppr_rankings.py", "-o", self.out]
        with mock.patch.object(ppr_rankings, "fetch", return_value=fixtures.underdog_data()), \
                mock.patch.object(sleeper_scraper.SleeperScraper, "_get_json", sleeper_get or default_get), \
                mock.patch.object(fantasypros_scraper.FantasyProsScraper, "_get_html", fantasypros_get), \
                mock.patch.object(fantasypros_scraper.time, "sleep"), \
                mock.patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()) as out:
            ppr_rankings.main()
        return out.getvalue()

    def sheet_names(self):
        with zipfile.ZipFile(self.out) as z:
            wb = minidom.parseString(z.read("xl/workbook.xml"))
        return [s.getAttribute("name") for s in wb.getElementsByTagName("sheet")]

    def read_csv(self, suffix=""):
        with open(os.path.join(self.tmp.name, f"out{suffix}.csv"), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_writes_every_output(self):
        log = self.run_main(None)
        self.assertIn("8 players; ranked by Sleeper Fantasy Pts line (PPR) (1 have it)", log)
        self.assertEqual(self.sheet_names(), ["PPR Rankings", "Odds Comparison", "Underdog Props", "Sleeper Props",
                                              "FantasyPros Projections"])
        for suffix in ("", "_odds_comparison", "_underdog_props", "_sleeper_props", "_fantasypros_projections"):
            self.assertTrue(self.read_csv(suffix), suffix)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "out.html")))
        rankings = self.read_csv()
        self.assertEqual(rankings[0]["Rank"], "1")
        self.assertIn("Pass Yds SL Line", rankings[0])
        self.assertIn("Fantasy Pts FP Proj", rankings[0])
        snaps = history.load_snapshots()                        # the run saved a snapshot to history/
        self.assertEqual((len(snaps), snaps[0]["week"], len(snaps[0]["rows"])), (1, 10, 8))
        self.assertIn("Fantasy Pts SL Line", rankings[0])
        with open(os.path.join(self.tmp.name, "out.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn('"sites": ["UD", "SL", "FP"]', page)
        self.assertIn('"label": "Week 10 (in progress)"', page)     # week-by-week data from the snapshot

    def test_sleeper_outage_does_not_stop_the_run(self):
        def down(_self, url):
            raise urllib.error.URLError("offline")

        log = self.run_main(down)
        self.assertIn("couldn't load Sleeper lines", log)
        self.assertEqual(self.sheet_names(), ["PPR Rankings", "Odds Comparison", "Underdog Props", "FantasyPros Projections"])
        self.assertNotIn("Pass Yds SL Line", self.read_csv()[0])

    def test_fantasypros_outage_does_not_stop_the_run(self):
        log = self.run_main(None, fantasypros_down=True)
        self.assertIn("couldn't load FantasyPros projections", log)
        self.assertNotIn("Fantasy Pts FP Proj", self.read_csv()[0])
        self.assertIn("Pass Yds SL Line", self.read_csv()[0])

    def test_no_underdog_props_exits(self):
        with mock.patch.object(ppr_rankings, "fetch", return_value={}), \
                mock.patch("sys.argv", ["ppr_rankings.py", "-o", self.out]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                ppr_rankings.main()


if __name__ == "__main__":
    unittest.main()
