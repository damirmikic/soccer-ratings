import unittest

from soccer_ratings.odds import calculate_match_probabilities
from soccer_ratings.tuning import (
    evaluate_weight_scale,
    sweep_weight_scales,
    walk_forward_predictions,
)


def make_match(**overrides) -> dict:
    match = {
        "date": "01.01.20",
        "home_team": "Alpha",
        "away_team": "Beta",
        "home_odds": 2.0,
        "draw_odds": 3.2,
        "away_odds": 3.8,
        "home_rating": 2000.0,
        "away_rating": 2000.0,
        "home_goals": 1,
        "away_goals": 1,
        "result": "1:1",
    }
    match.update(overrides)
    return match


def draw_heavy_league(count: int) -> list[dict]:
    """count matches, evenly rated, all draws — history strongly predicts
    the next match will also be a draw, so trusting it more should help."""
    return [
        make_match(date=f"{(i % 28) + 1:02d}.01.20", home_team=f"T{i}", away_team=f"T{i + 1}")
        for i in range(count)
    ]


class WalkForwardPredictionsTests(unittest.TestCase):
    def test_skips_matches_missing_required_fields(self) -> None:
        matches = [make_match(home_goals=None, away_goals=None, result=None), make_match()]
        predictions = walk_forward_predictions(matches, weight_scale=1.0)
        self.assertEqual(len(predictions), 1)

    def test_first_match_has_no_history_and_falls_back_to_base_model(self) -> None:
        matches = [make_match(home_rating=2200.0, away_rating=1900.0)]
        predictions = walk_forward_predictions(matches, weight_scale=1.0)

        expected = calculate_match_probabilities(2200.0, 1900.0)
        self.assertEqual(predictions[0]["probabilities"], expected)

    def test_zero_weight_scale_ignores_history_entirely(self) -> None:
        history = draw_heavy_league(5)
        target = make_match(date="01.02.20", home_rating=2050.0, away_rating=1950.0, home_goals=2, away_goals=0)
        matches = history + [target]

        predictions = walk_forward_predictions(matches, weight_scale=0.0)
        final = predictions[-1]

        expected = calculate_match_probabilities(2050.0, 1950.0)
        self.assertEqual(final["probabilities"], expected)

    def test_history_only_sees_strictly_earlier_matches(self) -> None:
        m1 = make_match(date="01.01.20", home_goals=1, away_goals=1)
        m2 = make_match(date="02.01.20", home_goals=1, away_goals=1)
        m3 = make_match(date="03.01.20", home_rating=2300.0, away_rating=1800.0, home_goals=3, away_goals=0)
        m4_future = make_match(date="04.01.20", home_rating=1500.0, away_rating=2400.0, home_goals=0, away_goals=4)

        without_future = walk_forward_predictions([m1, m2, m3], weight_scale=1.0)
        with_future = walk_forward_predictions([m1, m2, m3, m4_future], weight_scale=1.0)

        # m3's prediction must be identical whether or not a later match
        # (m4, dated after it) is included in the input at all.
        self.assertEqual(without_future[2]["probabilities"], with_future[2]["probabilities"])

    def test_input_order_does_not_matter(self) -> None:
        chronological = draw_heavy_league(6)
        scrambled = list(reversed(chronological))

        from_sorted = walk_forward_predictions(chronological, weight_scale=1.0)
        from_scrambled = walk_forward_predictions(scrambled, weight_scale=1.0)

        self.assertEqual(
            [(row["date"], row["probabilities"]) for row in from_sorted],
            [(row["date"], row["probabilities"]) for row in from_scrambled],
        )

    def test_market_brier_present_only_with_valid_odds(self) -> None:
        matches = [make_match(home_odds=0.0)]
        predictions = walk_forward_predictions(matches, weight_scale=1.0)
        self.assertNotIn("market_brier", predictions[0])

        matches = [make_match()]
        predictions = walk_forward_predictions(matches, weight_scale=1.0)
        self.assertIn("market_brier", predictions[0])


class EvaluateWeightScaleTests(unittest.TestCase):
    def test_no_completed_matches_returns_zero_summary(self) -> None:
        matches = [make_match(home_goals=None, away_goals=None, result=None)]
        result = evaluate_weight_scale(matches, weight_scale=1.0)
        self.assertEqual(result, {"weight_scale": 1.0, "matches_evaluated": 0})

    def test_aggregates_brier_and_pick_accuracy(self) -> None:
        matches = draw_heavy_league(3)
        result = evaluate_weight_scale(matches, weight_scale=1.0)

        self.assertEqual(result["matches_evaluated"], 3)
        self.assertGreaterEqual(result["avg_brier"], 0.0)
        self.assertGreaterEqual(result["pick_accuracy_percent"], 0.0)
        self.assertLessEqual(result["pick_accuracy_percent"], 100.0)
        self.assertIsNotNone(result["avg_market_brier"])


class SweepWeightScalesTests(unittest.TestCase):
    def test_skips_leagues_below_min_matches(self) -> None:
        matches = draw_heavy_league(5)
        result = sweep_weight_scales(matches, min_matches=10)

        self.assertEqual(result["matches_available"], 5)
        self.assertEqual(result["results"], [])
        self.assertIsNone(result["best"])

    def test_trusting_predictive_history_more_lowers_brier_score(self) -> None:
        # Every match is an evenly-rated draw: history is a near-perfect
        # predictor, so scaling calibration up should out-predict the
        # ratings-only model (scale 0.0).
        matches = draw_heavy_league(20)
        result = sweep_weight_scales(matches, weight_scales=(0.0, 1.0, 2.0), min_matches=10)

        by_scale = {row["weight_scale"]: row["avg_brier"] for row in result["results"]}
        self.assertLess(by_scale[2.0], by_scale[0.0])
        self.assertLess(by_scale[1.0], by_scale[0.0])
        self.assertGreater(result["best"]["weight_scale"], 0.0)
        self.assertEqual(result["current_default_scale"], 1.0)

    def test_best_is_the_lowest_avg_brier_result(self) -> None:
        matches = draw_heavy_league(20)
        result = sweep_weight_scales(matches, weight_scales=(0.0, 1.0, 2.0), min_matches=10)

        self.assertEqual(result["best"], min(result["results"], key=lambda r: r["avg_brier"]))


if __name__ == "__main__":
    unittest.main()
