import unittest
from unittest import mock

from fastapi.testclient import TestClient

from soccer_ratings.dashboard import create_dashboard_app

_COUNTRIES = [
    {"country": "England", "country_path": "/England/", "continent": "Europe"},
    {"country": "Spain", "country_path": "/Spain/", "continent": "Europe"},
]
_LEAGUES = [{"league": "Premier League", "league_path": "/England/Premier-League/"}]
_RATINGS = {
    "home": [
        {"rank": 1, "team": "Arsenal", "rating": 1600},
        {"rank": 2, "team": "Chelsea", "rating": 1550},
    ],
    "away": [
        {"rank": 1, "team": "Arsenal", "rating": 1580},
        {"rank": 2, "team": "Chelsea", "rating": 1500},
    ],
}

_PATCHES = (
    mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES),
    mock.patch("soccer_ratings.services.fetch_country_leagues", return_value=_LEAGUES),
    mock.patch("soccer_ratings.services.load_country_leagues_from_db", return_value=_LEAGUES),
    mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db", return_value=_RATINGS),
    mock.patch("soccer_ratings.services.load_league_summary_stats", return_value=None),
    mock.patch("soccer_ratings.services.load_cached_league_history", return_value=None),
    mock.patch("soccer_ratings.services.load_league_history_matches", return_value=[]),
)


def make_client() -> TestClient:
    app = create_dashboard_app()
    return TestClient(app)


class IndexSharedLinkRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        for patcher in _PATCHES:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = make_client()

    def test_plain_index_has_no_preselection(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="league-loading"', response.text)
        self.assertNotIn("match-card", response.text)

    def test_league_link_preselects_and_renders_league_content(self) -> None:
        response = self.client.get("/?country=/England/&league=/England/Premier-League/", follow_redirects=False)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["location"], "/england/premier-league")

        response = self.client.get("/england/premier-league")
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="/England/" selected', response.text)
        self.assertIn('value="/England/Premier-League/" selected', response.text)
        self.assertIn("Premier League ratings", response.text)
        self.assertIn('id="league-data"', response.text)
        self.assertNotIn('id="league-loading"', response.text)

    def test_full_matchup_link_renders_comparison_inline(self) -> None:
        response = self.client.get(
            "/?country=/England/&league=/England/Premier-League/"
            "&home=Arsenal&away=Chelsea&margin=2",
            follow_redirects=False
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["location"], "/england/premier-league/arsenal-vs-chelsea?margin=2.0")

        response = self.client.get("/england/premier-league/arsenal-vs-chelsea?margin=2")
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="Arsenal" selected', response.text)
        self.assertIn('value="Chelsea" selected', response.text)
        self.assertIn('value="2.0"', response.text)
        self.assertIn("match-card", response.text)
        self.assertIn("odds-pill", response.text)

    def test_unresolvable_league_falls_back_gracefully(self) -> None:
        response = self.client.get("/?country=/England/&league=/Nowhere/Fake-League/", follow_redirects=False)
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["location"], "/england/fake-league")

        response = self.client.get("/england/fake-league")
        self.assertEqual(response.status_code, 404)


class FragmentPushUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        for patcher in _PATCHES:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = make_client()

    def test_country_options_pushes_continent_only(self) -> None:
        response = self.client.get("/fragments/country-options?continent=Europe")
        self.assertEqual(response.headers["HX-Push-Url"], "/?continent=Europe")

    def test_league_options_pushes_continent_and_country(self) -> None:
        response = self.client.get("/fragments/league-options?country_url=/England/")
        self.assertEqual(
            response.headers["HX-Push-Url"],
            "/england",
        )

    def test_league_content_pushes_full_league_state(self) -> None:
        response = self.client.get(
            "/fragments/league-content?league_url=/England/Premier-League/&country_url=/England/"
        )
        self.assertEqual(
            response.headers["HX-Push-Url"],
            "/england/premier-league",
        )

    def test_compare_pushes_full_matchup_state(self) -> None:
        response = self.client.get(
            "/fragments/compare"
            "?league_url=/England/Premier-League/&country_url=/England/"
            "&home_team=Arsenal&away_team=Chelsea&margin=3.5"
        )
        self.assertEqual(
            response.headers["HX-Push-Url"],
            "/england/premier-league/arsenal-vs-chelsea?margin=3.5",
        )


    def test_compare_does_not_push_url_when_teams_incomplete(self) -> None:
        response = self.client.get(
            "/fragments/compare?league_url=/England/Premier-League/&home_team=Arsenal&away_team="
        )
        self.assertNotIn("HX-Push-Url", response.headers)


if __name__ == "__main__":
    unittest.main()
