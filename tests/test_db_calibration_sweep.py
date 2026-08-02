import unittest
from contextlib import contextmanager
from unittest import mock

from soccer_ratings.db import list_all_imported_leagues, run_calibration_sweep


class _FakeCursor:
    def __init__(self, fetchall_result):
        self._fetchall_result = fetchall_result

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return self._fetchall_result


def _fake_db_cursor(fetchall_result):
    cursor = _FakeCursor(fetchall_result)

    @contextmanager
    def db_cursor(*args, **kwargs):
        yield (mock.Mock(), cursor)

    return db_cursor


class ListAllImportedLeaguesTests(unittest.TestCase):
    def test_returns_leagues_from_query_rows(self) -> None:
        fake_db_cursor = _fake_db_cursor(
            [
                ("/England/Premier-League/", "Premier League", "England"),
                ("/Spain/La-Liga/", "La Liga", "Spain"),
            ]
        )
        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = list_all_imported_leagues()

        self.assertEqual(
            result,
            [
                {"league_path": "/England/Premier-League/", "league": "Premier League", "country": "England"},
                {"league_path": "/Spain/La-Liga/", "league": "La Liga", "country": "Spain"},
            ],
        )

    def test_returns_empty_list_when_nothing_imported(self) -> None:
        fake_db_cursor = _fake_db_cursor([])
        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = list_all_imported_leagues()
        self.assertEqual(result, [])


def _fake_fit(fit_beats_default: bool):
    """A stand-in fit_league_model result: either the fit clearly beats the
    module defaults out of sample, or there wasn't enough data to fit at
    all. home_advantage is always 0.0 — see fit_league_model's docstring
    for why it's never fit as an independent parameter.
    """
    if fit_beats_default:
        return {
            "matches_available": 500,
            "min_matches_required": 30,
            "train_matches": 350,
            "calibration_matches": 75,
            "test_matches": 75,
            "train_avg_brier": 0.52,
            "fitted": {
                "home_advantage": 0.0,
                "rho": -0.08,
                "temperature": 0.92,
                "home_goal_scale": 1.5,
                "home_goal_rate": 700.0,
                "away_goal_scale": 1.0,
                "away_goal_rate": 800.0,
            },
            "validation": {
                "test_matches": 75,
                "fitted_avg_brier": 0.50,
                "default_avg_brier": 0.56,
                "improvement": 0.06,
            },
        }
    return {
        "matches_available": 5,
        "min_matches_required": 30,
        "train_matches": 0,
        "calibration_matches": 0,
        "test_matches": 0,
        "train_avg_brier": None,
        "fitted": None,
        "validation": None,
    }


class RunCalibrationSweepTests(unittest.TestCase):
    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.fit_league_model")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_splits_evaluated_and_skipped_leagues(
        self, mock_list_leagues, mock_fit, mock_load_matches
    ) -> None:
        mock_list_leagues.return_value = [
            {"league_path": "/England/Premier-League/", "league": "Premier League", "country": "England"},
            {"league_path": "/Spain/Regional/", "league": "Tercera", "country": "Spain"},
        ]
        mock_load_matches.return_value = []
        mock_fit.side_effect = [_fake_fit(True), _fake_fit(False)]

        result = run_calibration_sweep()

        self.assertEqual(result["leagues_considered"], 2)
        self.assertEqual(result["leagues_evaluated"], 1)
        self.assertEqual(result["leagues_skipped"], 1)
        self.assertEqual(len(result["leagues"]), 1)
        self.assertEqual(result["leagues"][0]["league"], "Premier League")
        self.assertEqual(result["leagues"][0]["fitted"]["rho"], -0.08)
        self.assertEqual(result["leagues"][0]["validation"]["improvement"], 0.06)
        self.assertEqual(len(result["skipped_leagues"]), 1)
        self.assertEqual(result["skipped_leagues"][0]["league"], "Tercera")
        self.assertIsNotNone(result["summary"])
        self.assertEqual(result["summary"]["leagues_evaluated"], 1)
        self.assertEqual(result["summary"]["median_rho"], -0.08)
        self.assertEqual(result["summary"]["avg_out_of_sample_brier_improvement_vs_default"], 0.06)

    @mock.patch("soccer_ratings.db.update_league_tuning_parameters")
    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.fit_league_model")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_persists_only_the_fitted_leagues(
        self, mock_list_leagues, mock_fit, mock_load_matches, mock_update
    ) -> None:
        mock_list_leagues.return_value = [
            {"league_path": "/England/Premier-League/", "league": "Premier League", "country": "England"},
            {"league_path": "/Spain/Regional/", "league": "Tercera", "country": "Spain"},
        ]
        mock_load_matches.return_value = []
        fake = _fake_fit(True)
        mock_fit.side_effect = [fake, _fake_fit(False)]

        run_calibration_sweep()

        mock_update.assert_called_once_with("/England/Premier-League/", fake["fitted"], None)

    @mock.patch("soccer_ratings.db.update_league_tuning_parameters")
    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.fit_league_model")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_persist_false_does_not_write_anything(
        self, mock_list_leagues, mock_fit, mock_load_matches, mock_update
    ) -> None:
        mock_list_leagues.return_value = [
            {"league_path": "/England/Premier-League/", "league": "Premier League", "country": "England"},
        ]
        mock_load_matches.return_value = []
        mock_fit.return_value = _fake_fit(True)

        run_calibration_sweep(persist=False)

        mock_update.assert_not_called()

    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.fit_league_model")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_reports_progress_after_each_league(
        self, mock_list_leagues, mock_fit, mock_load_matches
    ) -> None:
        mock_list_leagues.return_value = [
            {"league_path": "/England/Premier-League/", "league": "Premier League", "country": "England"},
            {"league_path": "/Spain/La-Liga/", "league": "La Liga", "country": "Spain"},
        ]
        mock_load_matches.return_value = []
        mock_fit.side_effect = [_fake_fit(True), _fake_fit(True)]

        progress_calls = []
        run_calibration_sweep(
            on_progress=lambda current, total, message: progress_calls.append((current, total, message))
        )

        self.assertEqual(progress_calls, [(1, 2, "Premier League"), (2, 2, "La Liga")])

    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.fit_league_model")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_does_nothing_when_no_leagues_imported_yet(
        self, mock_list_leagues, mock_fit, mock_load_matches
    ) -> None:
        mock_list_leagues.return_value = []

        result = run_calibration_sweep()

        mock_fit.assert_not_called()
        self.assertEqual(result["leagues_considered"], 0)
        self.assertEqual(result["leagues_evaluated"], 0)
        self.assertIsNone(result["summary"])


if __name__ == "__main__":
    unittest.main()
