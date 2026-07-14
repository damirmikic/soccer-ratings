import unittest
from unittest import mock

from soccer_ratings.db import import_country_history


class ImportCountryHistoryProgressTests(unittest.TestCase):
    @mock.patch("soccer_ratings.db.import_league_history")
    @mock.patch("soccer_ratings.db.fetch_country_leagues")
    def test_reports_progress_after_each_league(self, mock_fetch_leagues, mock_import_league) -> None:
        mock_fetch_leagues.return_value = [
            {"league": "Premier League", "league_path": "/England/Premier-League/"},
            {"league": "Championship", "league_path": "/England/Championship/"},
        ]
        mock_import_league.side_effect = [
            {"matches_imported": 10, "deduped_match_count": 8},
            {"matches_imported": 5, "deduped_match_count": 4},
        ]

        progress_calls = []
        result = import_country_history(
            "/England/",
            on_progress=lambda current, total, message: progress_calls.append((current, total, message)),
        )

        self.assertEqual(
            progress_calls,
            [(1, 2, "Premier League"), (2, 2, "Championship")],
        )
        self.assertEqual(result["leagues_processed"], 2)
        self.assertEqual(result["matches_imported"], 15)

    @mock.patch("soccer_ratings.db.import_league_history")
    @mock.patch("soccer_ratings.db.fetch_country_leagues")
    def test_continues_and_reports_progress_after_a_league_failure(
        self, mock_fetch_leagues, mock_import_league
    ) -> None:
        mock_fetch_leagues.return_value = [
            {"league": "Premier League", "league_path": "/England/Premier-League/"},
            {"league": "Championship", "league_path": "/England/Championship/"},
        ]
        mock_import_league.side_effect = [
            RuntimeError("scrape failed"),
            {"matches_imported": 5, "deduped_match_count": 4},
        ]

        progress_calls = []
        result = import_country_history(
            "/England/",
            on_progress=lambda current, total, message: progress_calls.append((current, total, message)),
        )

        self.assertEqual(len(progress_calls), 2)
        self.assertEqual(result["leagues_processed"], 1)
        self.assertEqual(result["failure_count"], 1)

    @mock.patch("soccer_ratings.db.import_league_history")
    @mock.patch("soccer_ratings.db.fetch_country_leagues")
    def test_works_without_a_progress_callback(self, mock_fetch_leagues, mock_import_league) -> None:
        mock_fetch_leagues.return_value = [
            {"league": "Premier League", "league_path": "/England/Premier-League/"},
        ]
        mock_import_league.return_value = {"matches_imported": 1, "deduped_match_count": 1}

        result = import_country_history("/England/")

        self.assertEqual(result["leagues_processed"], 1)


if __name__ == "__main__":
    unittest.main()
