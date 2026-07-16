from __future__ import annotations

import logging

from .backtest import run_league_backtest
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
from .db import (
    load_all_history_matches,
    load_league_history_matches,
    load_league_tuning_parameters,
    matches_to_csv,
)
from .db import (
    import_country_history as import_country_history_to_db,
    import_league_history as import_league_history_to_db,
    load_country_leagues as load_country_leagues_from_db,
)
from .db import (
    load_league_home_away_ratings as load_league_home_away_ratings_from_db,
    load_league_summary_stats,
    run_calibration_sweep,
)
from .jobs import JobManager

logger = logging.getLogger(__name__)

# Countries and leagues change rarely; ratings are what users care about
# being fresh, so they get a shorter TTL. Both are well within the range
# recommended for a low-write scraped dataset like this one.
_COUNTRIES_CACHE_TTL_SECONDS = 12 * 3600
_LEAGUES_CACHE_TTL_SECONDS = 12 * 3600
_RATINGS_CACHE_TTL_SECONDS = 6 * 3600
_KNOWN_LEAGUES_CACHE_TTL_SECONDS = 6 * 3600

_COUNTRIES_CACHE_KEY = "all"
_KNOWN_LEAGUES_CACHE_KEY = "all"


class DashboardServices:
    def __init__(self) -> None:
        self._countries_cache = TTLCache(_COUNTRIES_CACHE_TTL_SECONDS)
        self._leagues_cache = TTLCache(_LEAGUES_CACHE_TTL_SECONDS)
        self._ratings_cache = TTLCache(_RATINGS_CACHE_TTL_SECONDS)
        self._known_leagues_cache = TTLCache(_KNOWN_LEAGUES_CACHE_TTL_SECONDS)
        self._jobs = JobManager()
        self._active_country_imports: dict[str, str] = {}
        self._active_calibration_sweep_job_id: str | None = None

    @property
    def pool(self):
        from .db import get_pool
        return get_pool()

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
        """Live-scraped list, so a country with only a few leagues imported
        still shows every league that actually exists on the source site
        (not just the imported subset) — DB is only a fallback if the live
        scrape itself fails.
        """
        cached = self._leagues_cache.get(country_url)
        if cached is not None:
            return cached

        try:
            leagues = fetch_country_leagues(country_url)
        except Exception as exc:
            logger.warning(
                "Live scrape failed for leagues in %s (%s: %s); falling back to DB",
                country_url,
                type(exc).__name__,
                exc,
            )
            leagues = []
            try:
                leagues = load_country_leagues_from_db(country_url)
            except Exception as db_exc:
                logger.warning(
                    "DB lookup also failed for leagues in %s (%s: %s)",
                    country_url,
                    type(db_exc).__name__,
                    db_exc,
                )
        self._leagues_cache.set(country_url, leagues)
        return leagues

    def get_known_leagues_by_country(self) -> dict[str, list[dict]]:
        """DB-only league listing per country, for the sitemap.

        Deliberately never falls back to a live scrape (unlike get_leagues)
        so a crawler hitting /sitemap.xml can't trigger a scrape across
        every country that hasn't been imported yet. Countries with no
        imported leagues are simply omitted.
        """
        cached = self._known_leagues_cache.get(_KNOWN_LEAGUES_CACHE_KEY)
        if cached is not None:
            return cached

        result: dict[str, list[dict]] = {}
        for country in self.get_countries():
            country_url = country.get("country_path")
            if not country_url:
                continue
            try:
                leagues = load_country_leagues_from_db(country_url)
            except Exception as exc:
                logger.warning(
                    "DB lookup failed for sitemap leagues in %s (%s: %s); omitting from sitemap",
                    country_url,
                    type(exc).__name__,
                    exc,
                )
                continue
            if leagues:
                result[country_url] = leagues

        self._known_leagues_cache.set(_KNOWN_LEAGUES_CACHE_KEY, result)
        return result

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
        if ratings:
            ratings["source"] = "db"
        else:
            ratings = fetch_league_home_away_ratings(league_url)
            ratings["source"] = "live"
            ratings["fetched_at"] = None
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

        tuning_params = None
        try:
            tuning_params = load_league_tuning_parameters(league_url)
        except Exception as exc:
            logger.warning(
                "DB lookup failed for tuning parameters in %s (%s: %s)",
                league_url,
                type(exc).__name__,
                exc,
            )

        comparison = compare_teams_from_ratings(
            ratings["home"],
            ratings["away"],
            home_team=home_team,
            away_team=away_team,
            margin_percent=margin_percent,
            historical_matches=historical_matches,
            tuning_params=tuning_params,
        )
        comparison["history_source"] = history_source
        return comparison

    def get_backtest(
        self,
        league_url: str,
        edge_threshold_percent: float = 5.0,
        stake: float = 1.0,
    ) -> dict:
        historical_matches: list[dict] = []
        history_source = "none"
        try:
            historical_matches = load_league_history_matches(league_url)
            if historical_matches:
                history_source = "postgres"
        except Exception as exc:
            logger.warning(
                "DB lookup failed for backtest history in %s (%s: %s); falling back to cached history file",
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

        tuning_params = None
        try:
            tuning_params = load_league_tuning_parameters(league_url)
        except Exception as exc:
            logger.warning(
                "DB lookup failed for tuning parameters in %s (%s: %s)",
                league_url,
                type(exc).__name__,
                exc,
            )

        result = run_league_backtest(
            historical_matches,
            edge_threshold_percent=edge_threshold_percent,
            stake=stake,
            tuning_params=tuning_params,
        )
        result["league_url"] = league_url
        result["history_source"] = history_source
        return result

    def get_history_status(self, league_url: str) -> dict:
        cached = load_cached_league_history(league_url)
        db_count = 0
        try:
            db_matches = load_league_history_matches(league_url)
            db_count = len(db_matches)
        except Exception:
            db_count = 0
        if cached is None:
            return {"cached": False, "league_url": league_url, "db_match_count": db_count}
        return {
            "cached": True,
            "league_url": cached.get("league_url", league_url),
            "team_count": cached.get("team_count", 0),
            "raw_match_count": cached.get("raw_match_count", 0),
            "deduped_match_count": cached.get("deduped_match_count", 0),
            "cache_path": cached.get("cache_path", ""),
            "db_match_count": db_count,
        }

    def export_history_matches(
        self,
        league_url: str = "",
        competition: str = "",
        completed_only: bool = True,
    ) -> list[dict]:
        if league_url:
            return load_league_history_matches(league_url, completed_only=completed_only)
        return load_all_history_matches(competition=competition, completed_only=completed_only)

    def export_history_csv(
        self,
        league_url: str = "",
        competition: str = "",
        completed_only: bool = True,
    ) -> str:
        matches = self.export_history_matches(league_url, competition, completed_only=completed_only)
        return matches_to_csv(matches)

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

    def start_calibration_sweep_job(self) -> str:
        """Kick off (or reuse) a background calibration sweep across every
        imported league. Reuses a running job the same way country imports
        do, so a double-click doesn't queue a second sweep.
        """
        if self._active_calibration_sweep_job_id and self._jobs.is_running(
            self._active_calibration_sweep_job_id
        ):
            return self._active_calibration_sweep_job_id

        job_id = self._jobs.create(kind="calibration_sweep", label="all imported leagues")
        self._active_calibration_sweep_job_id = job_id
        return job_id

    def run_calibration_sweep_job(self, job_id: str) -> None:
        """Blocking worker body — schedule via BackgroundTasks, never call directly from a request."""

        def task(on_progress):
            return run_calibration_sweep(on_progress=on_progress)

        self._jobs.run(job_id, task)

    def get_job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)
