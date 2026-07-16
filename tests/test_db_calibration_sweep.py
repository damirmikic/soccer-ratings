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


def _fake_sweep(weight_scale_two_wins: bool):
    """A stand-in sweep_league_parameters result: either the tuned scale beats
    the default, or there wasn't enough data to evaluate at all."""
    if weight_scale_two_wins:
        return {
            "matches_available": 50,
            "min_matches_required": 30,
            "best": {
                "weight_scale": 2.0,
                "elo_divisor": 420.0,
                "draw_max": 0.32,
                "draw_divisor": 480.0,
                "draw_min": 0.20,
                "avg_brier": 0.50,
                "matches_evaluated": 50,
            },
            "default": {
                "weight_scale": 1.0,
                "elo_divisor": 400.0,
                "draw_max": 0.30,
                "draw_divisor": 500.0,
                "draw_min": 0.18,
                "avg_brier": 0.60,
                "matches_evaluated": 50,
            },
        }
    return {
        "matches_available": 5,
        "min_matches_required": 30,
        "best": None,
        "default": None,
    }


class RunCalibrationSweepTests(unittest.TestCase):
    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.sweep_league_parameters")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_splits_evaluated_and_skipped_leagues(
        self, mock_list_leagues, mock_sweep, mock_load_matches
    ) -> None:
        mock_list_leagues.return_value = [
            {"league_path": "/England/Premier-League/", "league": "Premier League", "country": "England"},
            {"league_path": "/Spain/Regional/", "league": "Tercera", "country": "Spain"},
        ]
        mock_load_matches.return_value = []
        mock_sweep.side_effect = [_fake_sweep(True), _fake_sweep(False)]

        result = run_calibration_sweep()

        self.assertEqual(result["leagues_considered"], 2)
        self.assertEqual(result["leagues_evaluated"], 1)
        self.assertEqual(result["leagues_skipped"], 1)
        self.assertEqual(len(result["leagues"]), 1)
        self.assertEqual(result["leagues"][0]["league"], "Premier League")
        self.assertEqual(result["leagues"][0]["best"]["weight_scale"], 2.0)
        self.assertEqual(result["leagues"][0]["default_avg_brier"], 0.60)
        self.assertEqual(len(result["skipped_leagues"]), 1)
        self.assertEqual(result["skipped_leagues"][0]["league"], "Tercera")
        self.assertIsNotNone(result["summary"])

    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.sweep_league_parameters")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_reports_progress_after_each_league(
        self, mock_list_leagues, mock_sweep, mock_load_matches
    ) -> None:
        mock_list_leagues.return_value = [
            {"league_path": "/England/Premier-League/", "league": "Premier League", "country": "England"},
            {"league_path": "/Spain/La-Liga/", "league": "La Liga", "country": "Spain"},
        ]
        mock_load_matches.return_value = []
        mock_sweep.side_effect = [_fake_sweep(True), _fake_sweep(True)]

        progress_calls = []
        run_calibration_sweep(
            on_progress=lambda current, total, message: progress_calls.append((current, total, message))
        )

        self.assertEqual(progress_calls, [(1, 2, "Premier League"), (2, 2, "La Liga")])

    @mock.patch("soccer_ratings.db.load_league_history_matches")
    @mock.patch("soccer_ratings.db.sweep_league_parameters")
    @mock.patch("soccer_ratings.db.list_all_imported_leagues")
    def test_does_nothing_when_no_leagues_imported_yet(
        self, mock_list_leagues, mock_sweep, mock_load_matches
    ) -> None:
        mock_list_leagues.return_value = []

        result = run_calibration_sweep()

        mock_sweep.assert_not_called()
        self.assertEqual(result["leagues_considered"], 0)
        self.assertEqual(result["leagues_evaluated"], 0)
        self.assertIsNone(result["summary"])


if __name__ == "__main__":
    unittest.main()
