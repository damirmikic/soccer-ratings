from __future__ import annotations

import csv
import io
import logging
import os
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .client import (
    fetch_country_leagues,
    fetch_league_history,
    fetch_league_home_away_ratings,
    fetch_league_ratings,
    fetch_rankings,
    league_code_from_url,
)
from .env import load_env_file
from .tuning import DEFAULT_MIN_MATCHES, fit_league_model

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
load_env_file()


def get_database_url(explicit_url: str | None = None, *, use_direct: bool = False) -> str:
    database_url = explicit_url
    if not database_url:
        database_url = os.getenv("DIRECT_DATABASE_URL") if use_direct else os.getenv("DATABASE_URL")
    if not database_url and use_direct:
        database_url = os.getenv("DATABASE_URL")
    if not database_url:
        expected_var = "DIRECT_DATABASE_URL or DATABASE_URL" if use_direct else "DATABASE_URL"
        raise RuntimeError(f"{expected_var} is not set")
    return database_url


logger = logging.getLogger(__name__)

_POOL = None


def init_pool(database_url: str | None = None, min_size: int | None = None, max_size: int | None = None) -> None:
    global _POOL
    if _POOL is not None:
        return

    try:
        url = get_database_url(database_url, use_direct=False)
    except RuntimeError as exc:
        logger.warning("Could not initialize connection pool: %s", exc)
        return

    if min_size is None:
        try:
            min_size = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
        except ValueError:
            min_size = 1
    if max_size is None:
        try:
            max_size = int(os.getenv("DB_POOL_MAX_SIZE", "10"))
        except ValueError:
            max_size = 10

    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "psycopg-pool is required for connection pooling. Install it with `pip install psycopg-pool`."
        ) from exc

    logger.info("Initializing psycopg_pool.ConnectionPool with min_size=%d, max_size=%d", min_size, max_size)
    _POOL = ConnectionPool(url, min_size=min_size, max_size=max_size, open=True)


def close_pool() -> None:
    global _POOL
    if _POOL is not None:
        logger.info("Closing psycopg_pool.ConnectionPool")
        _POOL.close()
        _POOL = None


def get_pool():
    global _POOL
    return _POOL


def connect(database_url: str | None = None, *, use_direct: bool = False):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for Postgres support. Install it with `pip install psycopg[binary]`."
        ) from exc

    return psycopg.connect(get_database_url(database_url, use_direct=use_direct))


@contextmanager
def db_cursor(database_url: str | None = None, *, use_direct: bool = False) -> Iterator:
    global _POOL
    if not use_direct and database_url is None and _POOL is not None:
        with _POOL.connection() as conn:
            with conn.cursor() as cur:
                yield conn, cur
    else:
        with connect(database_url, use_direct=use_direct) as conn:
            with conn.cursor() as cur:
                yield conn, cur


def init_db(database_url: str | None = None) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with db_cursor(database_url, use_direct=False) as (conn, cur):
        cur.execute(schema_sql)
        # elo_divisor/draw_max/draw_divisor/draw_min are retired (the 1X2
        # model moved to a Dixon-Coles score grid, see soccer_ratings.odds)
        # but left in place rather than dropped, since existing rows may
        # still carry tuned values from before the migration.
        for col in (
            "elo_divisor",
            "draw_max",
            "draw_divisor",
            "draw_min",
            "weight_scale",
            "home_advantage",
            "rho",
            "home_goal_scale",
            "home_goal_rate",
            "away_goal_scale",
            "away_goal_rate",
            "temperature",
        ):
            cur.execute(f"ALTER TABLE leagues ADD COLUMN IF NOT EXISTS {col} DOUBLE PRECISION;")
        # Rows imported before this column existed keep a NULL capture time;
        # the backtest reports those as "unverifiable" rather than assuming
        # their ratings predate kickoff.
        cur.execute("ALTER TABLE matches ADD COLUMN IF NOT EXISTS rating_captured_at TIMESTAMPTZ;")
        conn.commit()


def import_country_rankings(database_url: str | None = None) -> dict:
    countries = fetch_rankings()
    with db_cursor(database_url, use_direct=True) as (conn, cur):
        imported = 0
        fetched_at = datetime.now(timezone.utc)
        for row in countries:
            country_id = _upsert_country(cur, row["country"], row.get("country_path"), row["rating"])
            cur.execute(
                """
                INSERT INTO rating_snapshots (scope, mode, country_id, ranking, rating, source_url, fetched_at)
                VALUES ('country', 'general', %s, %s, %s, %s, %s)
                """,
                (country_id, row["rank"], row["rating"], row.get("country_path"), fetched_at),
            )
            imported += 1
        conn.commit()
    return {"countries_imported": imported}


def import_league_ratings(country_url: str, database_url: str | None = None) -> dict:
    leagues = fetch_country_leagues(country_url)
    with db_cursor(database_url, use_direct=True) as (conn, cur):
        imported = 0
        team_snapshots_imported = 0
        fetched_at = datetime.now(timezone.utc)
        country_name = _country_name_from_path(country_url)
        country_id = _upsert_country(cur, country_name, country_url, None)
        for row in leagues:
            league_id = _upsert_league(
                cur,
                country_id=country_id,
                name=row["league"],
                league_path=row["league_path"],
                latest_rating=row["rating"],
            )
            cur.execute(
                """
                INSERT INTO rating_snapshots (scope, mode, country_id, league_id, ranking, rating, source_url, fetched_at)
                VALUES ('league', 'general', %s, %s, %s, %s, %s, %s)
                """,
                (
                    country_id,
                    league_id,
                    row["rank"],
                    row["rating"],
                    row["league_path"],
                    fetched_at,
                ),
            )
            imported += 1

            for mode in ("general", "home", "away"):
                team_rows = fetch_league_ratings(row["league_path"], mode=mode)
                for team_row in team_rows:
                    team_id = _upsert_team(cur, team_row["team"], team_row.get("team_path"))
                    cur.execute(
                        """
                        INSERT INTO rating_snapshots (
                            scope,
                            mode,
                            country_id,
                            league_id,
                            team_id,
                            ranking,
                            rating,
                            source_url,
                            fetched_at
                        )
                        VALUES ('team', %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            mode,
                            country_id,
                            league_id,
                            team_id,
                            team_row["rank"],
                            team_row["rating"],
                            team_row.get("team_path"),
                            fetched_at,
                        ),
                    )
                    team_snapshots_imported += 1
        conn.commit()
    return {
        "leagues_imported": imported,
        "team_snapshots_imported": team_snapshots_imported,
        "country_url": country_url,
    }


def import_league_history(league_url: str, database_url: str | None = None) -> dict:
    payload = fetch_league_history(league_url)
    with db_cursor(database_url, use_direct=True) as (conn, cur):
        league_id = _ensure_league_from_url(cur, payload["league_url"])
        team_ids: dict[str, int] = {}
        for team_meta in payload["teams"]:
            team_ids[team_meta["team"]] = _upsert_team(cur, team_meta["team"], team_meta.get("team_path"))

        imported_matches = 0
        for match in payload["matches"]:
            home_team_id = team_ids.get(match["home_team"]) or _upsert_team(
                cur, match["home_team"], None
            )
            away_team_id = team_ids.get(match["away_team"]) or _upsert_team(
                cur, match["away_team"], None
            )
            source_team_id = None
            if match.get("focal_team"):
                source_team_id = team_ids.get(match["focal_team"]) or _upsert_team(
                    cur, match["focal_team"], None
                )

            cur.execute(
                """
                INSERT INTO matches (
                    match_date,
                    competition,
                    home_team_id,
                    away_team_id,
                    home_odds,
                    draw_odds,
                    away_odds,
                    home_rating,
                    away_rating,
                    home_goals,
                    away_goals,
                    result_text,
                    source_team_id,
                    source_team_path,
                    rating_captured_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (match_date, competition, home_team_id, away_team_id)
                DO UPDATE SET
                    home_odds = EXCLUDED.home_odds,
                    draw_odds = EXCLUDED.draw_odds,
                    away_odds = EXCLUDED.away_odds,
                    home_rating = EXCLUDED.home_rating,
                    away_rating = EXCLUDED.away_rating,
                    home_goals = EXCLUDED.home_goals,
                    away_goals = EXCLUDED.away_goals,
                    result_text = EXCLUDED.result_text,
                    source_team_id = EXCLUDED.source_team_id,
                    source_team_path = EXCLUDED.source_team_path,
                    -- Re-stamped only when the ratings themselves change, so
                    -- an unrelated re-import (odds/result refresh) doesn't
                    -- make as-of-match ratings look retroactively written.
                    rating_captured_at = CASE
                        WHEN matches.home_rating IS DISTINCT FROM EXCLUDED.home_rating
                          OR matches.away_rating IS DISTINCT FROM EXCLUDED.away_rating
                        THEN NOW()
                        ELSE matches.rating_captured_at
                    END,
                    updated_at = NOW()
                """,
                (
                    _parse_match_date(match["date"]),
                    match["competition"],
                    home_team_id,
                    away_team_id,
                    match["home_odds"],
                    match["draw_odds"],
                    match["away_odds"],
                    match["home_rating"],
                    match["away_rating"],
                    match.get("home_goals"),
                    match.get("away_goals"),
                    match.get("result"),
                    source_team_id,
                    match.get("source_team_path"),
                ),
            )
            imported_matches += 1

        cur.execute(
            """
            INSERT INTO league_history_builds (league_id, raw_match_count, deduped_match_count, metadata)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (
                league_id,
                payload["raw_match_count"],
                payload["deduped_match_count"],
                "{}",
            ),
        )
        conn.commit()

    return {
        "league_url": payload["league_url"],
        "team_count": payload["team_count"],
        "matches_imported": imported_matches,
        "deduped_match_count": payload["deduped_match_count"],
        "failed_team_count": len(payload.get("failed_teams", [])),
        "failed_teams": payload.get("failed_teams", []),
    }


def import_country_history(
    country_url: str,
    database_url: str | None = None,
    *,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    leagues = fetch_country_leagues(country_url)
    total = len(leagues)
    results: list[dict] = []
    total_matches_imported = 0
    total_deduped_match_count = 0
    failures: list[dict] = []

    for index, league in enumerate(leagues, start=1):
        league_path = league.get("league_path")
        league_name = league.get("league") or league_path or ""

        if league_path:
            try:
                result = import_league_history(league_path, database_url)
                results.append(result)
                total_matches_imported += int(result.get("matches_imported", 0))
                total_deduped_match_count += int(result.get("deduped_match_count", 0))
            except Exception as exc:
                failures.append(
                    {
                        "league_url": league_path,
                        "league": league.get("league"),
                        "error": str(exc),
                    }
                )

        if on_progress:
            on_progress(index, total, league_name)

    return {
        "country_url": country_url,
        "leagues_processed": len(results),
        "matches_imported": total_matches_imported,
        "deduped_match_count": total_deduped_match_count,
        "failure_count": len(failures),
        "failures": failures,
        "leagues": results,
    }


def import_all_history(database_url: str | None = None) -> dict:
    countries = fetch_rankings()
    results: list[dict] = []
    total_leagues_processed = 0
    total_matches_imported = 0
    total_deduped_match_count = 0
    failures: list[dict] = []

    for country in countries:
        country_path = country.get("country_path")
        if not country_path:
            continue

        try:
            result = import_country_history(country_path, database_url)
            results.append(result)
            total_leagues_processed += int(result.get("leagues_processed", 0))
            total_matches_imported += int(result.get("matches_imported", 0))
            total_deduped_match_count += int(result.get("deduped_match_count", 0))
        except Exception as exc:
            failures.append(
                {
                    "country_url": country_path,
                    "country": country.get("country"),
                    "error": str(exc),
                }
            )

    return {
        "countries_processed": len(results),
        "leagues_processed": total_leagues_processed,
        "matches_imported": total_matches_imported,
        "deduped_match_count": total_deduped_match_count,
        "failure_count": len(failures),
        "failures": failures,
        "countries": results,
    }


def list_countries_with_imported_leagues(database_url: str | None = None) -> list[dict]:
    """Countries that already have at least one league imported.

    DB-only (no live scrape) so scheduled refresh jobs can discover what
    to re-import without crawling the whole site just to find out.
    """
    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            """
            SELECT DISTINCT c.country_path, c.name
            FROM countries c
            JOIN leagues l ON l.country_id = c.id
            WHERE c.country_path IS NOT NULL
            ORDER BY c.name ASC
            """
        )
        rows = cur.fetchall()
    return [{"country_path": row[0], "country": row[1]} for row in rows]


def refresh_known_history(database_url: str | None = None) -> dict:
    """Re-import history for every country already imported into Postgres.

    Meant for a scheduled/nightly job: unlike import_all_history (which
    crawls every ranked country on the source site), this only touches
    countries an operator has already imported via the CLI or /admin, so
    the scope grows naturally as more countries get imported instead of
    needing to be hardcoded anywhere.
    """
    countries = list_countries_with_imported_leagues(database_url)
    results: list[dict] = []
    total_leagues_processed = 0
    total_matches_imported = 0
    total_deduped_match_count = 0
    failures: list[dict] = []

    for country in countries:
        country_path = country["country_path"]
        try:
            result = import_country_history(country_path, database_url)
            results.append(result)
            total_leagues_processed += int(result.get("leagues_processed", 0))
            total_matches_imported += int(result.get("matches_imported", 0))
            total_deduped_match_count += int(result.get("deduped_match_count", 0))
        except Exception as exc:
            failures.append(
                {
                    "country_url": country_path,
                    "country": country.get("country"),
                    "error": str(exc),
                }
            )

    return {
        "countries_processed": len(results),
        "leagues_processed": total_leagues_processed,
        "matches_imported": total_matches_imported,
        "deduped_match_count": total_deduped_match_count,
        "failure_count": len(failures),
        "failures": failures,
        "countries": results,
    }


def list_all_imported_leagues(database_url: str | None = None) -> list[dict]:
    """Every league that has been imported (has a row in `leagues`), across
    all countries — DB-only, for global operations like the calibration
    sweep that need to touch every known league without crawling the
    source site to discover them.
    """
    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            """
            SELECT l.league_path, l.name, c.name
            FROM leagues l
            LEFT JOIN countries c ON c.id = l.country_id
            ORDER BY c.name ASC NULLS LAST, l.name ASC
            """
        )
        rows = cur.fetchall()
    return [{"league_path": row[0], "league": row[1], "country": row[2]} for row in rows]


def run_calibration_sweep(
    database_url: str | None = None,
    *,
    min_matches: int = DEFAULT_MIN_MATCHES,
    on_progress: Callable[[int, int, str], None] | None = None,
    persist: bool = True,
) -> dict:
    """Runs soccer_ratings.tuning's fit_league_model against every imported
    league's stored history — the goal curve, rho, and a recalibration
    temperature, continuously fit and validated on a held-out slice, for
    the exact pipeline soccer_ratings.backtest.evaluate_match runs —
    persists the fitted parameters, and rolls the per-league results up
    into a single across-leagues recommendation.

    This used to run soccer_ratings.tuning.sweep_league_parameters, a fixed
    grid (weight_scale x 3 home_advantage values x 5 rho values) evaluated
    against the *history-calibrated* model compare_teams_from_ratings uses,
    which isn't the model this app actually bets with — sweep_league_parameters
    is kept for that live-app history-calibration question (still reachable via
    the `tune-calibration` CLI command) but is no longer what keeps a league's
    stored tuning parameters up to date, since it was never fitting the thing
    being graded.
    """
    leagues = list_all_imported_leagues(database_url)
    total = len(leagues)
    league_fits: list[dict] = []

    for index, league in enumerate(leagues, start=1):
        league_path = league["league_path"]
        matches = load_league_history_matches(league_path, database_url)
        fit = fit_league_model(matches, min_matches=min_matches)

        fitted = fit.get("fitted")
        if fitted and persist:
            try:
                update_league_tuning_parameters(league_path, fitted, database_url)
            except Exception as exc:
                logger.warning(
                    "Failed to save fitted model parameters for %s (%s: %s)",
                    league_path,
                    type(exc).__name__,
                    exc,
                )

        league_fits.append(
            {
                "league": league["league"],
                "league_path": league_path,
                "country": league["country"],
                **fit,
            }
        )
        if on_progress:
            on_progress(index, total, league["league"] or league_path)

    evaluated = [row for row in league_fits if row["fitted"] is not None]
    skipped = [row for row in league_fits if row["fitted"] is None]

    summary = None
    if evaluated:
        rhos = sorted(row["fitted"]["rho"] for row in evaluated)
        count = len(rhos)
        median_rho = (
            rhos[count // 2]
            if count % 2 == 1
            else (rhos[count // 2 - 1] + rhos[count // 2]) / 2.0
        )

        # Out-of-sample, not the training Brier the old grid sweep compared —
        # "did the fit generalize" rather than "did it fit its own data".
        improvements = [
            row["validation"]["improvement"]
            for row in evaluated
            if row.get("validation") and row["validation"]["improvement"] is not None
        ]
        avg_brier_improvement = sum(improvements) / len(improvements) if improvements else None

        summary = {
            "leagues_evaluated": count,
            "leagues_with_validation": len(improvements),
            "median_rho": round(median_rho, 4),
            "avg_out_of_sample_brier_improvement_vs_default": (
                round(avg_brier_improvement, 4) if avg_brier_improvement is not None else None
            ),
        }

    return {
        "leagues_considered": total,
        "leagues_evaluated": len(evaluated),
        "leagues_skipped": len(skipped),
        "leagues": evaluated,
        "skipped_leagues": skipped,
        "summary": summary,
    }


def _compute_match_derived_fields(home_goals: int | None, away_goals: int | None) -> tuple[int | None, str | None, str | None]:
    if home_goals is None or away_goals is None:
        return None, None, None
    total_goals = home_goals + away_goals
    if home_goals > away_goals:
        winner = "home"
    elif home_goals < away_goals:
        winner = "away"
    else:
        winner = "draw"
    btts = "Y" if (home_goals > 0 and away_goals > 0) else "N"
    return total_goals, winner, btts


# One row per real fixture, chosen by the database rather than by luck of
# join order. Duplicate `teams` rows (same club, two team_paths) each spawn
# their own `matches` row — the matches unique constraint keys on team *id*,
# so it cannot see them as the same fixture — and every duplicate that
# reaches a backtest multiplies that match's stake, profit, and calibration
# weight. DISTINCT ON collapses them on normalized team *names* --
# lowercased, trimmed, and with internal whitespace runs collapsed, so the
# normalization matches matchkeys.normalize_name exactly. (btrim alone is
# not enough: it leaves "home   fc" distinct from "home fc".)
#
# The ORDER BY inside DISTINCT ON is the snapshot rule: prefer a settled
# result, then a usable price, then the most recently written row (the
# closest stand-in for closing odds the stored data offers).
_ONE_ROW_PER_FIXTURE_SELECT = r"""
            SELECT DISTINCT ON (
                m.match_date,
                m.competition,
                regexp_replace(lower(btrim(home_team.name)), '\s+', ' ', 'g'),
                regexp_replace(lower(btrim(away_team.name)), '\s+', ' ', 'g')
            )
                m.match_date,
                m.competition,
                home_team.name AS home_team,
                away_team.name AS away_team,
                m.home_odds,
                m.draw_odds,
                m.away_odds,
                m.home_rating,
                m.away_rating,
                m.home_goals,
                m.away_goals,
                m.rating_captured_at,
                m.id
            FROM matches m
            JOIN teams home_team ON home_team.id = m.home_team_id
            JOIN teams away_team ON away_team.id = m.away_team_id
"""

_ONE_ROW_PER_FIXTURE_ORDER = r"""
            ORDER BY
                m.match_date DESC,
                m.competition,
                regexp_replace(lower(btrim(home_team.name)), '\s+', ' ', 'g'),
                regexp_replace(lower(btrim(away_team.name)), '\s+', ' ', 'g'),
                (m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL) DESC,
                (m.home_odds > 0 AND m.draw_odds > 0 AND m.away_odds > 0) DESC,
                m.id DESC
"""


def _history_row_to_match(row) -> dict:
    """Shape one _ONE_ROW_PER_FIXTURE_SELECT row into the match dict the
    rest of the app consumes.
    """
    total_goals, winner, btts = _compute_match_derived_fields(row[9], row[10])
    return {
        "date": row[0].strftime("%d.%m.%y"),
        "competition": row[1],
        "home_team": row[2],
        "away_team": row[3],
        "home_odds": float(row[4]),
        "draw_odds": float(row[5]),
        "away_odds": float(row[6]),
        "home_rating": float(row[7]),
        "away_rating": float(row[8]),
        "home_goals": row[9],
        "away_goals": row[10],
        "result": f"{row[9]}-{row[10]}" if row[9] is not None and row[10] is not None else None,
        "total_goals": total_goals,
        "winner": winner,
        "btts?": btts,
        # Carried so the backtest can check the stored ratings predate
        # kickoff, and so any duplicate that still slips through is
        # collapsed deterministically rather than by list order.
        "rating_captured_at": row[11],
        "row_id": row[12],
    }


def load_league_history_matches(
    league_url: str,
    database_url: str | None = None,
    *,
    completed_only: bool = True,
) -> list[dict]:
    competition = league_code_from_url(league_url).upper()
    if not competition:
        return []

    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            f"""
            {_ONE_ROW_PER_FIXTURE_SELECT}
            WHERE m.competition = %s
              AND (%s::bool = FALSE OR (m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL))
            {_ONE_ROW_PER_FIXTURE_ORDER}
            """,
            (competition, completed_only),
        )
        rows = cur.fetchall()

    return [_history_row_to_match(row) for row in rows]


def load_all_history_matches(
    database_url: str | None = None,
    *,
    competition: str | None = None,
    completed_only: bool = True,
) -> list[dict]:
    comp_code = competition.upper() if competition else None
    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            f"""
            {_ONE_ROW_PER_FIXTURE_SELECT}
            WHERE (%s::text IS NULL OR m.competition = %s::text)
              AND (%s::bool = FALSE OR (m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL))
            {_ONE_ROW_PER_FIXTURE_ORDER}
            """,
            (comp_code, comp_code, completed_only),
        )
        rows = cur.fetchall()

    return [_history_row_to_match(row) for row in rows]


def matches_to_csv(matches: list[dict]) -> str:
    headers = [
        "Date",
        "Competition",
        "Home Team",
        "Away Team",
        "Home Goals",
        "Away Goals",
        "Total Goals",
        "Winner",
        "BTTS?",
        "Home Odds",
        "Draw Odds",
        "Away Odds",
        "Home Rating",
        "Away Rating",
    ]
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(headers)
    for m in matches:
        hg = m.get("home_goals")
        ag = m.get("away_goals")
        total_goals = m.get("total_goals")
        winner = m.get("winner")
        btts = m.get("btts?")
        if total_goals is None or winner is None or btts is None:
            calc_total, calc_winner, calc_btts = _compute_match_derived_fields(hg, ag)
            if total_goals is None:
                total_goals = calc_total
            if winner is None:
                winner = calc_winner
            if btts is None:
                btts = calc_btts

        writer.writerow([
            m.get("date", ""),
            m.get("competition", ""),
            m.get("home_team", ""),
            m.get("away_team", ""),
            hg if hg is not None else "",
            ag if ag is not None else "",
            total_goals if total_goals is not None else "",
            winner or "",
            btts or "",
            f"{m['home_odds']:.2f}" if m.get("home_odds") is not None else "",
            f"{m['draw_odds']:.2f}" if m.get("draw_odds") is not None else "",
            f"{m['away_odds']:.2f}" if m.get("away_odds") is not None else "",
            f"{m['home_rating']:.2f}" if m.get("home_rating") is not None else "",
            f"{m['away_rating']:.2f}" if m.get("away_rating") is not None else "",
        ])
    return output.getvalue()


def load_league_summary_stats(league_url: str, database_url: str | None = None) -> dict | None:
    competition = league_code_from_url(league_url).upper()
    if not competition:
        return None

    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL) AS match_count,
                AVG(home_goals + away_goals) FILTER (WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL) AS avg_goals,
                AVG(home_goals) FILTER (WHERE home_goals IS NOT NULL) AS avg_home_goals,
                AVG(away_goals) FILTER (WHERE away_goals IS NOT NULL) AS avg_away_goals,
                AVG(CASE WHEN home_goals > away_goals THEN 1.0 ELSE 0.0 END) FILTER (WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL) AS home_win_rate,
                AVG(CASE WHEN home_goals = away_goals THEN 1.0 ELSE 0.0 END) FILTER (WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL) AS draw_rate,
                AVG(CASE WHEN home_goals < away_goals THEN 1.0 ELSE 0.0 END) FILTER (WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL) AS away_win_rate
            FROM matches
            WHERE competition = %s
            """,
            (competition,),
        )
        row = cur.fetchone()

    if row is None or not row[0]:
        return None

    return {
        "matches": int(row[0]),
        "avg_goals": round(float(row[1]), 2) if row[1] is not None else 0.0,
        "avg_home_goals": round(float(row[2]), 2) if row[2] is not None else 0.0,
        "avg_away_goals": round(float(row[3]), 2) if row[3] is not None else 0.0,
        "home_win_pct": round(float(row[4]) * 100.0, 1) if row[4] is not None else 0.0,
        "draw_pct": round(float(row[5]) * 100.0, 1) if row[5] is not None else 0.0,
        "away_win_pct": round(float(row[6]) * 100.0, 1) if row[6] is not None else 0.0,
    }


def load_country_rankings(database_url: str | None = None) -> list[dict]:
    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            """
            SELECT country_path, name, latest_rating
            FROM countries
            WHERE country_path IS NOT NULL
            ORDER BY latest_rating DESC NULLS LAST, name ASC
            """
        )
        rows = cur.fetchall()

    results = []
    for index, row in enumerate(rows, start=1):
        results.append(
            {
                "rank": index,
                "country_path": row[0],
                "country": row[1],
                "rating": float(row[2]) if row[2] is not None else None,
            }
        )
    return results


def load_country_leagues(country_url: str, database_url: str | None = None) -> list[dict]:
    path = _path_from_url(country_url)
    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            """
            SELECT l.league_path, l.name, l.latest_rating
            FROM leagues l
            JOIN countries c ON c.id = l.country_id
            WHERE c.country_path = %s
            ORDER BY l.latest_rating DESC NULLS LAST, l.name ASC
            """,
            (path,),
        )
        rows = cur.fetchall()

    results = []
    for index, row in enumerate(rows, start=1):
        results.append(
            {
                "rank": index,
                "league_path": row[0],
                "league": row[1],
                "rating": float(row[2]) if row[2] is not None else None,
            }
        )
    return results


# Every column load_league_tuning_parameters can return and
# update_league_tuning_parameters can write. Two independent sweeps persist
# through this: sweep_league_parameters (weight_scale/home_advantage/rho,
# for the history-calibrated live-app model) and
# soccer_ratings.tuning.fit_league_model (the goal curve, rho, and
# temperature, for the model soccer_ratings.backtest.evaluate_match runs).
# Both call update_league_tuning_parameters with only the keys *they*
# computed — see its docstring for why that has to stay a partial update.
_TUNING_PARAM_COLUMNS = (
    "weight_scale",
    "home_advantage",
    "rho",
    "home_goal_scale",
    "home_goal_rate",
    "away_goal_scale",
    "away_goal_rate",
    "temperature",
)


def load_league_tuning_parameters(
    league_url: str,
    database_url: str | None = None,
) -> dict[str, float] | None:
    path = _path_from_url(league_url)
    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            f"""
            SELECT {", ".join(_TUNING_PARAM_COLUMNS)}
            FROM leagues
            WHERE league_path = %s
            """,
            (path,),
        )
        row = cur.fetchone()
        if not row:
            return None

        params = {}
        for key, val in zip(_TUNING_PARAM_COLUMNS, row):
            if val is not None:
                params[key] = float(val)
        return params


def update_league_tuning_parameters(
    league_url: str,
    params: dict[str, float],
    database_url: str | None = None,
) -> None:
    """Persist whichever of _TUNING_PARAM_COLUMNS are present in params,
    leaving every other tuning column exactly as stored.

    This has to be a partial update, not a full overwrite of all eight
    columns every time: sweep_league_parameters only ever computes
    weight_scale/home_advantage/rho, and fit_league_model only ever
    computes the goal curve/rho/temperature (home_advantage isn't
    identifiable jointly with a freely-fit curve — see its docstring — so
    it never appears in that dict at all). Whichever ran most recently
    would silently null out the other's columns if this issued a single
    UPDATE ... SET column = %s for all eight regardless of what params
    actually contains.
    """
    present_columns = [column for column in _TUNING_PARAM_COLUMNS if column in params]
    if not present_columns:
        return

    path = _path_from_url(league_url)
    set_clause = ", ".join(f"{column} = %s" for column in present_columns)
    values = [params[column] for column in present_columns]
    with db_cursor(database_url, use_direct=True) as (conn, cur):
        cur.execute(
            f"""
            UPDATE leagues
            SET {set_clause}, updated_at = NOW()
            WHERE league_path = %s
            """,
            (*values, path),
        )
        conn.commit()


def load_league_home_away_ratings(league_url: str, database_url: str | None = None) -> dict | None:
    path = _path_from_url(league_url)
    with db_cursor(database_url, use_direct=False) as (_, cur):
        cur.execute(
            """
            SELECT id, league_path
            FROM leagues
            WHERE league_path = %s
            """,
            (path,),
        )
        league_row = cur.fetchone()
        if league_row is None:
            return None

        league_id = league_row[0]
        payload = {"league_url": league_row[1]}
        fetched_at = None
        for mode in ("home", "away", "general"):
            cur.execute(
                """
                SELECT t.name, t.team_path, rs.ranking, rs.rating, rs.fetched_at
                FROM rating_snapshots rs
                JOIN teams t ON t.id = rs.team_id
                WHERE rs.scope = 'team'
                  AND rs.league_id = %s
                  AND rs.mode = %s
                  -- Only the most recent import batch: rows from one import
                  -- share a single fetched_at, and older batches may contain
                  -- teams that have since left the league.
                  AND rs.fetched_at = (
                      SELECT MAX(rs2.fetched_at)
                      FROM rating_snapshots rs2
                      WHERE rs2.scope = 'team'
                        AND rs2.league_id = rs.league_id
                        AND rs2.mode = rs.mode
                  )
                ORDER BY rs.fetched_at DESC, rs.ranking ASC
                """,
                (league_id, mode),
            )
            rows = cur.fetchall()
            deduped_rows: list[dict] = []
            seen_team_ids: set[tuple[str, str | None]] = set()
            for row in rows:
                team_key = (row[0], row[1])
                if team_key in seen_team_ids:
                    continue
                seen_team_ids.add(team_key)
                deduped_rows.append(
                    {
                        "team": row[0],
                        "team_path": row[1],
                        "rank": row[2],
                        "rating": float(row[3]),
                        "mode": mode,
                    }
                )
            payload[mode] = deduped_rows
            # Rows are ordered fetched_at DESC, so the first row (if any) is
            # this mode's freshest snapshot timestamp.
            if rows and rows[0][4] is not None:
                fetched_at = rows[0][4] if fetched_at is None else max(fetched_at, rows[0][4])
        payload["fetched_at"] = fetched_at

    if not payload.get("home") or not payload.get("away"):
        return None
    return payload


def _upsert_country(cur, name: str, country_path: str | None, latest_rating: float | None) -> int:
    cur.execute(
        """
        INSERT INTO countries (name, country_path, latest_rating)
        VALUES (%s, %s, %s)
        ON CONFLICT (name)
        DO UPDATE SET
            country_path = COALESCE(EXCLUDED.country_path, countries.country_path),
            latest_rating = COALESCE(EXCLUDED.latest_rating, countries.latest_rating),
            updated_at = NOW()
        RETURNING id
        """,
        (name, country_path, latest_rating),
    )
    return cur.fetchone()[0]


def _upsert_league(cur, country_id: int | None, name: str, league_path: str, latest_rating: float | None) -> int:
    cur.execute(
        """
        INSERT INTO leagues (country_id, name, league_path, latest_rating)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (league_path)
        DO UPDATE SET
            country_id = COALESCE(EXCLUDED.country_id, leagues.country_id),
            name = EXCLUDED.name,
            latest_rating = COALESCE(EXCLUDED.latest_rating, leagues.latest_rating),
            updated_at = NOW()
        RETURNING id
        """,
        (country_id, name, league_path, latest_rating),
    )
    return cur.fetchone()[0]


def _upsert_team(cur, name: str, team_path: str | None) -> int:
    if team_path:
        cur.execute(
            """
            INSERT INTO teams (name, team_path)
            VALUES (%s, %s)
            ON CONFLICT (team_path)
            DO UPDATE SET
                name = EXCLUDED.name,
                updated_at = NOW()
            RETURNING id
            """,
            (name, team_path),
        )
        return cur.fetchone()[0]

    # No discovered team_path — this is common for historical opponents
    # outside the league's own roster (e.g. a relegated/promoted team).
    # NULL never equals NULL under the team_path UNIQUE constraint, so
    # ON CONFLICT (team_path) would never fire here and every import would
    # mint a fresh row for the same team name, which then cascades into
    # duplicate match rows (see merge_duplicate_teams, which cleans up
    # rows created by this bug before this fix). Look the team up by name
    # instead so repeated imports reuse the same row.
    cur.execute("SELECT id FROM teams WHERE name = %s AND team_path IS NULL", (name,))
    row = cur.fetchone()
    if row is not None:
        cur.execute("UPDATE teams SET updated_at = NOW() WHERE id = %s", (row[0],))
        return row[0]

    cur.execute(
        "INSERT INTO teams (name, team_path) VALUES (%s, NULL) RETURNING id",
        (name,),
    )
    return cur.fetchone()[0]


def merge_duplicate_teams(database_url: str | None = None) -> dict:
    """One-off cleanup for the duplicate rows _upsert_team's old NULL-path
    bug produced: every re-import minted a fresh teams row for any team
    seen without a discovered team_path (typically historical opponents
    outside a league's own roster), which then cascaded into duplicate
    match rows once the "same" fixture pointed at two different team ids.

    Collapses those duplicate team rows down to one per name (preferring
    a row that actually has a team_path, else the oldest row), repoints
    matches/rating_snapshots at the surviving row, drops the match rows
    that become exact duplicates once both sides are remapped (keeping
    the most recently touched copy of each fixture), and finally deletes
    the now-orphaned team rows. Safe to run repeatedly — a database with
    no duplicates is a no-op.
    """
    with db_cursor(database_url, use_direct=True) as (conn, cur):
        cur.execute(
            """
            CREATE TEMP TABLE team_merge_map AS
            SELECT dupe.id AS dupe_id, canonical.id AS canonical_id
            FROM (
                SELECT id, name,
                       ROW_NUMBER() OVER (
                           PARTITION BY name
                           ORDER BY (team_path IS NOT NULL) DESC, id ASC
                       ) AS rn
                FROM teams
            ) dupe
            JOIN (
                SELECT id, name,
                       ROW_NUMBER() OVER (
                           PARTITION BY name
                           ORDER BY (team_path IS NOT NULL) DESC, id ASC
                       ) AS rn
                FROM teams
            ) canonical ON canonical.name = dupe.name AND canonical.rn = 1
            WHERE dupe.rn > 1
            """
        )
        cur.execute("SELECT COUNT(*) FROM team_merge_map")
        (duplicate_team_count,) = cur.fetchone()

        if duplicate_team_count == 0:
            cur.execute("DROP TABLE team_merge_map")
            conn.commit()
            return {"teams_merged": 0, "matches_removed": 0}

        # Drop match rows that would collide once both sides are remapped
        # onto their canonical team id, keeping the most recently touched
        # copy of each fixture (highest id).
        cur.execute(
            """
            WITH mapped AS (
                SELECT
                    m.id,
                    m.match_date,
                    m.competition,
                    COALESCE(mh.canonical_id, m.home_team_id) AS mapped_home,
                    COALESCE(ma.canonical_id, m.away_team_id) AS mapped_away
                FROM matches m
                LEFT JOIN team_merge_map mh ON mh.dupe_id = m.home_team_id
                LEFT JOIN team_merge_map ma ON ma.dupe_id = m.away_team_id
            ),
            ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY match_date, competition, mapped_home, mapped_away
                           ORDER BY id DESC
                       ) AS rn
                FROM mapped
            )
            DELETE FROM matches WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
        matches_removed = cur.rowcount

        cur.execute(
            """
            UPDATE matches m
            SET home_team_id = map.canonical_id, updated_at = NOW()
            FROM team_merge_map map
            WHERE m.home_team_id = map.dupe_id
            """
        )
        cur.execute(
            """
            UPDATE matches m
            SET away_team_id = map.canonical_id, updated_at = NOW()
            FROM team_merge_map map
            WHERE m.away_team_id = map.dupe_id
            """
        )
        cur.execute(
            """
            UPDATE matches m
            SET source_team_id = map.canonical_id, updated_at = NOW()
            FROM team_merge_map map
            WHERE m.source_team_id = map.dupe_id
            """
        )
        cur.execute(
            """
            UPDATE rating_snapshots rs
            SET team_id = map.canonical_id
            FROM team_merge_map map
            WHERE rs.team_id = map.dupe_id
            """
        )

        cur.execute("DELETE FROM teams WHERE id IN (SELECT dupe_id FROM team_merge_map)")
        teams_merged = cur.rowcount

        cur.execute("DROP TABLE team_merge_map")
        conn.commit()

    return {"teams_merged": teams_merged, "matches_removed": matches_removed}


def _ensure_league_from_url(cur, league_url: str) -> int:
    path = _path_from_url(league_url)
    inferred_country = _country_name_from_path(path)
    country_id = _upsert_country(cur, inferred_country, f"/{inferred_country.replace(' ', '-')}/", None)
    league_name = path.strip("/").split("/")[-1] or inferred_country
    return _upsert_league(cur, country_id, league_name, path, None)


def _path_from_url(url_or_path: str) -> str:
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        parts = url_or_path.split("/", 3)
        return "/" + parts[3] if len(parts) > 3 else "/"
    return url_or_path


def _country_name_from_path(country_url: str) -> str:
    path = _path_from_url(country_url).strip("/")
    if not path:
        return "Unknown"
    first_segment = path.split("/")[0]
    return first_segment.replace("-", " ")


def _parse_match_date(value: str):
    return datetime.strptime(value, "%d.%m.%y").date()


def load_sitemap_metadata(database_url: str | None = None) -> dict[str, datetime]:
    """Query country and league paths mapped to their latest updated_at times from the DB."""
    metadata = {}
    try:
        with db_cursor(database_url, use_direct=False) as (_, cur):
            cur.execute("SELECT country_path, updated_at FROM countries WHERE country_path IS NOT NULL")
            for row in cur.fetchall():
                metadata[row[0]] = row[1]
            cur.execute("SELECT league_path, updated_at FROM leagues WHERE league_path IS NOT NULL")
            for row in cur.fetchall():
                metadata[row[0]] = row[1]
    except Exception as exc:
        logger.warning("Failed to load sitemap metadata from DB: %s", exc)
    return metadata


def get_weekly_rating_movers(database_url: str | None = None, limit: int = 10) -> dict:
    """Find the largest positive and negative Elo rating changes over the past 7 days."""
    climbers = []
    sliders = []

    query = """
    WITH latest_snapshots AS (
        SELECT DISTINCT ON (team_id)
            team_id,
            rating AS latest_rating,
            fetched_at AS latest_fetched_at,
            league_id
        FROM rating_snapshots
        WHERE scope = 'team' AND mode = 'general'
        ORDER BY team_id, fetched_at DESC
    ),
    past_snapshots AS (
        SELECT DISTINCT ON (team_id)
            team_id,
            rating AS past_rating,
            fetched_at AS past_fetched_at
        FROM rating_snapshots
        WHERE scope = 'team' AND mode = 'general'
          AND fetched_at <= NOW() - INTERVAL '6 days'
        ORDER BY team_id, fetched_at DESC
    )
    SELECT 
        t.name, 
        t.team_path,
        l.name AS league_name,
        l.league_path,
        c.name AS country_name,
        ls.latest_rating,
        ps.past_rating,
        (ls.latest_rating - ps.past_rating) AS rating_change
    FROM latest_snapshots ls
    JOIN past_snapshots ps ON ls.team_id = ps.team_id
    JOIN teams t ON t.id = ls.team_id
    LEFT JOIN leagues l ON l.id = ls.league_id
    LEFT JOIN countries c ON c.id = t.country_id
    """

    try:
        with db_cursor(database_url, use_direct=False) as (_, cur):
            # Get climbers (positive rating changes)
            cur.execute(
                query + " WHERE (ls.latest_rating - ps.past_rating) > 0 ORDER BY rating_change DESC LIMIT %s",
                (limit,),
            )
            for row in cur.fetchall():
                climbers.append(
                    {
                        "team": row[0],
                        "team_path": row[1],
                        "league": row[2],
                        "league_path": row[3],
                        "country": row[4],
                        "latest_rating": row[5],
                        "past_rating": row[6],
                        "change": round(row[7], 2),
                    }
                )

            # Get sliders (negative rating changes)
            cur.execute(
                query + " WHERE (ls.latest_rating - ps.past_rating) < 0 ORDER BY rating_change ASC LIMIT %s",
                (limit,),
            )
            for row in cur.fetchall():
                sliders.append(
                    {
                        "team": row[0],
                        "team_path": row[1],
                        "league": row[2],
                        "league_path": row[3],
                        "country": row[4],
                        "latest_rating": row[5],
                        "past_rating": row[6],
                        "change": round(row[7], 2),
                    }
                )
    except Exception as exc:
        logger.warning("Failed to load weekly rating movers from DB: %s", exc)

    return {"climbers": climbers, "sliders": sliders}


def get_model_accuracy_summary(database_url: str | None = None) -> dict:
    """Calculate overall model prediction accuracy stats and fetch top-performing tuned leagues."""
    evaluated_count = 0
    correct_predictions = 0
    total_brier = 0.0

    query = """
    SELECT
        m.home_rating,
        m.away_rating,
        m.home_goals,
        m.away_goals,
        l.home_advantage,
        l.rho
    FROM matches m
    JOIN teams t ON t.id = m.home_team_id
    LEFT JOIN leagues l ON (
        l.league_path LIKE '%/' || m.competition || '/' 
        OR l.league_path LIKE '%/' || m.competition
    )
    WHERE m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL
    """

    from .odds import DEFAULT_RHO, calculate_match_probabilities

    def brier_score(probabilities: dict[str, float], outcome: str) -> float:
        return sum(
            (probabilities[key] - (1.0 if key == outcome else 0.0)) ** 2 for key in ("home", "draw", "away")
        )

    try:
        with db_cursor(database_url, use_direct=False) as (_, cur):
            cur.execute(query)
            rows = cur.fetchall()

            for row in rows:
                home_rating = float(row[0])
                away_rating = float(row[1])
                home_goals = int(row[2])
                away_goals = int(row[3])

                # Use tuned parameters if available, else defaults
                home_advantage = float(row[4]) if row[4] is not None else 0.0
                rho = float(row[5]) if row[5] is not None else DEFAULT_RHO

                probs = calculate_match_probabilities(
                    home_rating,
                    away_rating,
                    home_advantage=home_advantage,
                    rho=rho,
                )

                # Determine outcome
                if home_goals > away_goals:
                    outcome = "home"
                elif home_goals < away_goals:
                    outcome = "away"
                else:
                    outcome = "draw"

                # Prediction is the outcome with the highest probability
                pred = max(probs, key=probs.get)
                if pred == outcome:
                    correct_predictions += 1

                brier = brier_score(probs, outcome)
                total_brier += brier
                evaluated_count += 1
    except Exception as exc:
        logger.warning("Failed to calculate model accuracy summary: %s", exc)

    accuracy = (correct_predictions / evaluated_count) if evaluated_count > 0 else 0.0
    avg_brier = (total_brier / evaluated_count) if evaluated_count > 0 else 0.0

    tuned_leagues = []
    try:
        with db_cursor(database_url, use_direct=False) as (_, cur):
            cur.execute(
                """
                SELECT l.name, c.name, l.league_path, l.weight_scale, l.home_advantage, l.rho
                FROM leagues l
                JOIN countries c ON c.id = l.country_id
                WHERE l.weight_scale IS NOT NULL
                ORDER BY l.updated_at DESC
                LIMIT 5
                """
            )
            for row in cur.fetchall():
                tuned_leagues.append(
                    {
                        "name": row[0],
                        "country": row[1],
                        "league_path": row[2],
                        "weight_scale": row[3],
                        "home_advantage": row[4],
                        "rho": row[5],
                    }
                )
    except Exception as exc:
        logger.warning("Failed to load tuned leagues list: %s", exc)

    return {
        "accuracy": round(accuracy * 100, 1),
        "avg_brier": round(avg_brier, 4),
        "total_evaluated": evaluated_count,
        "tuned_leagues": tuned_leagues,
    }


