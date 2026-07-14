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
        patches = (
            mock.patch("soccer_ratings.services.fetch_all_rankings", return_value=_COUNTRIES),
            mock.patch(
                "soccer_ratings.services.load_country_leagues_from_db",
                side_effect=_fake_load_country_leagues,
            ),
            mock.patch("soccer_ratings.services.fetch_country_leagues"),
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
        self.assertIn("country=%2FEngland%2F", text)
        self.assertIn("country=%2FNotImportedYet%2F", text)
        self.assertIn("league=%2FEngland%2FPremier-League%2F", text)
        # The not-yet-imported country should appear (as a country page)
        # but must not have triggered a live scrape for its leagues.
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
                "soccer_ratings.services.load_country_leagues_from_db",
                side_effect=_fake_load_country_leagues,
            ),
            mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db", return_value=ratings),
            mock.patch("soccer_ratings.services.load_league_summary_stats", return_value=None),
            mock.patch("soccer_ratings.services.load_cached_league_history", return_value=None),
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
        self.assertIn('<meta property="og:title" content="ratings1x2 - soccer match ratings">', text)
        self.assertIn('<meta name="twitter:card" content="summary">', text)
        self.assertIn('<link rel="canonical" href="http://testserver/">', text)

    def test_league_page_has_league_specific_og_tags_and_canonical(self) -> None:
        response = self.client.get("/?country=/England/&league=/England/Premier-League/")
        text = response.text
        self.assertIn('<meta property="og:title" content="Premier League ratings &amp; odds', text)
        self.assertIn(
            'href="http://testserver/?country=/England/&amp;league=/England/Premier-League/"', text
        )


if __name__ == "__main__":
    unittest.main()
