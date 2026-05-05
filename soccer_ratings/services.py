from __future__ import annotations

from .client import (
    build_and_cache_league_history,
    compare_teams_from_ratings,
    fetch_all_rankings,
    fetch_country_leagues,
    fetch_league_home_away_ratings,
    filter_matches_for_league,
    load_cached_league_history,
    summarize_league_stats,
)
from .db import load_league_history_matches
from .db import (
    import_country_history as import_country_history_to_db,
    import_league_history as import_league_history_to_db,
    load_country_leagues as load_country_leagues_from_db,
)
from .db import (
    load_league_home_away_ratings as load_league_home_away_ratings_from_db,
    load_league_summary_stats,
)


class DashboardServices:
    def __init__(self) -> None:
        self._countries_cache: list[dict] | None = None
        self._leagues_cache: dict[str, list[dict]] = {}
        self._ratings_cache: dict[str, dict] = {}

    def get_countries(self) -> list[dict]:
        if self._countries_cache is None:
            self._countries_cache = fetch_all_rankings()
        return self._countries_cache

    def get_leagues(self, country_url: str) -> list[dict]:
        if country_url not in self._leagues_cache:
            try:
                self._leagues_cache[country_url] = load_country_leagues_from_db(country_url)
            except Exception:
                self._leagues_cache[country_url] = []
            if not self._leagues_cache[country_url]:
                self._leagues_cache[country_url] = fetch_country_leagues(country_url)
        return self._leagues_cache[country_url]

    def get_ratings(self, league_url: str) -> dict:
        if league_url not in self._ratings_cache:
            try:
                self._ratings_cache[league_url] = load_league_home_away_ratings_from_db(league_url)
            except Exception:
                self._ratings_cache[league_url] = None
            if not self._ratings_cache[league_url]:
                self._ratings_cache[league_url] = fetch_league_home_away_ratings(league_url)
        return self._ratings_cache[league_url]

    def get_league_stats(self, league_url: str) -> dict | None:
        try:
            league_stats = load_league_summary_stats(league_url)
        except Exception:
            league_stats = None
        if league_stats is None:
            cached = load_cached_league_history(league_url)
            if cached is not None:
                league_stats = summarize_league_stats(
                    filter_matches_for_league(cached.get("matches", []), league_url)
                )
        return league_stats

    def get_comparison(
        self,
        league_url: str,
        home_team: str,
        away_team: str,
        margin_percent: float,
    ) -> dict:
        ratings = self.get_ratings(league_url)

        historical_matches: list[dict] = []
        history_source = "none"
        try:
            historical_matches = load_league_history_matches(league_url)
            if historical_matches:
                history_source = "postgres"
        except Exception:
            historical_matches = []

        if not historical_matches:
            cached = load_cached_league_history(league_url)
            if cached is not None:
                historical_matches = filter_matches_for_league(
                    cached.get("matches", []),
                    league_url,
                )
                if historical_matches:
                    history_source = "cache"

        comparison = compare_teams_from_ratings(
            ratings["home"],
            ratings["away"],
            home_team=home_team,
            away_team=away_team,
            margin_percent=margin_percent,
            historical_matches=historical_matches,
        )
        comparison["history_source"] = history_source
        return comparison

    def get_history_status(self, league_url: str) -> dict:
        cached = load_cached_league_history(league_url)
        if cached is None:
            return {"cached": False, "league_url": league_url}
        return {
            "cached": True,
            "league_url": cached.get("league_url", league_url),
            "team_count": cached.get("team_count", 0),
            "raw_match_count": cached.get("raw_match_count", 0),
            "deduped_match_count": cached.get("deduped_match_count", 0),
            "cache_path": cached.get("cache_path", ""),
        }

    def build_history_cache(self, league_url: str, refresh: bool) -> dict:
        return build_and_cache_league_history(league_url, force_refresh=refresh)

    def import_history_to_db(self, league_url: str) -> dict:
        return import_league_history_to_db(league_url)

    def import_country_to_db(self, country_url: str) -> dict:
        return import_country_history_to_db(country_url)
