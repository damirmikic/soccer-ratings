import unittest
from unittest import mock
from contextlib import contextmanager

from soccer_ratings.db import get_weekly_rating_movers, get_model_accuracy_summary


class _FakeCursor:
    def __init__(self, fetchall_results):
        self._fetchall_results = fetchall_results
        self._call_count = 0

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        res = self._fetchall_results[self._call_count]
        self._call_count += 1
        return res


def _fake_db_cursor(fetchall_results):
    cursor = _FakeCursor(fetchall_results)

    @contextmanager
    def db_cursor(*args, **kwargs):
        yield (mock.Mock(), cursor)

    return db_cursor


class WeeklyRatingMoversTests(unittest.TestCase):
    def test_returns_climbers_and_sliders(self) -> None:
        climbers_rows = [
            ("Team A", "/team/a", "League X", "/league/x", "Country Y", 1500.0, 1400.0, 100.0),
        ]
        sliders_rows = [
            ("Team B", "/team/b", "League X", "/league/x", "Country Y", 1300.0, 1400.0, -100.0),
        ]

        fake_db_cursor = _fake_db_cursor([climbers_rows, sliders_rows])
        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = get_weekly_rating_movers(limit=5)

        self.assertEqual(len(result["climbers"]), 1)
        self.assertEqual(result["climbers"][0]["team"], "Team A")
        self.assertEqual(result["climbers"][0]["change"], 100.0)

        self.assertEqual(len(result["sliders"]), 1)
        self.assertEqual(result["sliders"][0]["team"], "Team B")
        self.assertEqual(result["sliders"][0]["change"], -100.0)


class ModelAccuracySummaryTests(unittest.TestCase):
    @mock.patch("soccer_ratings.odds.calculate_match_probabilities")
    def test_calculates_correct_stats(self, mock_calc) -> None:
        mock_calc.return_value = {"home": 0.6, "draw": 0.2, "away": 0.2}

        match_rows = [
            (1500.0, 1400.0, 3, 1, 0.0, -0.13),
        ]
        tuned_rows = [
            ("League X", "Country Y", "/league/x", 1.5, 80.0, -0.13),
        ]

        fake_db_cursor = _fake_db_cursor([match_rows, tuned_rows])
        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = get_model_accuracy_summary()

        self.assertEqual(result["accuracy"], 100.0)
        self.assertEqual(result["total_evaluated"], 1)
        self.assertEqual(len(result["tuned_leagues"]), 1)
        self.assertEqual(result["tuned_leagues"][0]["name"], "League X")
