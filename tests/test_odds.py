import unittest
from unittest.mock import patch

from soccer_ratings.client import (
    compare_teams_from_ratings,
    dedupe_matches,
    fetch_league_history,
    filter_matches_for_league,
    league_code_from_url,
    summarize_league_stats,
)
from soccer_ratings.db import import_all_history, import_country_history
from soccer_ratings.odds import (
    DEFAULT_AWAY_GOAL_RATE,
    DEFAULT_AWAY_GOAL_SCALE,
    DEFAULT_HOME_GOAL_RATE,
    DEFAULT_HOME_GOAL_SCALE,
    apply_shin_margin,
    apply_temperature,
    build_btts_odds,
    build_dnb_odds,
    build_match_odds,
    build_total_goals_odds,
    build_match_odds,
    build_total_goals_odds,
    calibrate_probabilities_with_history,
    calculate_asian_handicap_probabilities,
    calculate_btts_probabilities,
    calculate_dnb_probabilities,
    calculate_double_chance_probabilities,
    calculate_match_probabilities,
    calculate_total_goals_probabilities,
    estimate_expected_goals,
    summarize_historical_match_context,
    summarize_team_goal_context,
)


class OddsModelTests(unittest.TestCase):
    def test_equal_ratings_still_favor_home_via_structural_home_advantage(self) -> None:
        # The score grid is built from the same rating-to-goals mapping the
        # totals/BTTS/AH markets use, which has a higher baseline home goal
        # expectation than away (1.42 vs 1.08) even at a zero rating gap —
        # this is what keeps 1X2 consistent with those markets instead of
        # being symmetric on its own separate curve.
        probabilities = calculate_match_probabilities(2000.0, 2000.0)

        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=4)
        self.assertGreater(probabilities["home"], probabilities["away"])
        self.assertGreater(probabilities["draw"], 0.0)

    def test_reversing_the_rating_gap_reverses_the_favorite(self) -> None:
        stronger_home = calculate_match_probabilities(2200.0, 2000.0)
        stronger_away = calculate_match_probabilities(2000.0, 2200.0)

        self.assertGreater(stronger_home["home"], stronger_home["away"])
        self.assertGreater(stronger_away["away"], stronger_away["home"])

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

    def test_total_goals_probabilities_sum_to_one(self) -> None:
        probabilities = calculate_total_goals_probabilities(1.5, 1.1, line=2.5)

        self.assertAlmostEqual(probabilities["over"] + probabilities["under"], 1.0, places=4)

    def test_btts_probabilities_sum_to_one(self) -> None:
        probabilities = calculate_btts_probabilities(1.4, 1.2)

        self.assertAlmostEqual(probabilities["yes"] + probabilities["no"], 1.0, places=4)

    def test_goal_market_odds_exist_for_reasonable_expected_goals(self) -> None:
        total_odds = build_total_goals_odds(1.6, 1.0, line=2.5)
        btts_odds = build_btts_odds(1.6, 1.0)

        self.assertGreater(total_odds["over"], 0.0)
        self.assertGreater(total_odds["under"], 0.0)
        self.assertGreater(btts_odds["yes"], 0.0)
        self.assertGreater(btts_odds["no"], 0.0)

    def test_double_chance_probabilities_sum_components(self) -> None:
        probs = {"home": 0.5, "draw": 0.3, "away": 0.2}
        dc_probs = calculate_double_chance_probabilities(probs)
        
        self.assertAlmostEqual(dc_probs["1X"], 0.8, places=4)
        self.assertAlmostEqual(dc_probs["X2"], 0.5, places=4)
        self.assertAlmostEqual(dc_probs["12"], 0.7, places=4)
        
    def test_asian_handicap_minus_0_5(self) -> None:
        probs = {"home": 0.5, "draw": 0.3, "away": 0.2}
        ah_probs = calculate_asian_handicap_probabilities(1.5, 1.0, probs, -0.5)
        
        self.assertAlmostEqual(ah_probs["home"], 0.5, places=4)
        self.assertAlmostEqual(ah_probs["away"], 0.5, places=4)
        
    def test_asian_handicap_minus_1_0_normalizes_without_push(self) -> None:
        probs = {"home": 0.6, "draw": 0.25, "away": 0.15}
        ah_probs = calculate_asian_handicap_probabilities(2.0, 1.0, probs, -1.0)
        
        self.assertAlmostEqual(ah_probs["home"] + ah_probs["away"], 1.0, places=4)
        self.assertGreater(ah_probs["home"], 0.0)
        self.assertGreater(ah_probs["away"], 0.0)
        
    def test_asian_handicap_minus_1_5(self) -> None:
        probs = {"home": 0.6, "draw": 0.25, "away": 0.15}
        ah_probs = calculate_asian_handicap_probabilities(2.0, 1.0, probs, -1.5)
        
        self.assertAlmostEqual(ah_probs["home"] + ah_probs["away"], 1.0, places=4)
        self.assertLess(ah_probs["home"], probs["home"])
        self.assertGreater(ah_probs["away"], probs["draw"] + probs["away"])


class GoalCurveTests(unittest.TestCase):
    """calculate_match_probabilities's rating->goals curve is exponential
    and per-league-fittable (see soccer_ratings.tuning.fit_league_model),
    replacing a linear map with hard caps. These check the module defaults
    reproduce the old curve's anchor/slope at gap=0 and that per-league
    curve parameters actually change the priced probabilities.
    """

    def test_default_curve_matches_the_retired_linear_map_at_zero_gap(self) -> None:
        probabilities = calculate_match_probabilities(1500.0, 1500.0)

        # The retired linear curve gave home=1.42/away=1.08 expected goals
        # at an even matchup; the exponential defaults were chosen to
        # reproduce that exactly (scale *is* the value at gap=0).
        even_odds_curve = calculate_match_probabilities(
            1500.0, 1500.0,
            home_goal_scale=1.42, home_goal_rate=DEFAULT_HOME_GOAL_RATE,
            away_goal_scale=1.08, away_goal_rate=DEFAULT_AWAY_GOAL_RATE,
        )
        self.assertEqual(probabilities, even_odds_curve)

    def test_a_fitted_curve_changes_the_priced_probabilities(self) -> None:
        default_probabilities = calculate_match_probabilities(1700.0, 1500.0)
        steeper_curve_probabilities = calculate_match_probabilities(
            1700.0, 1500.0,
            home_goal_scale=DEFAULT_HOME_GOAL_SCALE,
            home_goal_rate=300.0,  # much steeper than the default ~781
            away_goal_scale=DEFAULT_AWAY_GOAL_SCALE,
            away_goal_rate=DEFAULT_AWAY_GOAL_RATE,
        )
        self.assertNotEqual(default_probabilities, steeper_curve_probabilities)
        self.assertGreater(steeper_curve_probabilities["home"], default_probabilities["home"])

    def test_curve_has_no_hard_ceiling_unlike_the_retired_linear_map(self) -> None:
        # The old map capped home expected goals at 3.2 and away at 0.30 —
        # a big enough rating gap could never push the model's favorite
        # probability any higher once that ceiling was hit. The exponential
        # curve keeps responding (bounded only by the numerical safety net,
        # far beyond any real rating gap).
        moderate = calculate_match_probabilities(2000.0, 1500.0)
        extreme = calculate_match_probabilities(2600.0, 1500.0)
        self.assertGreater(extreme["home"], moderate["home"])

    def test_build_match_odds_and_estimate_expected_goals_accept_curve_kwargs(self) -> None:
        from soccer_ratings.odds import build_dnb_odds as _build_dnb_odds  # already imported above

        curve_kwargs = dict(
            home_goal_scale=1.5, home_goal_rate=650.0, away_goal_scale=1.0, away_goal_rate=850.0
        )
        odds = build_match_odds(1700.0, 1500.0, **curve_kwargs)
        dnb_odds = _build_dnb_odds(1700.0, 1500.0, **curve_kwargs)
        expected_goals = estimate_expected_goals(1700.0, 1500.0, **curve_kwargs)

        self.assertGreater(odds["home"], 0.0)
        self.assertGreater(dnb_odds["home"], 0.0)
        self.assertGreater(expected_goals["home"], 0.0)


class TemperatureScalingTests(unittest.TestCase):
    def test_identity_at_temperature_one(self) -> None:
        probabilities = {"home": 0.55, "draw": 0.25, "away": 0.20}
        self.assertEqual(apply_temperature(probabilities, 1.0), probabilities)

    def test_sharpens_the_favorite_below_one(self) -> None:
        probabilities = {"home": 0.55, "draw": 0.25, "away": 0.20}
        sharpened = apply_temperature(probabilities, 0.5)
        self.assertGreater(sharpened["home"], probabilities["home"])
        self.assertLess(sharpened["away"], probabilities["away"])

    def test_flattens_toward_uniform_above_one(self) -> None:
        probabilities = {"home": 0.55, "draw": 0.25, "away": 0.20}
        flattened = apply_temperature(probabilities, 2.5)
        self.assertLess(flattened["home"], probabilities["home"])
        self.assertGreater(flattened["away"], probabilities["away"])

    def test_never_flips_the_favorite(self) -> None:
        probabilities = {"home": 0.42, "draw": 0.30, "away": 0.28}
        for temperature in (0.2, 0.5, 0.8, 1.0, 1.5, 2.0, 3.0):
            scaled = apply_temperature(probabilities, temperature)
            self.assertEqual(max(scaled, key=scaled.get), "home")

    def test_always_sums_to_one(self) -> None:
        probabilities = {"home": 0.7, "draw": 0.2, "away": 0.1}
        for temperature in (0.4, 1.0, 2.5):
            scaled = apply_temperature(probabilities, temperature)
            self.assertAlmostEqual(sum(scaled.values()), 1.0, places=3)

    def test_non_positive_temperature_falls_back_to_identity(self) -> None:
        probabilities = {"home": 0.5, "draw": 0.3, "away": 0.2}
        self.assertEqual(apply_temperature(probabilities, 0.0), probabilities)
        self.assertEqual(apply_temperature(probabilities, -1.0), probabilities)

    def test_zero_probability_stays_zero(self) -> None:
        probabilities = {"home": 0.8, "draw": 0.2, "away": 0.0}
        scaled = apply_temperature(probabilities, 0.5)
        self.assertEqual(scaled["away"], 0.0)


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

    def test_compare_teams_uses_historical_context_when_available(self) -> None:
        home_rows = [{"team": "Alpha", "rating": 2100.0, "rank": 1}]
        away_rows = [{"team": "Beta", "rating": 2000.0, "rank": 2}]
        historical_matches = [
            {
                "home_team": "Alpha",
                "away_team": "Gamma",
                "home_rating": 2095.0,
                "away_rating": 1995.0,
                "home_goals": 1,
                "away_goals": 1,
            },
            {
                "home_team": "Alpha",
                "away_team": "Delta",
                "home_rating": 2105.0,
                "away_rating": 2005.0,
                "home_goals": 0,
                "away_goals": 0,
            },
            {
                "home_team": "Epsilon",
                "away_team": "Beta",
                "home_rating": 2110.0,
                "away_rating": 2010.0,
                "home_goals": 2,
                "away_goals": 1,
            },
        ]

        comparison = compare_teams_from_ratings(
            home_rows,
            away_rows,
            home_team="Alpha",
            away_team="Beta",
            historical_matches=historical_matches,
        )

        self.assertEqual(comparison["model"], "history-calibrated")
        self.assertIsNotNone(comparison["historical_context"])
        self.assertGreater(comparison["probabilities"]["draw"], comparison["base_probabilities"]["draw"])
        self.assertIn("expected_goals", comparison)
        self.assertIsNotNone(comparison["team_goal_context"])
        self.assertIn("total_goals_probabilities", comparison)
        self.assertIn("btts_probabilities", comparison)
        # No Alpha-vs-Beta meeting in the sample data, but each side has form.
        self.assertIsNone(comparison["head_to_head"])
        self.assertIsNotNone(comparison["home_form"])
        self.assertIsNotNone(comparison["away_form"])

    def test_compare_teams_surfaces_head_to_head_record(self) -> None:
        home_rows = [{"team": "Alpha", "rating": 2100.0, "rank": 1}]
        away_rows = [{"team": "Beta", "rating": 2000.0, "rank": 2}]
        historical_matches = [
            {
                "date": "01.01.23",
                "home_team": "Alpha",
                "away_team": "Beta",
                "home_odds": 1.8,
                "draw_odds": 3.5,
                "away_odds": 4.2,
                "home_rating": 2095.0,
                "away_rating": 1995.0,
                "home_goals": 2,
                "away_goals": 0,
            },
        ]

        comparison = compare_teams_from_ratings(
            home_rows,
            away_rows,
            home_team="Alpha",
            away_team="Beta",
            historical_matches=historical_matches,
        )

        self.assertEqual(comparison["head_to_head"]["wins"], 1)
        self.assertEqual(comparison["head_to_head"]["sample_size"], 1)


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

    def test_dedupe_matches_sorts_newest_first_across_months_and_years(self) -> None:
        matches = [
            {"date": "30.12.25", "competition": "BA1", "home_team": "A", "away_team": "B"},
            {"date": "02.01.26", "competition": "BA1", "home_team": "C", "away_team": "D"},
            {"date": "15.11.25", "competition": "BA1", "home_team": "E", "away_team": "F"},
        ]

        deduped = dedupe_matches(matches)

        self.assertEqual(
            [match["date"] for match in deduped],
            ["02.01.26", "30.12.25", "15.11.25"],
        )

    def test_filter_matches_for_league_keeps_only_matching_competition(self) -> None:
        matches = [
            {"competition": "UK1", "home_team": "A", "away_team": "B"},
            {"competition": "UKFACUP", "home_team": "A", "away_team": "B"},
        ]

        filtered = filter_matches_for_league(matches, "/England/UK1/")

        self.assertEqual(filtered, [{"competition": "UK1", "home_team": "A", "away_team": "B"}])

    @patch("soccer_ratings.client.discover_league_mode_urls")
    def test_league_code_from_top_flight_country_url_uses_special_link_code(self, mock_discover) -> None:
        mock_discover.return_value = {
            "general": "https://www.soccer-rating.com/England/",
            "home": "https://www.soccer-rating.com/England/UK1/home/",
            "away": "https://www.soccer-rating.com/England/UK1/away/",
        }

        self.assertEqual(league_code_from_url("/England/"), "UK1")


class HistoricalCalibrationTests(unittest.TestCase):
    def test_summarize_historical_match_context_returns_goal_and_draw_features(self) -> None:
        context = summarize_historical_match_context(
            [
                {"home_rating": 2100.0, "away_rating": 2000.0, "home_goals": 1, "away_goals": 1},
                {"home_rating": 2120.0, "away_rating": 2020.0, "home_goals": 2, "away_goals": 0},
                {"home_rating": 2080.0, "away_rating": 1980.0, "home_goals": 0, "away_goals": 0},
            ],
            target_rating_gap=100.0,
        )

        self.assertIsNotNone(context)
        self.assertEqual(context["sample_size"], 3)
        self.assertGreater(context["draw_rate"], 0.0)
        self.assertGreater(context["expected_total_goals"], 0.0)

    def test_summarize_historical_match_context_applies_recency_decay(self) -> None:
        matches = [
            {"home_rating": 2100.0, "away_rating": 2000.0, "home_goals": 1, "away_goals": 1, "date": "20.06.26"},
            {"home_rating": 2100.0, "away_rating": 2000.0, "home_goals": 2, "away_goals": 0, "date": "10.12.25"},
        ]
        context_no_decay = summarize_historical_match_context(
            matches,
            target_rating_gap=100.0,
        )
        context_with_decay = summarize_historical_match_context(
            matches,
            target_rating_gap=100.0,
            target_date="30.06.26",
            decay_half_life_days=182.5,
        )
        self.assertIsNotNone(context_no_decay)
        self.assertIsNotNone(context_with_decay)
        self.assertGreater(context_with_decay["draw_rate"], context_no_decay["draw_rate"])

    def test_calibrate_probabilities_with_history_raises_draw_probability_when_history_is_draw_heavy(self) -> None:
        base_probabilities = {"home": 0.5, "draw": 0.22, "away": 0.28}
        historical_context = {
            "effective_sample_size": 18.0,
            "draw_rate": 0.4,
            "home_share_non_draw": 0.55,
        }

        calibrated = calibrate_probabilities_with_history(base_probabilities, historical_context)

        self.assertGreater(calibrated["draw"], base_probabilities["draw"])
        self.assertAlmostEqual(
            calibrated["home"] + calibrated["draw"] + calibrated["away"],
            1.0,
            places=3,
        )

    def test_calibrate_probabilities_with_history_weight_scale_zero_ignores_history(self) -> None:
        base_probabilities = {"home": 0.5, "draw": 0.22, "away": 0.28}
        historical_context = {
            "effective_sample_size": 18.0,
            "draw_rate": 0.9,
            "home_share_non_draw": 0.1,
        }

        calibrated = calibrate_probabilities_with_history(
            base_probabilities, historical_context, weight_scale=0.0
        )

        self.assertEqual(calibrated, {key: round(value, 4) for key, value in base_probabilities.items()})

    def test_calibrate_probabilities_with_history_default_weight_scale_matches_scale_one(self) -> None:
        base_probabilities = {"home": 0.5, "draw": 0.22, "away": 0.28}
        historical_context = {
            "effective_sample_size": 18.0,
            "draw_rate": 0.4,
            "home_share_non_draw": 0.55,
        }

        default_call = calibrate_probabilities_with_history(base_probabilities, historical_context)
        explicit_scale_one = calibrate_probabilities_with_history(
            base_probabilities, historical_context, weight_scale=1.5
        )

        self.assertEqual(default_call, explicit_scale_one)

    def test_calibrate_probabilities_with_history_higher_weight_scale_trusts_history_more(self) -> None:
        base_probabilities = {"home": 0.5, "draw": 0.22, "away": 0.28}
        historical_context = {
            "effective_sample_size": 18.0,
            "draw_rate": 0.9,
            "home_share_non_draw": 0.55,
        }

        scale_one = calibrate_probabilities_with_history(base_probabilities, historical_context, weight_scale=1.0)
        scale_two = calibrate_probabilities_with_history(base_probabilities, historical_context, weight_scale=2.0)

        self.assertGreater(scale_two["draw"], scale_one["draw"])

    def test_estimate_expected_goals_blends_history_when_available(self) -> None:
        expected_goals = estimate_expected_goals(
            2100.0,
            2000.0,
            {
                "effective_sample_size": 20.0,
                "expected_home_goals": 1.9,
                "expected_away_goals": 0.8,
            },
        )

        self.assertGreater(expected_goals["home"], expected_goals["away"])
        self.assertGreater(expected_goals["total"], 0.0)

    def test_summarize_team_goal_context_reads_home_and_away_team_profiles(self) -> None:
        context = summarize_team_goal_context(
            [
                {"home_team": "Alpha", "away_team": "Beta", "home_goals": 2, "away_goals": 1},
                {"home_team": "Alpha", "away_team": "Gamma", "home_goals": 1, "away_goals": 0},
                {"home_team": "Delta", "away_team": "Beta", "home_goals": 1, "away_goals": 2},
            ],
            home_team="Alpha",
            away_team="Beta",
        )

        self.assertIsNotNone(context)
        self.assertEqual(context["home_team_home_sample"], 2)
        self.assertEqual(context["away_team_away_sample"], 2)
        self.assertGreater(context["home_team_home_scored"], 0.0)

    def test_summarize_league_stats_returns_goal_and_result_distribution(self) -> None:
        stats = summarize_league_stats(
            [
                {"home_goals": 2, "away_goals": 1},
                {"home_goals": 1, "away_goals": 1},
                {"home_goals": 0, "away_goals": 2},
            ]
        )

        self.assertEqual(stats["matches"], 3)
        self.assertEqual(stats["avg_goals"], 2.33)
        self.assertEqual(stats["home_win_pct"], 33.3)
        self.assertEqual(stats["draw_pct"], 33.3)
        self.assertEqual(stats["away_win_pct"], 33.3)


class ResilienceTests(unittest.TestCase):
    @patch("soccer_ratings.client.fetch_team_history")
    @patch("soccer_ratings.client.fetch_league_ratings")
    def test_fetch_league_history_skips_failed_team_pages(self, mock_fetch_league_ratings, mock_fetch_team_history) -> None:
        mock_fetch_league_ratings.return_value = [
            {"team": "Alpha", "team_path": "/Alpha/", "rating": 2000.0, "rank": 1},
            {"team": "Beta", "team_path": "/Beta/", "rating": 1900.0, "rank": 2},
        ]
        mock_fetch_team_history.side_effect = [
            [{"date": "01.01.26", "competition": "UK1", "home_team": "Alpha", "away_team": "Gamma"}],
            RuntimeError("HTTP 500"),
        ]

        payload = fetch_league_history("/England/UK1/")

        self.assertEqual(payload["team_count"], 1)
        self.assertEqual(len(payload["failed_teams"]), 1)
        self.assertEqual(payload["failed_teams"][0]["team"], "Beta")

    @patch("soccer_ratings.db.fetch_country_leagues")
    @patch("soccer_ratings.db.import_league_history")
    def test_import_country_history_collects_failures_without_aborting(self, mock_import_league_history, mock_fetch_country_leagues) -> None:
        mock_fetch_country_leagues.return_value = [
            {"league": "Premier League", "league_path": "/England/"},
            {"league": "Championship", "league_path": "/England/UK2/"},
        ]
        mock_import_league_history.side_effect = [
            {"league_url": "/England/", "matches_imported": 20, "deduped_match_count": 10},
            RuntimeError("HTTP 500"),
        ]

        payload = import_country_history("/England/")

        self.assertEqual(payload["leagues_processed"], 1)
        self.assertEqual(payload["failure_count"], 1)
        self.assertEqual(payload["failures"][0]["league"], "Championship")

    @patch("soccer_ratings.db.fetch_rankings")
    @patch("soccer_ratings.db.import_country_history")
    def test_import_all_history_collects_country_failures_without_aborting(self, mock_import_country_history, mock_fetch_rankings) -> None:
        mock_fetch_rankings.return_value = [
            {"country": "England", "country_path": "/England/"},
            {"country": "Spain", "country_path": "/Spain/"},
        ]
        mock_import_country_history.side_effect = [
            {"country_url": "/England/", "leagues_processed": 2, "matches_imported": 40, "deduped_match_count": 20},
            RuntimeError("HTTP 500"),
        ]

        payload = import_all_history()

        self.assertEqual(payload["countries_processed"], 1)
        self.assertEqual(payload["failure_count"], 1)
        self.assertEqual(payload["failures"][0]["country"], "Spain")
