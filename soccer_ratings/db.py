from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .client import fetch_country_leagues, fetch_league_history, fetch_league_home_away_ratings, fetch_rankings
from .env import load_env_file

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
    with connect(database_url, use_direct=use_direct) as conn:
        with conn.cursor() as cur:
            yield conn, cur


def init_db(database_url: str | None = None) -> None:
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with db_cursor(database_url, use_direct=False) as (conn, cur):
        cur.execute(schema_sql)
        conn.commit()


def import_country_rankings(database_url: str | None = None) -> dict:
    countries = fetch_rankings()
    with db_cursor(database_url, use_direct=True) as (conn, cur):
        imported = 0
        fetched_at = datetime.utcnow()
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
        fetched_at = datetime.utcnow()
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
        conn.commit()
    return {"leagues_imported": imported, "country_url": country_url}


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
                    source_team_path
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    }


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
