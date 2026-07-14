import unittest
from contextlib import contextmanager
from unittest import mock

from soccer_ratings.db import list_countries_with_imported_leagues, refresh_known_history


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


class ListCountriesWithImportedLeaguesTests(unittest.TestCase):
    def test_returns_countries_from_query_rows(self) -> None:
        fake_db_cursor = _fake_db_cursor(
            [("/England/", "England"), ("/Spain/", "Spain")]
        )
        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = list_countries_with_imported_leagues()

        self.assertEqual(
            result,
            [
                {"country_path": "/England/", "country": "England"},
                {"country_path": "/Spain/", "country": "Spain"},
            ],
        )

    def test_returns_empty_list_when_nothing_imported(self) -> None:
        fake_db_cursor = _fake_db_cursor([])
        with mock.patch("soccer_ratings.db.db_cursor", fake_db_cursor):
            result = list_countries_with_imported_leagues()
        self.assertEqual(result, [])


class RefreshKnownHistoryTests(unittest.TestCase):
    @mock.patch("soccer_ratings.db.import_country_history")
    @mock.patch("soccer_ratings.db.list_countries_with_imported_leagues")
    def test_refreshes_only_already_imported_countries(
        self, mock_list_countries, mock_import_country
    ) -> None:
        mock_list_countries.return_value = [
            {"country_path": "/England/", "country": "England"},
            {"country_path": "/Spain/", "country": "Spain"},
        ]
        mock_import_country.side_effect = [
            {"leagues_processed": 2, "matches_imported": 20, "deduped_match_count": 18},
            {"leagues_processed": 1, "matches_imported": 5, "deduped_match_count": 4},
        ]

        result = refresh_known_history()

        self.assertEqual(mock_import_country.call_count, 2)
        mock_import_country.assert_any_call("/England/", None)
        mock_import_country.assert_any_call("/Spain/", None)
        self.assertEqual(result["countries_processed"], 2)
        self.assertEqual(result["leagues_processed"], 3)
        self.assertEqual(result["matches_imported"], 25)
        self.assertEqual(result["failure_count"], 0)

    @mock.patch("soccer_ratings.db.import_country_history")
    @mock.patch("soccer_ratings.db.list_countries_with_imported_leagues")
    def test_continues_past_a_country_failure(self, mock_list_countries, mock_import_country) -> None:
        mock_list_countries.return_value = [
            {"country_path": "/England/", "country": "England"},
            {"country_path": "/Spain/", "country": "Spain"},
        ]
        mock_import_country.side_effect = [
            RuntimeError("scrape failed"),
            {"leagues_processed": 1, "matches_imported": 5, "deduped_match_count": 4},
        ]

        result = refresh_known_history()

        self.assertEqual(result["countries_processed"], 1)
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["failures"][0]["country_url"], "/England/")

    @mock.patch("soccer_ratings.db.import_country_history")
    @mock.patch("soccer_ratings.db.list_countries_with_imported_leagues")
    def test_does_nothing_when_no_countries_imported_yet(
        self, mock_list_countries, mock_import_country
    ) -> None:
        mock_list_countries.return_value = []

        result = refresh_known_history()

        mock_import_country.assert_not_called()
        self.assertEqual(result["countries_processed"], 0)


if __name__ == "__main__":
    unittest.main()
