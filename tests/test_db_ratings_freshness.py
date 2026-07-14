import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest import mock

from soccer_ratings.db import load_league_home_away_ratings


class _FakeCursor:
    def __init__(self, fetchone_result, fetchall_results):
        self._fetchone_result = fetchone_result
        self._fetchall_results = iter(fetchall_results)

    def execute(self, query, params=None):
        pass

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return next(self._fetchall_results)


def _fake_db_cursor(fetchone_result, fetchall_results):
    cursor = _FakeCursor(fetchone_result, fetchall_results)

    @contextmanager
    def db_cursor(*args, **kwargs):
        yield (mock.Mock(), cursor)

    return db_cursor


class LoadLeagueHomeAwayRatingsFreshnessTests(unittest.TestCase):
    def test_returns_max_fetched_at_across_home_and_away(self) -> None:
        older = datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)
        newer = datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc)

        fake_db_cursor = _fake_db_cursor(
            fetchone_result=(1, "/England/Premier-League/"),
            fetchall_results=[
                [("Arsenal", "/arsenal/", 1, 1600.0, newer)],  # home
                [("Arsenal", "/arsenal/", 1, 1580.0, older)],  # away
                [],  # general
            ],
        )

        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = load_league_home_away_ratings("/England/Premier-League/")

        self.assertIsNotNone(result)
        self.assertEqual(result["fetched_at"], newer)

    def test_fetched_at_is_none_when_snapshot_rows_lack_a_timestamp(self) -> None:
        fake_db_cursor = _fake_db_cursor(
            fetchone_result=(1, "/England/Premier-League/"),
            fetchall_results=[
                [("Arsenal", "/arsenal/", 1, 1600.0, None)],
                [("Arsenal", "/arsenal/", 1, 1580.0, None)],
                [],
            ],
        )

        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = load_league_home_away_ratings("/England/Premier-League/")

        self.assertIsNotNone(result)
        self.assertIsNone(result["fetched_at"])

    def test_returns_none_when_league_not_found(self) -> None:
        fake_db_cursor = _fake_db_cursor(fetchone_result=None, fetchall_results=[])

        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = load_league_home_away_ratings("/Nowhere/")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
