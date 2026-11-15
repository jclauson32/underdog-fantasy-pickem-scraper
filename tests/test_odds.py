"""Odds conversions and the projection model, checked against hand-calculated answers."""

import math
import unittest

from ppr_rankings import (american_to_prob, fmt_american, no_vig_over_prob, poisson_mean_for, poisson_sf,
                          project, recent_over_pct)
from sleeper_scraper import multiplier_to_american


class AmericanOdds(unittest.TestCase):
    def test_favourite_and_underdog(self):
        self.assertAlmostEqual(american_to_prob("-110"), 110 / 210)
        self.assertAlmostEqual(american_to_prob("+150"), 100 / 250)
        self.assertAlmostEqual(american_to_prob(-200), 2 / 3)

    def test_bad_input(self):
        self.assertIsNone(american_to_prob(""))
        self.assertIsNone(american_to_prob(None))
        self.assertIsNone(american_to_prob("abc"))

    def test_format(self):
        self.assertEqual(fmt_american("150"), "+150")
        self.assertEqual(fmt_american(-110.0), "-110")
        self.assertEqual(fmt_american(""), "")


class NoVig(unittest.TestCase):
    def test_even_market_is_fifty_fifty(self):
        self.assertAlmostEqual(no_vig_over_prob("-110", "-110"), 0.5)

    def test_margin_removed_and_sums_to_one(self):
        po = no_vig_over_prob("-150", "+130")
        pu = no_vig_over_prob("+130", "-150")
        self.assertAlmostEqual(po + pu, 1.0)
        raw = american_to_prob("-150")
        self.assertAlmostEqual(po, raw / (raw + american_to_prob("+130")))

    def test_one_sided_market(self):
        self.assertAlmostEqual(no_vig_over_prob("+400", None), 0.2 / 1.05)
        self.assertAlmostEqual(no_vig_over_prob(None, "-400"), 1 - 0.8 / 1.05)
        self.assertIsNone(no_vig_over_prob(None, None))


class Poisson(unittest.TestCase):
    def test_survival_function(self):
        self.assertAlmostEqual(poisson_sf(0.5, 1.0), 1 - math.exp(-1))            # P(X >= 1)
        self.assertAlmostEqual(poisson_sf(1.5, 2.0), 1 - 3 * math.exp(-2))        # P(X >= 2)

    def test_mean_recovers_known_lambda(self):
        for lam, line in [(1.0, 0.5), (2.3, 1.5), (5.2, 4.5)]:
            self.assertAlmostEqual(poisson_mean_for(line, poisson_sf(line, lam)), lam, places=4)

    def test_extreme_probabilities_are_clamped(self):
        self.assertGreater(poisson_mean_for(0.5, 0.0), 0)
        self.assertLess(poisson_mean_for(0.5, 1.0), 20)


class Projection(unittest.TestCase):
    def test_yards_at_fifty_fifty_equal_the_line(self):
        self.assertAlmostEqual(project("receiving_yds", 65.5, 0.5), 65.5)

    def test_yards_move_with_the_odds(self):
        self.assertGreater(project("rushing_yds", 50.5, 0.6), 50.5)
        self.assertLess(project("rushing_yds", 50.5, 0.4), 50.5)
        self.assertGreaterEqual(project("rushing_yds", 0.5, 0.01), 0.0)

    def test_counts_use_poisson(self):
        self.assertAlmostEqual(project("rush_rec_tds", 0.5, 1 - math.exp(-0.7)), 0.7, places=4)

    def test_unknown_odds_fall_back_to_line(self):
        self.assertEqual(project("receiving_rec", 4.5, None), 4.5)
        self.assertEqual(project("tackles", 7.5, 0.7), 7.5)  # not a modelled stat


class SleeperMultipliers(unittest.TestCase):
    def test_conversion(self):
        self.assertEqual(multiplier_to_american("2.00"), "+100")
        self.assertEqual(multiplier_to_american("3.0"), "+200")
        self.assertEqual(multiplier_to_american("1.5"), "-200")
        self.assertEqual(multiplier_to_american("1.77"), "-130")

    def test_round_trip_probability(self):
        # a multiplier m pays m per 1 staked, so its implied probability is 1/m
        for m in ("1.25", "1.78", "2.5", "4.0"):
            self.assertAlmostEqual(american_to_prob(multiplier_to_american(m)), 1 / float(m), places=2)

    def test_bad_input(self):
        for bad in ("", None, "x", "1.0", "0.5"):
            self.assertEqual(multiplier_to_american(bad), "")


class RecentHitRate(unittest.TestCase):
    def test_share_over_line(self):
        self.assertEqual(recent_over_pct({"line": 60.5, "recent_values": [50, 70, 80, None]}), 67)
        self.assertEqual(recent_over_pct({"line": 1.5, "recent_values": []}), "")
        self.assertEqual(recent_over_pct(None), "")


if __name__ == "__main__":
    unittest.main()
