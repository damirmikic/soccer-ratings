import random
import unittest

from soccer_ratings.odds import (
    DEFAULT_AWAY_GOAL_RATE,
    DEFAULT_AWAY_GOAL_SCALE,
    DEFAULT_HOME_GOAL_RATE,
    DEFAULT_HOME_GOAL_SCALE,
    DEFAULT_RHO,
    DEFAULT_TEMPERATURE,
    _base_expected_goals,
    _dixon_coles_tau,
    _poisson_probability,
    calculate_match_probabilities,
)
from soccer_ratings.backtest import match_outcome, run_league_backtest
from soccer_ratings.tuning import (
    DEFAULT_GOAL_RATE_BOUNDS,
    DEFAULT_MIN_MATCHES,
    _brier_score,
    _brier_for_model_params,
    _chronological_split,
    _fit_goal_curve,
    _fit_rho,
    _fit_side_goal_curve,
    _golden_section_minimize,
    fit_league_model,
)

_MAX_GOALS = 10


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
    }
    match.update(overrides)
    return match


def _draw_scoreline(rng, home_rating, away_rating, *, home_advantage=0.0, rho=DEFAULT_RHO, curve=None):
    """Sample a real scoreline from the exact generative process
    calculate_match_probabilities assumes, so the fitting tests below check
    real identifiability rather than an approximation of it.
    """
    curve = curve or {}
    lam_h, lam_a = _base_expected_goals(home_rating, away_rating, home_advantage, **curve)
    home_pmf = [_poisson_probability(g, lam_h) for g in range(_MAX_GOALS + 1)]
    away_pmf = [_poisson_probability(g, lam_a) for g in range(_MAX_GOALS + 1)]
    cells = []
    for home_goals, p_home in enumerate(home_pmf):
        for away_goals, p_away in enumerate(away_pmf):
            weight = p_home * p_away * _dixon_coles_tau(home_goals, away_goals, lam_h, lam_a, rho)
            cells.append((home_goals, away_goals, weight))
    total = sum(cell[2] for cell in cells)
    draw = rng.random() * total
    cumulative = 0.0
    for home_goals, away_goals, weight in cells:
        cumulative += weight
        if cumulative >= draw:
            return home_goals, away_goals
    return cells[-1][0], cells[-1][1]


def make_synthetic_league(seed, count, *, home_advantage=0.0, rho=DEFAULT_RHO, curve=None):
    rng = random.Random(seed)
    matches = []
    for index in range(count):
        home_rating = rng.uniform(1300.0, 1900.0)
        away_rating = rng.uniform(1300.0, 1900.0)
        home_goals, away_goals = _draw_scoreline(
            rng, home_rating, away_rating, home_advantage=home_advantage, rho=rho, curve=curve
        )
        matches.append(
            {
                "date": f"{(index % 28) + 1:02d}.{(index % 12) + 1:02d}.2{20 + index // 300}",
                "home_team": f"Team {index % 20}",
                "away_team": f"Team {(index + 7) % 20}",
                "home_rating": home_rating,
                "away_rating": away_rating,
                "home_goals": home_goals,
                "away_goals": away_goals,
            }
        )
    return matches


class GoldenSectionMinimizeTests(unittest.TestCase):
    def test_finds_the_minimum_of_a_simple_parabola(self) -> None:
        result = _golden_section_minimize(lambda x: (x - 3.0) ** 2, -10.0, 10.0)
        self.assertAlmostEqual(result, 3.0, places=2)

    def test_respects_bounds_when_the_minimum_is_outside_them(self) -> None:
        # Minimum of (x-3)^2 is at 3, well outside [-10, -5] — should settle
        # at the boundary closest to it, not wander outside the interval.
        result = _golden_section_minimize(lambda x: (x - 3.0) ** 2, -10.0, -5.0)
        self.assertGreaterEqual(result, -10.0)
        self.assertLessEqual(result, -5.0)
        self.assertAlmostEqual(result, -5.0, places=2)

    def test_degenerate_interval_returns_the_low_bound(self) -> None:
        self.assertEqual(_golden_section_minimize(lambda x: x, 5.0, 5.0), 5.0)


class ChronologicalSplitTests(unittest.TestCase):
    def test_splits_are_ordered_and_partition_the_input(self) -> None:
        matches = [make_match(date=f"{day:02d}.01.20") for day in range(1, 21)]
        train, calibration, test = _chronological_split(matches, train_fraction=0.5, calibration_fraction=0.3)

        self.assertEqual(len(train) + len(calibration) + len(test), 20)
        self.assertEqual(train[0]["date"], "01.01.20")
        self.assertEqual(test[-1]["date"], "20.01.20")
        # Every match in train predates every match in calibration, which
        # predates every match in test.
        if calibration and test:
            self.assertLessEqual(train[-1]["date"][:2], calibration[0]["date"][:2])
            self.assertLessEqual(calibration[-1]["date"][:2], test[0]["date"][:2])

    def test_tiny_input_does_not_crash(self) -> None:
        train, calibration, test = _chronological_split([make_match()])
        self.assertEqual(len(train) + len(calibration) + len(test), 1)

    def test_empty_input(self) -> None:
        self.assertEqual(_chronological_split([]), ([], [], []))


class FitSideGoalCurveTests(unittest.TestCase):
    def test_recovers_a_known_scale_and_rate_from_synthetic_poisson_goals(self) -> None:
        import math

        rng = random.Random(11)
        true_scale, true_rate = 1.6, 700.0
        gaps, goals = [], []
        for _ in range(3000):
            gap = rng.uniform(-600.0, 600.0)
            lam = true_scale * math.exp(gap / true_rate)
            k = 0
            # Manual Poisson sampling (Knuth's method) to avoid importing
            # numpy/scipy just for a test fixture.
            l = math.exp(-lam)
            p = 1.0
            while True:
                p *= rng.random()
                if p <= l:
                    break
                k += 1
            gaps.append(gap)
            goals.append(k)

        scale, rate, nll = _fit_side_goal_curve(
            gaps, goals, fallback_scale=1.0, fallback_rate=500.0, rate_bounds=(100.0, 3000.0)
        )
        self.assertAlmostEqual(scale, true_scale, delta=0.15)
        self.assertAlmostEqual(rate, true_rate, delta=250.0)
        self.assertLess(nll, float("inf"))

    def test_empty_input_returns_the_fallback(self) -> None:
        scale, rate, nll = _fit_side_goal_curve(
            [], [], fallback_scale=1.42, fallback_rate=781.0, rate_bounds=DEFAULT_GOAL_RATE_BOUNDS
        )
        self.assertEqual((scale, rate), (1.42, 781.0))
        self.assertEqual(nll, float("inf"))

    def test_all_zero_goals_returns_the_fallback_rather_than_dividing_by_zero(self) -> None:
        scale, rate, _ = _fit_side_goal_curve(
            [10.0, -10.0, 0.0],
            [0, 0, 0],
            fallback_scale=1.42,
            fallback_rate=781.0,
            rate_bounds=DEFAULT_GOAL_RATE_BOUNDS,
        )
        self.assertEqual((scale, rate), (1.42, 781.0))


class FitGoalCurveTests(unittest.TestCase):
    def test_null_case_stays_close_to_the_generating_defaults(self) -> None:
        default_curve = {
            "home_goal_scale": DEFAULT_HOME_GOAL_SCALE,
            "home_goal_rate": DEFAULT_HOME_GOAL_RATE,
            "away_goal_scale": DEFAULT_AWAY_GOAL_SCALE,
            "away_goal_rate": DEFAULT_AWAY_GOAL_RATE,
        }
        matches = make_synthetic_league(1, 1200, curve=default_curve)

        curve = _fit_goal_curve(matches, home_advantage=0.0)

        self.assertAlmostEqual(curve["home_goal_scale"], DEFAULT_HOME_GOAL_SCALE, delta=0.25)
        self.assertAlmostEqual(curve["away_goal_scale"], DEFAULT_AWAY_GOAL_SCALE, delta=0.25)

    def test_a_real_home_edge_shows_up_as_scale_asymmetry(self) -> None:
        # home_advantage folded into the *generating* curve (not fit as a
        # separate parameter — see fit_league_model's docstring for why)
        # should widen the gap between home_goal_scale and away_goal_scale.
        default_curve = {
            "home_goal_scale": DEFAULT_HOME_GOAL_SCALE,
            "home_goal_rate": DEFAULT_HOME_GOAL_RATE,
            "away_goal_scale": DEFAULT_AWAY_GOAL_SCALE,
            "away_goal_rate": DEFAULT_AWAY_GOAL_RATE,
        }
        no_edge = make_synthetic_league(2, 1400, home_advantage=0.0, curve=default_curve)
        big_edge = make_synthetic_league(2, 1400, home_advantage=150.0, curve=default_curve)

        no_edge_curve = _fit_goal_curve(no_edge, home_advantage=0.0)
        big_edge_curve = _fit_goal_curve(big_edge, home_advantage=0.0)

        no_edge_ratio = no_edge_curve["home_goal_scale"] / no_edge_curve["away_goal_scale"]
        big_edge_ratio = big_edge_curve["home_goal_scale"] / big_edge_curve["away_goal_scale"]
        self.assertGreater(big_edge_ratio, no_edge_ratio)


class FitRhoTests(unittest.TestCase):
    def test_improves_brier_over_an_obviously_wrong_rho(self) -> None:
        curve = {
            "home_goal_scale": DEFAULT_HOME_GOAL_SCALE,
            "home_goal_rate": DEFAULT_HOME_GOAL_RATE,
            "away_goal_scale": DEFAULT_AWAY_GOAL_SCALE,
            "away_goal_rate": DEFAULT_AWAY_GOAL_RATE,
        }
        matches = make_synthetic_league(3, 1200, rho=0.05, curve=curve)

        fitted_rho = _fit_rho(matches, home_advantage=0.0, curve=curve, bounds=(-0.35, 0.15))
        wrong_rho_brier = _brier_for_model_params(matches, home_advantage=0.0, rho=-0.30, curve=curve)
        fitted_rho_brier = _brier_for_model_params(matches, home_advantage=0.0, rho=fitted_rho, curve=curve)

        self.assertLess(fitted_rho_brier, wrong_rho_brier)


class FitLeagueModelTests(unittest.TestCase):
    def test_reports_unavailable_below_min_matches(self) -> None:
        result = fit_league_model([make_match()], min_matches=30)

        self.assertIsNone(result["fitted"])
        self.assertIsNone(result["validation"])
        self.assertEqual(result["min_matches_required"], 30)

    def test_ignores_matches_missing_required_fields(self) -> None:
        matches = [make_match(home_rating=None)] * 40
        result = fit_league_model(matches, min_matches=10)

        self.assertEqual(result["matches_available"], 0)
        self.assertIsNone(result["fitted"])

    def test_home_advantage_is_always_zero(self) -> None:
        # See fit_league_model's docstring: home_advantage is not
        # identifiable jointly with a freely-fit curve, so it is never
        # fit as an independent number here.
        matches = make_synthetic_league(4, 400)
        result = fit_league_model(matches, min_matches=DEFAULT_MIN_MATCHES)

        self.assertEqual(result["fitted"]["home_advantage"], 0.0)

    def test_fitted_model_beats_default_out_of_sample_when_the_truth_differs(self) -> None:
        curve = dict(home_goal_scale=1.55, home_goal_rate=650.0, away_goal_scale=0.95, away_goal_rate=900.0)
        matches = make_synthetic_league(5, 1400, rho=0.05, curve=curve)

        result = fit_league_model(matches)

        self.assertIsNotNone(result["fitted"])
        self.assertIsNotNone(result["validation"])
        self.assertGreater(result["validation"]["test_matches"], 0)
        self.assertGreater(result["validation"]["improvement"], 0.0)
        self.assertLess(result["validation"]["fitted_avg_brier"], result["validation"]["default_avg_brier"])

    def test_null_case_does_not_run_away_from_the_defaults(self) -> None:
        # When the data really was generated from the module defaults, the
        # fit should land close to them, not drift to an extreme.
        matches = make_synthetic_league(6, 1200)

        result = fit_league_model(matches)
        fitted = result["fitted"]

        self.assertAlmostEqual(fitted["home_goal_scale"], DEFAULT_HOME_GOAL_SCALE, delta=0.35)
        self.assertAlmostEqual(fitted["away_goal_scale"], DEFAULT_AWAY_GOAL_SCALE, delta=0.35)
        self.assertGreater(fitted["rho"], -0.35)
        self.assertLess(fitted["rho"], 0.15)

    def test_too_few_matches_for_a_calibration_split_leaves_temperature_at_default(self) -> None:
        # 45 matches -> a 70% train split (32) clears min_matches=30, but
        # the 15% calibration slice (7) doesn't clear _MIN_CALIBRATION_MATCHES
        # (10), so temperature fitting should be skipped rather than fit on
        # too little data to trust.
        matches = make_synthetic_league(7, 45)

        result = fit_league_model(matches, min_matches=30)

        self.assertIsNotNone(result["fitted"])
        self.assertEqual(result["fitted"]["temperature"], DEFAULT_TEMPERATURE)

    def test_fitted_parameters_are_directly_usable_by_run_league_backtest(self) -> None:
        curve = dict(home_goal_scale=1.5, home_goal_rate=700.0, away_goal_scale=1.0, away_goal_rate=800.0)
        matches = make_synthetic_league(8, 1200, rho=0.0, curve=curve)
        fit_result = fit_league_model(matches)
        self.assertIsNotNone(fit_result["fitted"])

        backtest_matches = [
            {
                **match,
                "home_odds": 2.0,
                "draw_odds": 3.3,
                "away_odds": 3.6,
                "competition": "TEST",
                "result": f"{match['home_goals']}-{match['away_goals']}",
            }
            for match in matches[:50]
        ]
        result = run_league_backtest(backtest_matches, tuning_params=fit_result["fitted"])

        self.assertEqual(result["matches_evaluated"], 50)
        self.assertIn("avg_recalibrated_brier", result)


if __name__ == "__main__":
    unittest.main()
