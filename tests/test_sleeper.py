"""SleeperScraper on saved sample data: parsing lines, name matching, outputs and caching (no network)."""

import json
import os
import tempfile
import time
import unittest
from unittest import mock

import sleeper_scraper
from sleeper_scraper import SleeperScraper, normalize_name
from tests import fixtures


def loaded_scraper():
    s = SleeperScraper()
    s.process_data(fixtures.sleeper_lines(), fixtures.SLEEPER_PLAYERS)
    return s


class NormalizeName(unittest.TestCase):
    def test_variants_agree(self):
        self.assertEqual(normalize_name("D.J. Moore"), normalize_name("DJ Moore"))
        self.assertEqual(normalize_name("James Cook III"), "james cook")
        self.assertEqual(normalize_name("Brian Thomas Jr."), "brian thomas")
        self.assertEqual(normalize_name("Amon-Ra St. Brown"), "amon ra st brown")
        self.assertEqual(normalize_name("Ja'Marr Chase"), "jamarr chase")
        self.assertEqual(normalize_name(""), "")


class Lines(unittest.TestCase):
    def test_only_active_nfl_lines(self):
        s = loaded_scraper()
        self.assertEqual(len(s.sleeper_lines), 7)
        self.assertNotIn("points", {ln["wager_type"] for ln in s.sleeper_lines})

    def test_line_fields(self):
        s = loaded_scraper()
        ln = s.lines_for("Brian Thomas", "JAX")["receiving_yds"]   # wager type mapped to Underdog's key
        self.assertEqual(ln["line"], 62.5)
        self.assertEqual((ln["over_american"], ln["under_american"]), ("+100", "-200"))
        self.assertEqual((ln["picks_over"], ln["picks_under"], ln["popularity"]), (7, 3, 0.5))
        self.assertEqual(ln["recent_values"], [50, 70, 80])

    def test_line_rows_flatten_recent_results(self):
        rows = loaded_scraper().line_rows()
        allen = [r for r in rows if r["name"] == "Josh Allen" and r["wager_type"] == "passing_yards"][0]
        self.assertEqual(allen["recent_values"], "300 200 250 260")

    def test_unknown_wager_type_kept_as_is(self):
        s = SleeperScraper()
        s.process_data([fixtures._sl_line("4984", "brand_new_stat", 1.5, "1.8", "1.8", "BUF", "QB")],
                       fixtures.SLEEPER_PLAYERS)
        self.assertEqual(s.sleeper_lines[0]["stat_key"], "brand_new_stat")


class Matching(unittest.TestCase):
    def setUp(self):
        self.s = loaded_scraper()

    def test_exact(self):
        self.assertEqual(self.s.player_id_for("Josh Allen", "BUF"), "4984")
        self.assertEqual(self.s.lines_for("Josh Allen", "BUF")["fantasy_points"]["line"], 24.5)

    def test_suffix_dropped(self):
        self.assertEqual(self.s.player_id_for("Brian Thomas", "JAX"), "11631")

    def test_team_abbreviation_differs_but_name_unique(self):
        self.assertEqual(self.s.player_id_for("Josh Allen", "BUFF"), "4984")

    def test_nickname_via_unique_last_name_on_team(self):
        self.assertEqual(self.s.player_id_for("Bam Knight", "ARI"), "8122")

    def test_ambiguous_last_name_is_not_guessed(self):
        self.assertIsNone(self.s.player_id_for("JJ Smith", "MIA"))

    def test_unknown(self):
        self.assertIsNone(self.s.player_id_for("Nobody Here", "BUF"))
        self.assertIsNone(self.s.player_id_for("", "BUF"))
        self.assertEqual(self.s.lines_for("Nobody Here", "BUF"), {})


class Fetching(unittest.TestCase):
    def test_scrape_fetches_lines_and_players(self):
        s = SleeperScraper()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sleeper_scraper, "PLAYERS_CACHE", os.path.join(tmp, "players.json")):
            routes = {s.config["sleeper_lines_url"]: fixtures.sleeper_lines(),
                      s.config["sleeper_players_url"]: fixtures.SLEEPER_PLAYERS}
            with mock.patch.object(s, "_get_json", side_effect=routes.__getitem__):
                s.scrape()
        self.assertEqual(len(s.sleeper_lines), 7)
        self.assertEqual(s.players["777"]["name"], "Jake Moody")

    def test_player_list_is_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "players.json")
            with mock.patch.object(sleeper_scraper, "PLAYERS_CACHE", cache):
                s = SleeperScraper()
                with mock.patch.object(s, "_get_json", return_value=fixtures.SLEEPER_PLAYERS) as get:
                    s.fetch_players()
                    s.fetch_players()
                self.assertEqual(get.call_count, 1)          # second call served from disk
                with open(cache) as f:
                    self.assertEqual(json.load(f), fixtures.SLEEPER_PLAYERS)

                old = time.time() - 2 * 24 * 3600            # stale cache -> fetched again
                os.utime(cache, (old, old))
                with mock.patch.object(s, "_get_json", return_value={}) as get:
                    s.fetch_players()
                self.assertEqual(get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
