import unittest

from soccer_ratings.client import compare_teams_from_ratings, dedupe_matches
from soccer_ratings.odds import (
    apply_shin_margin,
    build_dnb_odds,
    build_match_odds,
    calculate_dnb_probabilities,
    calculate_match_probabilities,
)


class OddsModelTests(unittest.TestCase):
    def test_equal_ratings_produce_symmetric_home_and_away_probabilities(self) -> None:
        probabilities = calculate_match_probabilities(2000.0, 2000.0)

        self.assertEqual(probabilities["draw"], 0.3)
        self.assertAlmostEqual(probabilities["home"], probabilities["away"], places=4)

    def test_higher_home_rating_produces_shorter_home_odds(self) -> None:
        odds = build_match_odds(2300.0, 2100.0)

        self.assertLess(odds["home"], odds["away"])
        self.assertGreater(odds["draw"], 0)

    def test_dnb_probabilities_remove_draw_and_normalize(self) -> None:
        dnb_probabilities = calculate_dnb_probabilities(
            {"home": 0.42, "draw": 0.26, "away": 0.32}
        )

        self.assertAlmostEqual(dnb_probabilities["home"] + dnb_probabilities["away"], 1.0, places=4)
        self.assertGreater(dnb_probabilities["home"], dnb_probabilities["away"])

    def test_dnb_odds_favor_stronger_home_team(self) -> None:
        dnb_odds = build_dnb_odds(2300.0, 2100.0)

        self.assertLess(dnb_odds["home"], dnb_odds["away"])

    def test_shin_margin_increases_overround_and_shortens_odds(self) -> None:
        fair_probabilities = {"home": 0.5, "draw": 0.25, "away": 0.25}
        market = apply_shin_margin(fair_probabilities, 6.0)

        self.assertGreater(market["overround"], 1.0)
        self.assertLess(market["odds"]["home"], 2.0)
        self.assertGreater(market["z"], 0.0)


class TeamComparisonTests(unittest.TestCase):
    def test_compare_teams_uses_home_and_away_pools(self) -> None:
        home_rows = [
            {"team": "Arsenal", "rating": 2500.0, "rank": 1},
            {"team": "Liverpool", "rating": 2450.0, "rank": 2},
        ]
        away_rows = [
            {"team": "Chelsea", "rating": 2200.0, "rank": 5},
            {"team": "Liverpool", "rating": 2300.0, "rank": 2},
        ]

        comparison = compare_teams_from_ratings(
            home_rows,
            away_rows,
            home_team="Arsenal",
            away_team="Liverpool",
            margin_percent=5.0,
        )

        self.assertEqual(comparison["home_team"]["team"], "Arsenal")
        self.assertEqual(comparison["away_team"]["team"], "Liverpool")
        self.assertEqual(comparison["rating_gap"], 200.0)
        self.assertLess(comparison["odds"]["home"], comparison["odds"]["away"])
        self.assertLess(comparison["dnb_odds"]["home"], comparison["dnb_odds"]["away"])
        self.assertLess(comparison["market_odds"]["home"], comparison["odds"]["home"])
        self.assertLess(comparison["market_dnb_odds"]["home"], comparison["dnb_odds"]["home"])


class MatchDeduplicationTests(unittest.TestCase):
    def test_dedupe_matches_keeps_one_copy_per_match_identity(self) -> None:
        matches = [
            {
                "date": "22.04.26",
                "competition": "BA1",
                "home_team": "Zrinjski Mostar",
                "away_team": "Borac Banja Luka",
                "result": "1:1",
            },
            {
                "date": "22.04.26",
                "competition": "BA1",
                "home_team": "Zrinjski Mostar",
                "away_team": "Borac Banja Luka",
                "result": "1:1",
            },
            {
                "date": "21.04.26",
                "competition": "BA1",
                "home_team": "Another Team",
                "away_team": "Borac Banja Luka",
                "result": "0:1",
            },
        ]

        deduped = dedupe_matches(matches)

        self.assertEqual(len(deduped), 2)
