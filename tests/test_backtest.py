import unittest

from soccer_ratings.backtest import (
    evaluate_match,
    implied_probabilities_from_odds,
    match_outcome,
    run_league_backtest,
)
from soccer_ratings.odds import calculate_match_probabilities


def make_match(**overrides) -> dict:
    match = {
        "date": "01.02.23",
        "competition": "UK1",
        "home_team": "Home FC",
        "away_team": "Away FC",
        "home_odds": 1.8,
        "draw_odds": 3.6,
        "away_odds": 4.5,
        "home_rating": 2200.0,
        "away_rating": 2000.0,
        "home_goals": 2,
        "away_goals": 1,
        "result": "2:1",
        "focal_team": "Home FC",
        "source_team_path": "/Home-FC/1/",
    }
    match.update(overrides)
    return match


class ImpliedProbabilitiesTests(unittest.TestCase):
    def test_normalizes_to_one_and_removes_overround(self) -> None:
        probabilities, overround = implied_probabilities_from_odds(2.0, 3.0, 4.0)

        self.assertGreater(overround, 1.0)
        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=6)
        self.assertGreater(probabilities["home"], probabilities["draw"])
        self.assertGreater(probabilities["draw"], probabilities["away"])

    def test_zero_odds_returns_zero_probabilities(self) -> None:
        probabilities, overround = implied_probabilities_from_odds(0.0, 0.0, 0.0)

        self.assertEqual(probabilities, {"home": 0.0, "draw": 0.0, "away": 0.0})
        self.assertEqual(overround, 0.0)


class MatchOutcomeTests(unittest.TestCase):
    def test_home_win(self) -> None:
        self.assertEqual(match_outcome(2, 1), "home")

    def test_away_win(self) -> None:
        self.assertEqual(match_outcome(0, 3), "away")

    def test_draw(self) -> None:
        self.assertEqual(match_outcome(1, 1), "draw")


class EvaluateMatchTests(unittest.TestCase):
    def test_uses_model_from_match_time_ratings(self) -> None:
        match = make_match()
        row = evaluate_match(match)

        expected_probabilities = calculate_match_probabilities(2200.0, 2000.0)
        self.assertEqual(row["model_probabilities"], expected_probabilities)
        self.assertEqual(row["outcome"], "home")

    def test_missing_field_returns_none(self) -> None:
        match = make_match(home_goals=None, away_goals=None)
        self.assertIsNone(evaluate_match(match))

    def test_non_positive_odds_returns_none(self) -> None:
        match = make_match(home_odds=0.0)
        self.assertIsNone(evaluate_match(match))

    def test_flags_value_bet_when_model_edge_exceeds_threshold(self) -> None:
        # Short home price (implied ~71%) against a much stronger model view.
        match = make_match(home_rating=2500.0, away_rating=1900.0, home_odds=2.2, draw_odds=3.4, away_odds=3.0)
        row = evaluate_match(match, edge_threshold_percent=5.0, stake=2.0)

        self.assertIn("home", row["value_bets"])
        self.assertEqual(row["staked"], 2.0 * len(row["value_bets"]))
        # Home won, so a home value bet should be profitable at those odds.
        self.assertGreater(row["profit"], 0.0)

    def test_no_value_bets_when_model_and_market_agree(self) -> None:
        # Odds implying almost exactly the model's own probabilities.
        model_probabilities = calculate_match_probabilities(2200.0, 2000.0)
        match = make_match(
            home_odds=round(1.0 / model_probabilities["home"], 4),
            draw_odds=round(1.0 / model_probabilities["draw"], 4),
            away_odds=round(1.0 / model_probabilities["away"], 4),
        )
        row = evaluate_match(match, edge_threshold_percent=5.0)

        self.assertEqual(row["value_bets"], [])
        self.assertEqual(row["staked"], 0.0)
        self.assertEqual(row["profit"], 0.0)


class RunLeagueBacktestTests(unittest.TestCase):
    def test_empty_matches_returns_zero_summary(self) -> None:
        result = run_league_backtest([])

        self.assertEqual(result["matches_evaluated"], 0)
        self.assertIn("edge_threshold_percent", result)
        self.assertIn("stake", result)

    def test_skips_unplayed_fixtures(self) -> None:
        matches = [
            make_match(home_goals=None, away_goals=None, result=None),
            make_match(),
        ]
        result = run_league_backtest(matches)

        self.assertEqual(result["matches_evaluated"], 1)

    def test_calibration_buckets_cover_every_evaluated_outcome(self) -> None:
        matches = [make_match(), make_match(home_goals=0, away_goals=0, result="0:0")]
        result = run_league_backtest(matches)

        total_bucketed = sum(bucket["count"] for bucket in result["calibration"])
        self.assertEqual(total_bucketed, result["matches_evaluated"] * 3)

    def test_roi_reflects_consistently_underpriced_favorite(self) -> None:
        # Model strongly favors home; market prices home short but home
        # always wins, so value bets on home should show a positive ROI.
        matches = [
            make_match(
                home_rating=2500.0,
                away_rating=1900.0,
                home_odds=2.2,
                draw_odds=3.4,
                away_odds=3.0,
                home_goals=2,
                away_goals=0,
                result="2:0",
            )
            for _ in range(5)
        ]
        result = run_league_backtest(matches, edge_threshold_percent=5.0, stake=1.0)

        self.assertGreater(result["value_bet_count"], 0)
        self.assertEqual(result["value_bet_wins"], result["value_bet_count"])
        self.assertEqual(result["hit_rate_percent"], 100.0)
        self.assertGreater(result["roi_percent"], 0.0)

    def test_matches_list_preserved_for_display(self) -> None:
        matches = [make_match(home_team="A"), make_match(home_team="B")]
        result = run_league_backtest(matches)

        self.assertEqual(len(result["matches"]), 2)
        self.assertEqual({row["home_team"] for row in result["matches"]}, {"A", "B"})


if __name__ == "__main__":
    unittest.main()
