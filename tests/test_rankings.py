"""Underdog parsing, PPR rankings, Sleeper merge and the odds comparison, on saved sample data."""

import unittest

import ppr_rankings
from ppr_rankings import FANTASY_POINTS_LABEL, build_comparison, build_rankings, collect_props, no_vig_over_prob
from tests import fixtures
from tests.test_sleeper import loaded_scraper


def parsed():
    return collect_props(fixtures.underdog_data())


def by_player(rows):
    return {r["Player"]: r for r in rows}


class CollectProps(unittest.TestCase):
    def test_every_nfl_line_kept_and_other_sports_dropped(self):
        _, flat = parsed()
        self.assertEqual(len(flat), 18)
        self.assertNotIn("Some Guard", {r["Player"] for r in flat})

    def test_team_and_opponent(self):
        by_app, _ = parsed()
        self.assertEqual((by_app["a-wilson"]["team"], by_app["a-wilson"]["opp"]), ("NYJ", "BUF"))   # home
        self.assertEqual((by_app["a-allen"]["team"], by_app["a-allen"]["opp"]), ("BUF", "NYJ"))     # away

    def test_most_balanced_duplicate_line_wins(self):
        by_app, _ = parsed()
        self.assertEqual(by_app["a-wilson"]["stats"]["receiving_yds"]["line"], 65.5)

    def test_flat_row_has_all_price_fields(self):
        _, flat = parsed()
        row = [r for r in flat if r["Player"] == "Josh Allen" and r["Stat Key"] == "passing_tds"][0]
        self.assertEqual((row["Over Odds"], row["Under Odds"]), ("-150", "+120"))
        self.assertEqual(row["No-Vig Over %"], round(no_vig_over_prob("-150", "+120") * 100, 1))
        for field in ("Over Decimal", "Under Payout Mult", "Over Fantasy Odds", "Under Fantasy Prob %", "Line Type", "Updated"):
            self.assertNotEqual(row[field], "", field)


class NoProjections(unittest.TestCase):
    def test_model_is_gone(self):
        for name in ("project", "project_site", "poisson_sf", "poisson_mean_for", "PPR"):
            self.assertFalse(hasattr(ppr_rankings, name), name)

    def test_no_projection_columns(self):
        from tests.test_fantasypros import loaded_scraper as fp_scraper
        rows = build_rankings(parsed()[0], loaded_scraper(), fp_scraper())
        cols = {k for r in rows for k in r}
        self.assertFalse([k for k in cols if "Proj PPR" in k or "Proj Source" in k or k.endswith(" Exp")])


class Rankings(unittest.TestCase):
    """Underdog only (Sleeper and FantasyPros unavailable)."""

    def setUp(self):
        self.rows = build_rankings(parsed()[0])
        self.p = by_player(self.rows)

    def test_offensive_players_with_any_stat_line(self):
        # Pearsall only has a 1Q line and Warner is a defender
        self.assertEqual(set(self.p), {"Josh Allen", "Garrett Wilson", "Brian Thomas", "Bam Knight", "George Kittle"})

    def test_no_other_source_columns(self):
        self.assertFalse([k for k in self.rows[0] if " SL " in k or " FP " in k])

    def test_ranked_by_underdog_fantasy_points_line(self):
        self.assertEqual([(r["Player"], r["Rank"], r["Pos Rank"]) for r in self.rows[:2]],
                         [("Josh Allen", 1, "QB1"), ("George Kittle", 2, "TE1")])
        self.assertEqual({r["Rank"] for r in self.rows[2:]}, {""})          # no Fantasy Pts line: unranked
        self.assertEqual(list(self.rows[0])[:3], ["Rank", "Pos Rank", "Player"])

    def test_stat_columns(self):
        allen = self.p["Josh Allen"]
        self.assertEqual((allen["Pass TDs UD Line"], allen["Pass TDs UD Over"], allen["Pass TDs UD Under"]), (1.5, "-150", "+120"))
        self.assertEqual(allen["Fantasy Pts UD Line"], 22.5)
        self.assertEqual(allen["Anytime TD UD %"], round(no_vig_over_prob("+100", "-130") * 100, 1))
        self.assertEqual(self.p["Garrett Wilson"]["Rec Yds UD Line"], 65.5)       # the balanced duplicate
        self.assertEqual(self.p["Garrett Wilson"]["Pass Yds UD Line"], "")
        self.assertEqual(self.p["Bam Knight"]["Rush Yds UD Line"], "")           # no line, and nothing derived


class SideBySide(unittest.TestCase):
    """Underdog + Sleeper."""

    def setUp(self):
        self.rows = build_rankings(parsed()[0], loaded_scraper())
        self.p = by_player(self.rows)

    def test_players_from_either_site(self):
        # Underdog's five + two offensive players only Sleeper offers (the kicker isn't included)
        self.assertEqual(set(self.p), {"Josh Allen", "Garrett Wilson", "Brian Thomas", "Bam Knight", "George Kittle",
                                       "Jalen Smith", "Jaden Smith"})
        smith = self.p["Jalen Smith"]
        self.assertEqual((smith["Team"], smith["Game"], smith["Receptions SL Line"], smith["Receptions UD Line"]),
                         ("MIA", "", 3.5, ""))

    def test_ranked_by_sleeper_line_first(self):
        self.assertEqual((self.rows[0]["Player"], self.rows[0]["Rank"]), ("Josh Allen", 1))   # Sleeper FP line 24.5
        self.assertEqual(self.rows[1]["Player"], "George Kittle")    # unranked, ordered next by Underdog's line
        self.assertEqual(self.rows[1]["Rank"], "")

    def test_sleeper_stat_columns(self):
        allen = self.p["Josh Allen"]
        self.assertEqual((allen["Pass Yds SL Line"], allen["Pass Yds SL Over"], allen["Pass Yds SL Under"]), (245.5, "-128", "-128"))
        self.assertEqual((allen["Pass Yds UD Line"], allen["Pass Yds UD Over"]), (250.5, "-110"))
        self.assertEqual(allen["Fantasy Pts SL Line"], 24.5)
        self.assertEqual(self.p["Brian Thomas"]["Rec Yds SL Under"], "-200")
        self.assertEqual(self.p["Bam Knight"]["Rush Att SL Line"], 10.5)

    def test_column_order_pairs_sites(self):
        keys = list(self.rows[0])
        i = keys.index("Pass Yds UD Line")
        self.assertEqual(keys[i:i + 6], ["Pass Yds UD Line", "Pass Yds UD Over", "Pass Yds UD Under",
                                         "Pass Yds SL Line", "Pass Yds SL Over", "Pass Yds SL Under"])


class WithFantasyPros(unittest.TestCase):
    """All three sources."""

    def setUp(self):
        from tests.test_fantasypros import loaded_scraper as fp_scraper
        self.rows = build_rankings(parsed()[0], loaded_scraper(), fp_scraper())
        self.p = by_player(self.rows)

    def test_fantasypros_values(self):
        allen = self.p["Josh Allen"]
        self.assertEqual((allen["Fantasy Pts FP Proj"], allen["Pass Yds FP Proj"]), (24.1, 250.7))
        self.assertEqual(self.p["Garrett Wilson"]["Receptions FP Proj"], "")    # not in FantasyPros' top 10
        self.assertFalse([k for k in allen if k.startswith("Pass Yds FP ") and k != "Pass Yds FP Proj"])
        self.assertNotIn("Long Rush FP Proj", allen)        # FantasyPros doesn't project it

    def test_matched_through_suffix_and_team_alias(self):
        self.assertEqual(self.p["Brian Thomas"]["Fantasy Pts FP Proj"], 14.5)
        self.assertNotIn("Brian Thomas Jr.", self.p)       # not added twice

    def test_fantasypros_only_player(self):
        gibbs = self.p["Jahmyr Gibbs"]
        self.assertEqual((gibbs["Team"], gibbs["Opp"], gibbs["Fantasy Pts FP Proj"]), ("DET", "NE", 24.4))
        self.assertEqual(gibbs["Rank"], "")                 # ranked by Sleeper's line, which he doesn't have
        self.assertEqual(self.rows[1]["Player"], "Jahmyr Gibbs")   # but ordered next by FantasyPros


class Comparison(unittest.TestCase):
    def setUp(self):
        self.rows = build_comparison(parsed()[0], loaded_scraper())

    def find(self, player, stat):
        return [r for r in self.rows if r["Player"] == player and r["Stat Key"] == stat][0]

    def test_counts_by_site(self):
        sites = [r["Sites"] for r in self.rows]
        self.assertEqual((sites.count("Both"), sites.count("Underdog"), sites.count("Sleeper")), (3, 14, 4))

    def test_side_by_side_values(self):
        r = self.find("Brian Thomas", "receiving_yds")
        self.assertEqual((r["UD Line"], r["SL Line"], r["Line Δ (SL−UD)"]), (60.5, 62.5, 2.0))
        sl_p = no_vig_over_prob("+100", "-200")
        self.assertEqual(r["SL Over %"], round(sl_p * 100, 1))
        self.assertEqual(r["Over % Δ (SL−UD)"], round((sl_p - 0.5) * 100, 1))
        self.assertEqual(r["SL Recent Over %"], 67)
        self.assertEqual(r["SL Recent Results"], "50 70 80")

    def test_sleeper_only_row_uses_underdog_name_and_game(self):
        r = self.find("Bam Knight", "rushing_att")
        self.assertEqual((r["Sites"], r["Game"], r["UD Line"], r["SL Line"]), ("Sleeper", "ARI @ SF", "", 10.5))

    def test_sleeper_only_player_gets_game_from_team(self):
        r = self.find("Jake Moody", "kicking_points")
        self.assertEqual((r["Team"], r["Opp"], r["Game"]), ("SF", "ARI", "ARI @ SF"))

    def test_fantasy_points_labelled_with_scoring(self):
        self.assertEqual(self.find("Josh Allen", "fantasy_points")["Stat"], FANTASY_POINTS_LABEL)

    def test_without_sleeper(self):
        rows = build_comparison(parsed()[0], None)
        self.assertEqual(len(rows), 17)
        self.assertEqual({r["Sites"] for r in rows}, {"Underdog"})


if __name__ == "__main__":
    unittest.main()
