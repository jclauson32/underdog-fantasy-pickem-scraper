"""Underdog parsing, PPR rankings, Sleeper merge and the odds comparison, on saved sample data."""

import unittest

from ppr_rankings import (FANTASY_POINTS_LABEL, FP_TO_PPR_PER_REC, NO_TD_SOURCE, build_comparison, build_rankings,
                          collect_props, no_vig_over_prob, poisson_mean_for, project, project_site)
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


class Rankings(unittest.TestCase):
    """Underdog only (Sleeper unavailable)."""

    def setUp(self):
        self.rows = build_rankings(parsed()[0])
        self.p = by_player(self.rows)

    def test_only_offensive_players_with_usable_lines(self):
        self.assertEqual(set(self.p), {"Josh Allen", "Garrett Wilson", "Brian Thomas", "Bam Knight", "George Kittle"})

    def test_no_sleeper_columns(self):
        self.assertFalse([k for k in self.rows[0] if " SL " in k or k.startswith("SL ")])

    def test_hand_calculated_projection(self):
        # 60.5 rec yds at 50/50 -> 6.05 pts, plus 1 pt per expected catch (4.5 line at 50/50)
        self.assertAlmostEqual(self.p["Brian Thomas"]["UD Proj PPR"], round(6.05 + poisson_mean_for(4.5, 0.5), 2))

    def test_rushing_derived_from_combo_line(self):
        knight = self.p["Bam Knight"]
        self.assertAlmostEqual(knight["Rush Yds UD Exp"], 40.0)
        self.assertAlmostEqual(knight["UD Proj PPR"], 5.05)   # 0.1 x (40 rush + 10.5 rec)

    def test_qb_scoring(self):
        s = parsed()[0]["a-allen"]["stats"]
        e = {k: project(k, v["line"], v["p_over"]) for k, v in s.items()}
        expected = 0.04 * e["passing_yds"] + 4 * e["passing_tds"] - 2 * e["passing_ints"] + 0.1 * e["rushing_yds"] + 6 * e["rush_rec_tds"]
        self.assertAlmostEqual(self.p["Josh Allen"]["UD Proj PPR"], round(expected, 2))
        self.assertEqual(self.p["Josh Allen"]["Avg Proj PPR"], self.p["Josh Allen"]["UD Proj PPR"])

    def test_sources(self):
        self.assertEqual(self.p["Josh Allen"]["UD Proj Source"], "Props")
        self.assertEqual(self.p["Brian Thomas"]["UD Proj Source"], NO_TD_SOURCE)   # no anytime-TD line
        self.assertEqual(self.p["George Kittle"]["UD Proj Source"], "Fantasy Pts line")
        self.assertEqual(self.p["George Kittle"]["UD Proj PPR"], 8.5)

    def test_ranks(self):
        projs = [r["Avg Proj PPR"] for r in self.rows]
        self.assertEqual(projs, sorted(projs, reverse=True))
        self.assertEqual([r["Rank"] for r in self.rows], list(range(1, len(self.rows) + 1)))
        self.assertEqual([r["Pos Rank"] for r in self.rows if r["Pos"] == "WR"], ["WR1", "WR2"])
        self.assertEqual(list(self.rows[0])[:3], ["Rank", "Pos Rank", "Player"])

    def test_stat_columns(self):
        allen = self.p["Josh Allen"]
        self.assertEqual((allen["Pass TDs UD Line"], allen["Pass TDs UD Over"], allen["Pass TDs UD Under"]), (1.5, "-150", "+120"))
        self.assertEqual(allen["Fantasy Pts UD Line"], 22.5)
        self.assertEqual(allen["Anytime TD UD %"], round(no_vig_over_prob("+100", "-130") * 100, 1))
        self.assertIn("Pass Yds UD Exp", allen)          # feeds the projection
        self.assertNotIn("Pass Att UD Exp", allen)       # doesn't
        self.assertEqual(self.p["Garrett Wilson"]["Pass Yds UD Line"], "")


class ProjectSite(unittest.TestCase):
    def test_fantasy_points_fallback_per_site_scoring(self):
        stats = {"fantasy_points": {"line": 10.0, "over": "-110", "under": "-110", "p_over": 0.5},
                 "period_1_receiving_rec": {"line": 0.5, "over": "-110", "under": "-110", "p_over": 0.5}}
        self.assertEqual(project_site(stats, FP_TO_PPR_PER_REC["SL"])[1:], (10.0, "Fantasy Pts line"))
        stats["receiving_tgts"] = {"line": 6.5, "over": "-110", "under": "-110", "p_over": 0.5}
        self.assertEqual(project_site(stats, FP_TO_PPR_PER_REC["UD"])[1], 10.0)  # no expected catches to convert

    def test_nothing_usable(self):
        self.assertEqual(project_site({}, 0.5), ({}, None, ""))


class SideBySide(unittest.TestCase):
    """Both sites."""

    def setUp(self):
        self.rows = build_rankings(parsed()[0], loaded_scraper())
        self.p = by_player(self.rows)

    def test_players_from_either_site(self):
        # Underdog's five + two offensive players only Sleeper offers (the kicker isn't ranked)
        self.assertEqual(set(self.p), {"Josh Allen", "Garrett Wilson", "Brian Thomas", "Bam Knight", "George Kittle",
                                       "Jalen Smith", "Jaden Smith"})

    def test_sleeper_projection_from_sleeper_lines(self):
        allen = self.p["Josh Allen"]
        self.assertAlmostEqual(allen["SL Proj PPR"], round(245.5 * 0.04, 2))   # only a pass-yds line on Sleeper
        self.assertEqual(allen["SL Proj Source"], NO_TD_SOURCE)
        self.assertAlmostEqual(allen["Avg Proj PPR"], round((allen["UD Proj PPR"] + allen["SL Proj PPR"]) / 2, 2), places=1)
        thomas = self.p["Brian Thomas"]
        exp = project("receiving_yds", 62.5, no_vig_over_prob("+100", "-200"))
        self.assertAlmostEqual(thomas["SL Proj PPR"], round(0.1 * exp, 2))
        self.assertAlmostEqual(thomas["Rec Yds SL Exp"], round(exp, 2))

    def test_one_site_only(self):
        self.assertEqual(self.p["Garrett Wilson"]["SL Proj PPR"], "")
        self.assertEqual(self.p["Garrett Wilson"]["Avg Proj PPR"], self.p["Garrett Wilson"]["UD Proj PPR"])
        self.assertEqual(self.p["Bam Knight"]["SL Proj PPR"], "")     # Sleeper only has rush attempts for him
        smith = self.p["Jalen Smith"]
        self.assertEqual((smith["UD Proj PPR"], smith["Team"], smith["Game"]), ("", "MIA", ""))
        self.assertAlmostEqual(smith["SL Proj PPR"], round(poisson_mean_for(3.5, 0.5), 2))

    def test_sleeper_stat_columns(self):
        allen = self.p["Josh Allen"]
        self.assertEqual((allen["Pass Yds SL Line"], allen["Pass Yds SL Over"], allen["Pass Yds SL Under"]), (245.5, "-128", "-128"))
        self.assertEqual((allen["Pass Yds UD Line"], allen["Pass Yds UD Over"]), (250.5, "-110"))
        self.assertEqual(allen["Fantasy Pts SL Line"], 24.5)
        self.assertEqual(self.p["Brian Thomas"]["Rec Yds SL Under"], "-200")

    def test_column_order_pairs_sites(self):
        keys = list(self.rows[0])
        i = keys.index("Pass Yds UD Line")
        self.assertEqual(keys[i:i + 8], ["Pass Yds UD Line", "Pass Yds UD Over", "Pass Yds UD Under", "Pass Yds UD Exp",
                                         "Pass Yds SL Line", "Pass Yds SL Over", "Pass Yds SL Under", "Pass Yds SL Exp"])


class WithFantasyPros(unittest.TestCase):
    """All three sites."""

    def setUp(self):
        from tests.test_fantasypros import loaded_scraper as fp_scraper
        self.rows = build_rankings(parsed()[0], loaded_scraper(), fp_scraper())
        self.p = by_player(self.rows)

    def test_projection_and_average(self):
        allen = self.p["Josh Allen"]
        self.assertEqual(allen["FP Proj PPR"], 24.1)
        self.assertEqual(allen["FP Proj Source"], "FantasyPros consensus")
        expected = (allen["UD Proj PPR"] + allen["SL Proj PPR"] + 24.1) / 3
        self.assertAlmostEqual(allen["Avg Proj PPR"], round(expected, 2), places=1)

    def test_matched_through_suffix_and_team_alias(self):
        self.assertEqual(self.p["Brian Thomas"]["FP Proj PPR"], 14.5)
        self.assertNotIn("Brian Thomas Jr.", self.p)       # not added twice

    def test_fantasypros_only_player(self):
        gibbs = self.p["Jahmyr Gibbs"]
        self.assertEqual((gibbs["UD Proj PPR"], gibbs["SL Proj PPR"], gibbs["FP Proj PPR"]), ("", "", 24.4))
        self.assertEqual((gibbs["Team"], gibbs["Opp"]), ("DET", "NE"))
        self.assertEqual(gibbs["Rank"], 1)

    def test_one_projection_column_per_stat(self):
        allen = self.p["Josh Allen"]
        self.assertEqual(allen["Pass Yds FP Proj"], 250.7)
        self.assertEqual(allen["Fantasy Pts FP Proj"], 24.1)
        self.assertEqual(self.p["Garrett Wilson"]["Receptions FP Proj"], "")    # not in FantasyPros' top 10
        self.assertFalse([k for k in allen if k.startswith("Pass Yds FP ") and k != "Pass Yds FP Proj"])
        self.assertNotIn("Long Rush FP Proj", allen)        # FantasyPros doesn't project it


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
