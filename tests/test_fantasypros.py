"""FantasyProsScraper on saved sample pages: parsing, stat mapping, matching, outputs (no network)."""

import unittest
from unittest import mock

from fantasypros_scraper import FantasyProsScraper, opponent_from_game
from tests import fixtures


def loaded_scraper():
    s = FantasyProsScraper()
    s.process_data(fixtures.fantasypros_pages())
    return s


class Parsing(unittest.TestCase):
    def setUp(self):
        self.s = loaded_scraper()
        self.p = {p["name"]: p for p in self.s.fantasypros_projections}

    def test_players_week_and_update(self):
        self.assertEqual(set(self.p), {"Josh Allen", "Jahmyr Gibbs", "Brian Thomas Jr.", "George Kittle"})  # no-fpts row dropped
        self.assertEqual((self.s.week, self.s.updated), (10, "Nov 15, 2026"))
        self.assertEqual([p["fpts"] for p in self.s.fantasypros_projections], [24.4, 24.1, 16.1, 14.5])  # sorted

    def test_stat_mapping(self):
        allen = self.p["Josh Allen"]["stats"]
        self.assertEqual((allen["passing_yds"], allen["passing_comps"], allen["fantasy_points"]), (250.7, 20.1, 24.1))
        self.assertAlmostEqual(allen["passing_and_rushing_yds"], 284.0)
        gibbs = self.p["Jahmyr Gibbs"]["stats"]
        self.assertEqual(gibbs["receiving_rec"], 4.6)
        self.assertAlmostEqual(gibbs["rush_rec_tds"], 1.2)
        self.assertAlmostEqual(gibbs["rush_rec_yds"], 128.8)

    def test_partial_fields_by_position(self):
        self.assertEqual(self.p["Josh Allen"]["stats"]["rush_rec_tds"], 0.7)       # QBs: no receiving TDs listed
        self.assertEqual(self.p["George Kittle"]["stats"]["rush_rec_tds"], 0.6)    # TEs: no rushing TDs listed
        self.assertNotIn("passing_and_rushing_yds", self.p["Jahmyr Gibbs"]["stats"])  # only for passers

    def test_team_alias_and_opponent(self):
        thomas = self.p["Brian Thomas Jr."]
        self.assertEqual((thomas["team"], thomas["opp"]), ("JAX", "TEN"))
        self.assertEqual(self.p["Jahmyr Gibbs"]["opp"], "NE")

    def test_layout_change_is_reported(self):
        with self.assertRaises(ValueError):
            FantasyProsScraper().process_data({"qb": "<html>new layout</html>"})


class Opponent(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(opponent_from_game("NEDET", "DET"), "NE")
        self.assertEqual(opponent_from_game("NEDET", "NE"), "DET")
        self.assertEqual(opponent_from_game("JACTEN", "JAC"), "TEN")
        self.assertEqual(opponent_from_game("BUFNYJ", "KC"), "")
        self.assertEqual(opponent_from_game("", "KC"), "")


class Matching(unittest.TestCase):
    def setUp(self):
        self.s = loaded_scraper()

    def test_lookup(self):
        self.assertEqual(self.s.lookup("Josh Allen", "BUF")["fpts"], 24.1)
        self.assertEqual(self.s.lookup("Brian Thomas", "JAX")["fpts"], 14.5)   # suffix + team alias
        self.assertEqual(self.s.lookup("Brian Thomas", "JAC")["fpts"], 14.5)
        self.assertIsNone(self.s.lookup("Nobody", "BUF"))
        self.assertIsNone(self.s.lookup("", "BUF"))


class Output(unittest.TestCase):
    def test_projection_rows_share_columns(self):
        rows = loaded_scraper().projection_rows()
        self.assertEqual(len({tuple(r) for r in rows}), 1)    # every row has the same columns
        gibbs = [r for r in rows if r["Player"] == "Jahmyr Gibbs"][0]
        self.assertEqual((gibbs["Opp"], gibbs["PPR"], gibbs["pass_yds"]), ("NE", 24.4, ""))
        self.assertNotIn("_filterGame", gibbs)


class Fetching(unittest.TestCase):
    def test_fetches_each_position_page(self):
        s = FantasyProsScraper(pause=0)
        pages = fixtures.fantasypros_pages()
        with mock.patch.object(s, "_get_html", side_effect=lambda url: pages[url.split("/")[-1].split(".")[0]]) as get:
            s.scrape()
        urls = [c.args[0] for c in get.call_args_list]
        self.assertEqual([u.split("/")[-1] for u in urls],
                         [f"{p}.php?scoring=PPR" for p in ("qb", "rb", "wr", "te")])
        self.assertTrue(all(u.startswith("https://www.fantasypros.com/nfl/projections/") for u in urls))
        self.assertEqual(len(s.fantasypros_projections), 4)


if __name__ == "__main__":
    unittest.main()
