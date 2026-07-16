import unittest
from unittest import mock

from fastapi.testclient import TestClient

from soccer_ratings.dashboard import create_dashboard_app

_COUNTRIES = [
    {"country": "England", "country_path": "/England/", "continent": "Europe"},
    {"country": "NotImportedYet", "country_path": "/NotImportedYet/", "continent": "Europe"},
]
_LEAGUES_BY_COUNTRY = {
    "/England/": [{"league": "Premier League", "league_path": "/England/Premier-League/"}],
}


def _fake_load_country_leagues(country_url, *args, **kwargs):
    return _LEAGUES_BY_COUNTRY.get(country_url, [])


def make_client() -> TestClient:
    return TestClient(create_dashboard_app())


class SitemapRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        from datetime import datetime, timezone
        mock_metadata = {
            "/England/": datetime(2026, 7, 16, 10, 0, 0, tzinfo=timezone.utc),
            "/England/Premier-League/": datetime(2026, 7, 16, 11, 0, 0, tzinfo=timezone.utc),
        }
        patches = (
            mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES),
            mock.patch(
                "soccer_ratings.services.load_country_leagues_from_db",
                side_effect=_fake_load_country_leagues,
            ),
            mock.patch("soccer_ratings.services.fetch_country_leagues"),
            mock.patch("soccer_ratings.services.DashboardServices.get_sitemap_metadata", return_value=mock_metadata),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = make_client()

    def test_sitemap_lists_homepage_countries_and_known_leagues(self) -> None:
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/xml")
        text = response.text
        self.assertIn("<loc>http://testserver/</loc>", text)
        self.assertIn("<lastmod>2026-07-16</lastmod>", text)
        self.assertIn("<changefreq>daily</changefreq>", text)
        self.assertIn("<priority>1.0</priority>", text)

        self.assertIn("<loc>http://testserver/england</loc>", text)
        self.assertIn("<changefreq>weekly</changefreq>", text)
        self.assertIn("<priority>0.8</priority>", text)

        self.assertIn("<loc>http://testserver/notimportedyet</loc>", text)

        self.assertIn("<loc>http://testserver/england/premier-league</loc>", text)
        self.assertIn("<changefreq>daily</changefreq>", text)
        self.assertIn("<priority>0.6</priority>", text)
        self.assertNotIn("league=%2FNotImportedYet%2F", text)


    def test_robots_txt_references_sitemap(self) -> None:
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sitemap: http://testserver/sitemap.xml", response.text)


class OpenGraphTagsTests(unittest.TestCase):
    def setUp(self) -> None:
        ratings = {
            "home": [{"rank": 1, "team": "Arsenal", "rating": 1600}],
            "away": [{"rank": 1, "team": "Arsenal", "rating": 1580}],
        }
        patches = (
            mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES),
            mock.patch(
                "soccer_ratings.services.fetch_country_leagues",
                side_effect=_fake_load_country_leagues,
            ),
            mock.patch(
                "soccer_ratings.services.load_country_leagues_from_db",
                side_effect=_fake_load_country_leagues,
            ),
            mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db", return_value=ratings),
            mock.patch("soccer_ratings.services.load_league_summary_stats", return_value=None),
            mock.patch("soccer_ratings.services.load_cached_league_history", return_value=None),
            mock.patch("soccer_ratings.services.load_league_history_matches", return_value=[]),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = make_client()

    def test_default_page_has_site_wide_og_tags(self) -> None:
        response = self.client.get("/")
        text = response.text
        self.assertIn('<meta property="og:type" content="website">', text)
        self.assertIn('<meta property="og:site_name" content="ratings1x2">', text)
        self.assertIn('<meta property="og:title" content="ratings1x2 — Soccer Ratings, Match Odds &amp; League Analysis">', text)
        self.assertIn('<meta name="twitter:card" content="summary">', text)
        self.assertIn('<link rel="canonical" href="http://testserver/">', text)
        # Verify JSON-LD WebSite Schema
        self.assertIn('"@type": "WebSite"', text)
        self.assertIn('"name": "ratings1x2"', text)
        self.assertNotIn('"@type": "SportsLeague"', text)
        self.assertNotIn('"@type": "BreadcrumbList"', text)
        # Verify theme-color, author, and noscript fallback
        self.assertIn('<meta name="theme-color" content="#e11d2e">', text)
        self.assertIn('<meta name="author" content="ratings1x2">', text)
        self.assertIn('<noscript>', text)

    def test_league_page_has_league_specific_og_tags_and_canonical(self) -> None:
        response = self.client.get("/england/premier-league")
        text = response.text
        self.assertIn('<meta property="og:title" content="Premier League ratings &amp; odds', text)
        self.assertIn(
            'href="http://testserver/england/premier-league"', text
        )
        # Verify JSON-LD WebSite, SportsLeague and BreadcrumbList Schemas
        self.assertIn('"@type": "WebSite"', text)
        self.assertIn('"@type": "SportsLeague"', text)
        self.assertIn('"name": "Premier League"', text)
        self.assertIn('"@type": "BreadcrumbList"', text)
        # Verify visible breadcrumbs
        self.assertIn('class="breadcrumbs"', text)
        self.assertIn('Home', text)
        self.assertIn('Premier League', text)

    def test_admin_page_has_robots_noindex_tag(self) -> None:
        # Request the admin page and verify the presence of robots noindex meta tag
        response = self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn('<meta name="robots" content="noindex, nofollow">', response.text)


if __name__ == "__main__":
    unittest.main()
