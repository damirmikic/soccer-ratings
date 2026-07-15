import unittest
from unittest import mock

from soccer_ratings.services import DashboardServices


class CacheWiringTests(unittest.TestCase):
    def test_cache_ttls_are_configured(self) -> None:
        svc = DashboardServices()
        self.assertEqual(svc._countries_cache._ttl, 12 * 3600)
        self.assertEqual(svc._leagues_cache._ttl, 12 * 3600)
        self.assertEqual(svc._ratings_cache._ttl, 6 * 3600)
        self.assertEqual(svc._known_leagues_cache._ttl, 6 * 3600)


class GetKnownLeaguesByCountryTests(unittest.TestCase):
    @mock.patch("soccer_ratings.services.fetch_country_leagues")
    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    @mock.patch("soccer_ratings.services.fetch_all_rankings")
    def test_omits_countries_with_no_imported_leagues_without_scraping(
        self, mock_countries, mock_load_db, mock_fetch_live
    ) -> None:
        mock_countries.return_value = [
            {"country": "England", "country_path": "/England/", "continent": "Europe"},
            {"country": "Nowhere", "country_path": "/Nowhere/", "continent": "Europe"},
        ]
        mock_load_db.side_effect = lambda country_url, *a, **kw: (
            [{"league": "Premier League", "league_path": "/England/Premier-League/"}]
            if country_url == "/England/"
            else []
        )

        svc = DashboardServices()
        result = svc.get_known_leagues_by_country()

        self.assertEqual(
            result,
            {"/England/": [{"league": "Premier League", "league_path": "/England/Premier-League/"}]},
        )
        mock_fetch_live.assert_not_called()

    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    @mock.patch("soccer_ratings.services.fetch_all_rankings")
    def test_logs_and_omits_country_on_db_failure(self, mock_countries, mock_load_db) -> None:
        mock_countries.return_value = [
            {"country": "England", "country_path": "/England/", "continent": "Europe"},
        ]
        mock_load_db.side_effect = RuntimeError("db down")

        svc = DashboardServices()
        with self.assertLogs("soccer_ratings.services", level="WARNING") as logs:
            result = svc.get_known_leagues_by_country()

        self.assertEqual(result, {})
        self.assertTrue(any("db down" in message for message in logs.output))

    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    @mock.patch("soccer_ratings.services.fetch_all_rankings")
    def test_caches_result_across_calls(self, mock_countries, mock_load_db) -> None:
        mock_countries.return_value = [
            {"country": "England", "country_path": "/England/", "continent": "Europe"},
        ]
        mock_load_db.return_value = [{"league": "Premier League", "league_path": "/England/Premier-League/"}]

        svc = DashboardServices()
        svc.get_known_leagues_by_country()
        svc.get_known_leagues_by_country()

        self.assertEqual(mock_load_db.call_count, 1)


class GetContinentForCountryTests(unittest.TestCase):
    @mock.patch("soccer_ratings.services.fetch_all_rankings")
    def test_finds_continent_for_known_country(self, mock_fetch) -> None:
        mock_fetch.return_value = [
            {"country": "England", "country_path": "/England/", "continent": "Europe"},
        ]
        svc = DashboardServices()
        self.assertEqual(svc.get_continent_for_country("/England/"), "Europe")

    @mock.patch("soccer_ratings.services.fetch_all_rankings")
    def test_returns_empty_string_for_unknown_country(self, mock_fetch) -> None:
        mock_fetch.return_value = [
            {"country": "England", "country_path": "/England/", "continent": "Europe"},
        ]
        svc = DashboardServices()
        self.assertEqual(svc.get_continent_for_country("/Nowhere/"), "")

    def test_returns_empty_string_for_empty_input_without_fetching(self) -> None:
        svc = DashboardServices()
        self.assertEqual(svc.get_continent_for_country(""), "")


class GetLeaguesFallbackTests(unittest.TestCase):
    """get_leagues is live-first: a country with only a handful of leagues
    imported must still show every league that exists on the source site,
    not just the imported subset. DB is only a fallback if the live scrape
    itself fails."""

    @mock.patch("soccer_ratings.services.fetch_country_leagues")
    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    def test_uses_live_scrape_even_when_country_is_partially_imported(
        self, mock_load_db, mock_fetch_live
    ) -> None:
        # DB only knows about one imported league...
        mock_load_db.return_value = [{"league": "Premier League", "league_path": "/England/Premier-League/"}]
        # ...but the source site actually lists several.
        mock_fetch_live.return_value = [
            {"league": "Premier League", "league_path": "/England/Premier-League/"},
            {"league": "Championship", "league_path": "/England/Championship/"},
            {"league": "League One", "league_path": "/England/League-One/"},
        ]

        svc = DashboardServices()
        result = svc.get_leagues("/England/")

        self.assertEqual(result, mock_fetch_live.return_value)
        mock_load_db.assert_not_called()

    @mock.patch("soccer_ratings.services.fetch_country_leagues")
    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    def test_logs_warning_and_falls_back_to_db_when_live_scrape_raises(
        self, mock_load_db, mock_fetch_live
    ) -> None:
        mock_fetch_live.side_effect = RuntimeError("HTTP Error 500: Internal Server Error")
        mock_load_db.return_value = [{"league": "Premier League", "league_path": "/x/"}]

        svc = DashboardServices()
        with self.assertLogs("soccer_ratings.services", level="WARNING") as logs:
            result = svc.get_leagues("/England/")

        self.assertEqual(result, mock_load_db.return_value)
        self.assertTrue(any("HTTP Error 500" in message for message in logs.output))

    @mock.patch("soccer_ratings.services.fetch_country_leagues")
    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    def test_returns_empty_list_and_logs_both_failures_when_live_and_db_fail(
        self, mock_load_db, mock_fetch_live
    ) -> None:
        mock_fetch_live.side_effect = RuntimeError("scrape failed")
        mock_load_db.side_effect = RuntimeError("db down")

        svc = DashboardServices()
        with self.assertLogs("soccer_ratings.services", level="WARNING") as logs:
            result = svc.get_leagues("/England/")

        self.assertEqual(result, [])
        self.assertTrue(any("scrape failed" in message for message in logs.output))
        self.assertTrue(any("db down" in message for message in logs.output))

    @mock.patch("soccer_ratings.services.fetch_country_leagues")
    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    def test_does_not_hit_live_again_within_ttl(self, mock_load_db, mock_fetch_live) -> None:
        mock_fetch_live.return_value = [{"league": "Premier League", "league_path": "/x/"}]

        svc = DashboardServices()
        svc.get_leagues("/England/")
        svc.get_leagues("/England/")

        self.assertEqual(mock_fetch_live.call_count, 1)
        mock_load_db.assert_not_called()

    @mock.patch("soccer_ratings.services.fetch_country_leagues")
    @mock.patch("soccer_ratings.services.load_country_leagues_from_db")
    def test_refreshes_from_live_after_ttl_expires(self, mock_load_db, mock_fetch_live) -> None:
        mock_fetch_live.return_value = [{"league": "Premier League", "league_path": "/x/"}]

        svc = DashboardServices()
        svc.get_leagues("/England/")

        with mock.patch("soccer_ratings.cache.time.monotonic", return_value=999_999_999.0):
            svc.get_leagues("/England/")

        self.assertEqual(mock_fetch_live.call_count, 2)


class GetRatingsFallbackTests(unittest.TestCase):
    @mock.patch("soccer_ratings.services.fetch_league_home_away_ratings")
    @mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db")
    def test_logs_warning_and_falls_back_to_live_scrape_when_db_raises(
        self, mock_load_db, mock_fetch_live
    ) -> None:
        mock_load_db.side_effect = RuntimeError("connection refused")
        mock_fetch_live.return_value = {"home": [], "away": []}

        svc = DashboardServices()
        with self.assertLogs("soccer_ratings.services", level="WARNING") as logs:
            result = svc.get_ratings("/England/Premier-League/")

        self.assertEqual(result, mock_fetch_live.return_value)
        self.assertTrue(any("connection refused" in message for message in logs.output))


class GetRatingsFreshnessTaggingTests(unittest.TestCase):
    @mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db")
    def test_db_result_is_tagged_with_source_db_and_keeps_fetched_at(self, mock_load_db) -> None:
        fetched_at = object()  # opaque sentinel; get_ratings must not transform it
        mock_load_db.return_value = {"home": [{"team": "A"}], "away": [{"team": "B"}], "fetched_at": fetched_at}

        svc = DashboardServices()
        result = svc.get_ratings("/England/Premier-League/")

        self.assertEqual(result["source"], "db")
        self.assertIs(result["fetched_at"], fetched_at)

    @mock.patch("soccer_ratings.services.fetch_league_home_away_ratings")
    @mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db")
    def test_live_scrape_result_is_tagged_source_live_with_no_fetched_at(
        self, mock_load_db, mock_fetch_live
    ) -> None:
        mock_load_db.return_value = None
        mock_fetch_live.return_value = {"home": [{"team": "A"}], "away": [{"team": "B"}]}

        svc = DashboardServices()
        result = svc.get_ratings("/England/Premier-League/")

        self.assertEqual(result["source"], "live")
        self.assertIsNone(result["fetched_at"])


class GetLeagueStatsFallbackTests(unittest.TestCase):
    @mock.patch("soccer_ratings.services.load_cached_league_history")
    @mock.patch("soccer_ratings.services.load_league_summary_stats")
    def test_logs_warning_when_db_raises(self, mock_load_stats, mock_load_cache) -> None:
        mock_load_stats.side_effect = RuntimeError("db down")
        mock_load_cache.return_value = None

        svc = DashboardServices()
        with self.assertLogs("soccer_ratings.services", level="WARNING") as logs:
            result = svc.get_league_stats("/England/Premier-League/")

        self.assertIsNone(result)
        self.assertTrue(any("db down" in message for message in logs.output))


class GetComparisonHistoryFallbackTests(unittest.TestCase):
    @mock.patch("soccer_ratings.services.load_cached_league_history")
    @mock.patch("soccer_ratings.services.load_league_history_matches")
    @mock.patch("soccer_ratings.services.fetch_league_home_away_ratings")
    @mock.patch("soccer_ratings.services.load_league_home_away_ratings_from_db")
    def test_logs_warning_when_history_db_lookup_raises(
        self, mock_load_ratings_db, mock_fetch_ratings, mock_load_matches, mock_load_cache
    ) -> None:
        mock_load_ratings_db.return_value = None
        mock_fetch_ratings.return_value = {
            "home": [{"team": "A", "rating": 1500}],
            "away": [{"team": "B", "rating": 1400}],
        }
        mock_load_matches.side_effect = RuntimeError("db down")
        mock_load_cache.return_value = None

        svc = DashboardServices()
        with self.assertLogs("soccer_ratings.services", level="WARNING") as logs:
            result = svc.get_comparison(
                league_url="/England/Premier-League/",
                home_team="A",
                away_team="B",
                margin_percent=0.0,
            )

        self.assertEqual(result["history_source"], "none")
        self.assertTrue(any("db down" in message for message in logs.output))


if __name__ == "__main__":
    unittest.main()
