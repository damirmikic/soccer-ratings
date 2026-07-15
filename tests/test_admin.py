import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from soccer_ratings.dashboard import create_dashboard_app

_COUNTRIES = [{"country": "England", "country_path": "/England/", "continent": "Europe"}]
_LEAGUES = [{"league": "Premier League", "league_path": "/England/Premier-League/"}]

_PATCHES = (
    mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES),
    mock.patch("soccer_ratings.services.fetch_country_leagues", return_value=_LEAGUES),
    mock.patch("soccer_ratings.services.load_country_leagues_from_db", return_value=_LEAGUES),
    mock.patch("soccer_ratings.services.load_cached_league_history", return_value=None),
)


def make_client() -> TestClient:
    # https base_url so the Secure admin-session cookie is actually resent
    # by the test client on subsequent requests, matching real browser
    # behavior on the HTTPS-only Render deployment.
    return TestClient(create_dashboard_app(), base_url="https://testserver")


class AdminLoginPageTests(unittest.TestCase):
    def setUp(self) -> None:
        for patcher in _PATCHES:
            patcher.start()
            self.addCleanup(patcher.stop)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": ""})
    def test_shows_disabled_message_when_no_token_configured(self) -> None:
        response = make_client().get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Admin actions are disabled", response.text)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_shows_login_form_when_not_authenticated(self) -> None:
        response = make_client().get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="admin_token"', response.text)
        self.assertNotIn("Import Country to DB", response.text)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_wrong_token_redirects_back_with_error(self) -> None:
        client = make_client()
        response = client.post(
            "/admin/login", data={"admin_token": "wrong"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin?error=1")

        followed = client.get(response.headers["location"])
        self.assertIn("Invalid admin token", followed.text)


class AdminSessionFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        for patcher in _PATCHES:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env_patch = mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = make_client()

    def _log_in(self) -> None:
        response = self.client.post(
            "/admin/login", data={"admin_token": "secret"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("admin_session", self.client.cookies)

    def test_login_sets_session_cookie_and_shows_tools(self) -> None:
        self._log_in()
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Import Country to DB", response.text)
        self.assertIn("Log out", response.text)

    def test_session_cookie_authorizes_country_import_without_a_token(self) -> None:
        self._log_in()
        with mock.patch("soccer_ratings.services.import_country_history_to_db") as mock_import:
            mock_import.return_value = {
                "leagues_processed": 1,
                "matches_imported": 5,
                "failure_count": 0,
            }
            response = self.client.post(
                "/fragments/country-import", data={"country_url": "/England/"}
            )
        self.assertEqual(response.status_code, 200)

    def test_session_cookie_authorizes_league_panel(self) -> None:
        self._log_in()
        response = self.client.get(
            "/admin/league-panel?league_url=/England/Premier-League/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Build Local Cache", response.text)
        self.assertIn("Import To DB", response.text)

    def test_logout_clears_session_and_revokes_access(self) -> None:
        self._log_in()
        response = self.client.post("/admin/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin")

        after_logout = self.client.get("/admin")
        self.assertIn('name="admin_token"', after_logout.text)

        panel_response = self.client.get(
            "/admin/league-panel?league_url=/England/Premier-League/"
        )
        self.assertEqual(panel_response.status_code, 401)


class AdminLeaguePanelAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        for patcher in _PATCHES:
            patcher.start()
            self.addCleanup(patcher.stop)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_requires_admin_without_session(self) -> None:
        response = make_client().get(
            "/admin/league-panel?league_url=/England/Premier-League/"
        )
        self.assertEqual(response.status_code, 401)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_header_token_still_works_without_a_session(self) -> None:
        response = make_client().get(
            "/admin/league-panel?league_url=/England/Premier-League/",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(response.status_code, 200)


class PublicUIHasNoAdminControlsTests(unittest.TestCase):
    def setUp(self) -> None:
        ratings = {
            "home": [{"rank": 1, "team": "Arsenal", "rating": 1600}],
            "away": [{"rank": 1, "team": "Arsenal", "rating": 1580}],
        }
        patches = _PATCHES + (
            mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db", return_value=ratings),
            mock.patch("soccer_ratings.services.load_league_summary_stats", return_value=None),
            mock.patch("soccer_ratings.services.load_league_history_matches", return_value=[]),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = make_client()

    def test_index_has_no_admin_controls(self) -> None:
        response = self.client.get(
            "/?country=/England/&league=/England/Premier-League/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Import Country to DB", response.text)
        self.assertNotIn("Build Local Cache", response.text)
        self.assertNotIn("admin_token", response.text)

    def test_league_content_fragment_has_no_admin_controls(self) -> None:
        response = self.client.get(
            "/fragments/league-content?league_url=/England/Premier-League/&country_url=/England/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Build Local Cache", response.text)
        self.assertNotIn("Import To DB", response.text)
        # Read-only status line should remain.
        self.assertIn("history-cache-meta", response.text)

    def test_robots_txt_disallows_admin(self) -> None:
        response = self.client.get("/robots.txt")
        self.assertIn("Disallow: /admin", response.text)


if __name__ == "__main__":
    unittest.main()
