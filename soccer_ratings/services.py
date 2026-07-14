from __future__ import annotations

import logging

from .cache import TTLCache
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
from .jobs import JobManager

logger = logging.getLogger(__name__)

# Countries and leagues change rarely; ratings are what users care about
# being fresh, so they get a shorter TTL. Both are well within the range
# recommended for a low-write scraped dataset like this one.
_COUNTRIES_CACHE_TTL_SECONDS = 12 * 3600
_LEAGUES_CACHE_TTL_SECONDS = 12 * 3600
_RATINGS_CACHE_TTL_SECONDS = 6 * 3600

_COUNTRIES_CACHE_KEY = "all"


class DashboardServices:
    def __init__(self) -> None:
        self._countries_cache = TTLCache(_COUNTRIES_CACHE_TTL_SECONDS)
        self._leagues_cache = TTLCache(_LEAGUES_CACHE_TTL_SECONDS)
        self._ratings_cache = TTLCache(_RATINGS_CACHE_TTL_SECONDS)
        self._jobs = JobManager()
        self._active_country_imports: dict[str, str] = {}

    def get_countries(self) -> list[dict]:
        cached = self._countries_cache.get(_COUNTRIES_CACHE_KEY)
        if cached is not None:
            return cached
        countries = fetch_all_rankings()
        self._countries_cache.set(_COUNTRIES_CACHE_KEY, countries)
        return countries

    def get_continent_for_country(self, country_url: str) -> str:
        """Looks up the continent for a country_path, for building shareable
        URLs server-side without the client having to pass it along."""
        if not country_url:
            return ""
        for country in self.get_countries():
            if country.get("country_path") == country_url:
                return country.get("continent") or ""
        return ""

    def get_leagues(self, country_url: str) -> list[dict]:
        cached = self._leagues_cache.get(country_url)
        if cached is not None:
            return cached

        leagues: list[dict] = []
        try:
            leagues = load_country_leagues_from_db(country_url)
        except Exception as exc:
            logger.warning(
                "DB lookup failed for leagues in %s (%s: %s); falling back to live scrape",
                country_url,
                type(exc).__name__,
                exc,
            )
        if not leagues:
            leagues = fetch_country_leagues(country_url)
        self._leagues_cache.set(country_url, leagues)
        return leagues

    def get_ratings(self, league_url: str) -> dict:
        cached = self._ratings_cache.get(league_url)
        if cached is not None:
            return cached

        ratings = None
        try:
            ratings = load_league_home_away_ratings_from_db(league_url)
        except Exception as exc:
            logger.warning(
                "DB lookup failed for ratings in %s (%s: %s); falling back to live scrape",
                league_url,
                type(exc).__name__,
                exc,
            )
        if not ratings:
            ratings = fetch_league_home_away_ratings(league_url)
        self._ratings_cache.set(league_url, ratings)
        return ratings

    def get_league_stats(self, league_url: str) -> dict | None:
        try:
            league_stats = load_league_summary_stats(league_url)
        except Exception as exc:
            logger.warning(
                "DB lookup failed for league stats in %s (%s: %s); falling back to cached history file",
                league_url,
                type(exc).__name__,
                exc,
            )
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
        except Exception as exc:
            logger.warning(
                "DB lookup failed for match history in %s (%s: %s); falling back to cached history file",
                league_url,
                type(exc).__name__,
                exc,
            )
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

    def start_country_import_job(self, country_url: str) -> str:
        """Kick off (or reuse) a background country import job.

        Returns an existing job id if one is already running for this
        country, so a double-click doesn't queue a second scrape of the
        same country.
        """
        existing_job_id = self._active_country_imports.get(country_url)
        if existing_job_id and self._jobs.is_running(existing_job_id):
            return existing_job_id

        job_id = self._jobs.create(kind="country_import", label=country_url)
        self._active_country_imports[country_url] = job_id
        return job_id

    def run_country_import_job(self, job_id: str, country_url: str) -> None:
        """Blocking worker body — schedule via BackgroundTasks, never call directly from a request."""

        def task(on_progress):
            return import_country_history_to_db(country_url, on_progress=on_progress)

        self._jobs.run(job_id, task)

    def get_job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)
