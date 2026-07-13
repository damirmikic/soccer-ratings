import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from soccer_ratings.dashboard import create_dashboard_app


class StubServices:
    """Stands in for DashboardServices so tests never hit the network or DB."""

    def get_countries(self):
        return [{"country": "England", "country_path": "/England/", "continent": "Europe"}]

    def build_history_cache(self, league_url, refresh):
        return {
            "league_url": league_url,
            "team_count": 2,
            "raw_match_count": 10,
            "deduped_match_count": 5,
            "cache_path": "/tmp/cache.json",
        }

    def import_history_to_db(self, league_url):
        return {"league_url": league_url, "matches_imported": 5}

    def import_country_to_db(self, country_url):
        return {"leagues_processed": 2, "matches_imported": 10, "failure_count": 0}


def make_client() -> TestClient:
    app = create_dashboard_app()
    app.state.services = StubServices()
    return TestClient(app)


class AdminAuthTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": ""})
    def test_admin_endpoints_disabled_without_configured_token(self) -> None:
        client = make_client()
        response = client.post("/api/league-history/import?league_url=/x/")
        self.assertEqual(response.status_code, 503)
        self.assertIn("ADMIN_TOKEN", response.json()["detail"])

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_admin_endpoints_reject_wrong_token(self) -> None:
        client = make_client()
        response = client.post(
            "/api/league-history/import?league_url=/x/",
            headers={"X-Admin-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_admin_endpoints_accept_header_token(self) -> None:
        client = make_client()
        response = client.post(
            "/api/league-history/import?league_url=/x/",
            headers={"X-Admin-Token": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["matches_imported"], 5)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_fragment_endpoints_accept_form_token(self) -> None:
        client = make_client()
        response = client.post(
            "/fragments/history-import",
            data={"league_url": "/x/", "admin_token": "secret"},
        )
        self.assertEqual(response.status_code, 200)

    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_country_import_fragment_requires_token(self) -> None:
        client = make_client()
        response = client.post("/fragments/country-import", data={"country_url": "/England/"})
        self.assertEqual(response.status_code, 401)

    def test_import_endpoints_no_longer_accept_get(self) -> None:
        for path in (
            "/api/league-history/import?league_url=/x/",
            "/api/league-history/build?league_url=/x/",
            "/api/country-history/import?country_url=/x/",
            "/fragments/history-build?league_url=/x/",
            "/fragments/history-import?league_url=/x/",
            "/fragments/country-import?country_url=/x/",
        ):
            # Fresh app per request so the strict per-IP budget on these
            # endpoints doesn't turn later responses into 429s.
            response = make_client().get(path)
            self.assertEqual(response.status_code, 405, path)


class SecurityHeaderTests(unittest.TestCase):
    def test_security_headers_present(self) -> None:
        client = make_client()
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_robots_txt_blocks_fragments_and_api(self) -> None:
        client = make_client()
        response = client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Disallow: /fragments/", response.text)
        self.assertIn("Disallow: /api/", response.text)


class RateLimitTests(unittest.TestCase):
    @mock.patch.dict(os.environ, {"ADMIN_TOKEN": "secret"})
    def test_expensive_endpoints_rate_limited(self) -> None:
        client = make_client()
        statuses = []
        for _ in range(6):
            response = client.post(
                "/api/league-history/build?league_url=/x/",
                headers={"X-Admin-Token": "secret"},
            )
            statuses.append(response.status_code)
        self.assertEqual(statuses[:5], [200] * 5)
        self.assertEqual(statuses[5], 429)

    def test_general_traffic_not_blocked_by_expensive_limit(self) -> None:
        client = make_client()
        for _ in range(10):
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
