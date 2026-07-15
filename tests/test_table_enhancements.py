import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from soccer_ratings.dashboard import create_dashboard_app

_COUNTRIES = [{"country": "England", "country_path": "/England/", "continent": "Europe"}]
_RATINGS = {
    "league_url": "/England/Premier-League/",
    "home": [
        {"rank": 1, "team": "Arsenal", "rating": 1600.0},
        {"rank": 2, "team": "Chelsea", "rating": 1550.0},
    ],
    "away": [
        {"rank": 1, "team": "Arsenal", "rating": 1580.0},
        {"rank": 2, "team": "Chelsea", "rating": 1500.0},
    ],
}


def make_client() -> TestClient:
    return TestClient(create_dashboard_app())


class RatingsFreshnessBannerTests(unittest.TestCase):
    def _fetch_league_content(self):
        return self.client.get(
            "/fragments/league-content?league_url=/England/Premier-League/&country_url=/England/"
        )

    def test_shows_relative_time_when_snapshot_has_a_timestamp(self) -> None:
        fetched_at = datetime.now(timezone.utc) - timedelta(hours=3, minutes=10)
        db_ratings = dict(_RATINGS, fetched_at=fetched_at)
        with mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES), mock.patch(
            "soccer_ratings.services.load_league_home_away_ratings_from_db", return_value=db_ratings
        ), mock.patch("soccer_ratings.services.load_league_summary_stats", return_value=None), mock.patch(
            "soccer_ratings.services.load_cached_league_history", return_value=None
        ), mock.patch("soccer_ratings.services.load_league_history_matches", return_value=[]):
            self.client = make_client()
            response = self._fetch_league_content()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Ratings updated 3h ago", response.text)

    def test_shows_live_data_wording_when_not_yet_cached(self) -> None:
        with mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES), mock.patch(
            "soccer_ratings.services.load_league_home_away_ratings_from_db", return_value=None
        ), mock.patch(
            "soccer_ratings.services.fetch_league_home_away_ratings", return_value=dict(_RATINGS)
        ), mock.patch("soccer_ratings.services.load_league_summary_stats", return_value=None), mock.patch(
            "soccer_ratings.services.load_cached_league_history", return_value=None
        ), mock.patch("soccer_ratings.services.load_league_history_matches", return_value=[]):
            self.client = make_client()
            response = self._fetch_league_content()

        self.assertEqual(response.status_code, 200)
        self.assertIn("Live data", response.text)
        self.assertIn("not yet cached", response.text)


class RatingsTableMarkupTests(unittest.TestCase):
    def setUp(self) -> None:
        patches = (
            mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES),
            mock.patch(
                "soccer_ratings.services.load_league_home_away_ratings_from_db",
                return_value=dict(_RATINGS),
            ),
            mock.patch("soccer_ratings.services.load_league_summary_stats", return_value=None),
            mock.patch("soccer_ratings.services.load_cached_league_history", return_value=None),
            mock.patch("soccer_ratings.services.load_league_history_matches", return_value=[]),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = make_client()

    def test_tables_carry_sort_and_team_data_attributes(self) -> None:
        response = self.client.get(
            "/fragments/league-content?league_url=/England/Premier-League/&country_url=/England/"
        )
        text = response.text
        self.assertIn('data-role="home-ratings"', text)
        self.assertIn('data-role="away-ratings"', text)
        self.assertIn('data-team="Arsenal"', text)
        self.assertIn('data-team="Chelsea"', text)
        self.assertIn('data-sort-key="rank"', text)
        self.assertIn('data-sort-key="team"', text)
        self.assertIn('data-sort-key="rating"', text)
        self.assertIn('data-cell="rating"', text)

    def test_team_filter_input_present(self) -> None:
        response = self.client.get(
            "/fragments/league-content?league_url=/England/Premier-League/&country_url=/England/"
        )
        self.assertIn('id="team-filter"', response.text)

    def test_multi_match_export_csv_button_present(self) -> None:
        response = self.client.get(
            "/fragments/league-content?league_url=/England/Premier-League/&country_url=/England/"
        )
        self.assertIn('id="multi-export-csv"', response.text)


if __name__ == "__main__":
    unittest.main()
