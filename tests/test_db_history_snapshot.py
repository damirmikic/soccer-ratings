import unittest
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest import mock

from soccer_ratings.db import (
    _history_row_to_match,
    load_all_history_matches,
    load_league_history_matches,
)


class _HistoryCursor:
    """Fake cursor that records the SQL it was handed and replays canned
    rows, so the query's *shape* can be asserted without a live Postgres.
    """

    def __init__(self, rows=()):
        self._rows = list(rows)
        self.queries: list[str] = []

    def execute(self, query, params=None):
        self.queries.append(" ".join(query.split()))

    def fetchall(self):
        return self._rows


@contextmanager
def _fake_cursor(cur):
    yield (None, cur)


def make_row(
    match_date=date(2023, 2, 1),
    competition="UK1",
    home_team="Home FC",
    away_team="Away FC",
    home_odds=1.8,
    draw_odds=3.6,
    away_odds=4.5,
    home_rating=2200.0,
    away_rating=2000.0,
    home_goals=2,
    away_goals=1,
    rating_captured_at=None,
    row_id=1,
):
    return (
        match_date,
        competition,
        home_team,
        away_team,
        home_odds,
        draw_odds,
        away_odds,
        home_rating,
        away_rating,
        home_goals,
        away_goals,
        rating_captured_at,
        row_id,
    )


class HistoryRowMappingTests(unittest.TestCase):
    def test_maps_columns_including_provenance_fields(self) -> None:
        captured = datetime(2023, 1, 30, tzinfo=timezone.utc)
        match = _history_row_to_match(make_row(rating_captured_at=captured, row_id=77))

        self.assertEqual(match["date"], "01.02.23")
        self.assertEqual(match["home_team"], "Home FC")
        self.assertEqual(match["result"], "2-1")
        self.assertEqual(match["rating_captured_at"], captured)
        self.assertEqual(match["row_id"], 77)

    def test_unplayed_match_has_no_result(self) -> None:
        match = _history_row_to_match(make_row(home_goals=None, away_goals=None))

        self.assertIsNone(match["result"])


class OneRowPerFixtureQueryTests(unittest.TestCase):
    """Duplicate `teams` rows spawn duplicate `matches` rows for one real
    fixture (the unique constraint keys on team id, not name), so the query
    itself has to pick a single row deterministically.
    """

    def _run(self, loader):
        cur = _HistoryCursor(rows=[make_row()])
        with mock.patch(
            "soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)
        ):
            matches = loader()
        return cur.queries[0], matches

    def test_league_query_is_distinct_on_normalized_team_names(self) -> None:
        query, _ = self._run(lambda: load_league_history_matches("/England/Premier-League/"))

        self.assertIn("SELECT DISTINCT ON", query)
        self.assertIn("lower(btrim(home_team.name))", query)
        self.assertIn("lower(btrim(away_team.name))", query)

    def test_team_name_normalization_collapses_internal_whitespace(self) -> None:
        # btrim alone only strips the *ends*, so "  home   fc " stayed
        # distinct from "Home FC" and the duplicate survived — verified
        # against a real Postgres before this regexp was added. The SQL
        # normalization has to match matchkeys.normalize_name, which
        # collapses internal runs too.
        query, _ = self._run(lambda: load_league_history_matches("/England/Premier-League/"))

        self.assertIn(r"regexp_replace(lower(btrim(home_team.name)), '\s+', ' ', 'g')", query)
        self.assertIn(r"regexp_replace(lower(btrim(away_team.name)), '\s+', ' ', 'g')", query)

    def test_league_query_prefers_settled_priced_and_newest_rows(self) -> None:
        query, _ = self._run(lambda: load_league_history_matches("/England/Premier-League/"))

        # The snapshot rule, in order: settled result, usable price, newest.
        self.assertIn("(m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL) DESC", query)
        self.assertIn("(m.home_odds > 0 AND m.draw_odds > 0 AND m.away_odds > 0) DESC", query)
        self.assertIn("m.id DESC", query)

    def test_league_query_selects_provenance_columns(self) -> None:
        query, matches = self._run(lambda: load_league_history_matches("/England/Premier-League/"))

        self.assertIn("m.rating_captured_at", query)
        self.assertIn("row_id", matches[0])

    def test_all_history_query_uses_the_same_shape(self) -> None:
        query, _ = self._run(lambda: load_all_history_matches(competition="UK1"))

        self.assertIn("SELECT DISTINCT ON", query)
        self.assertIn("lower(btrim(home_team.name))", query)
        self.assertIn("m.rating_captured_at", query)

    def test_unknown_league_short_circuits_without_querying(self) -> None:
        cur = _HistoryCursor()
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)):
            matches = load_league_history_matches("")

        self.assertEqual(matches, [])
        self.assertEqual(cur.queries, [])


class RatingCaptureStampTests(unittest.TestCase):
    def test_schema_declares_the_capture_column(self) -> None:
        from soccer_ratings.db import SCHEMA_PATH

        schema = SCHEMA_PATH.read_text(encoding="utf-8")

        self.assertIn("rating_captured_at TIMESTAMPTZ", schema)


if __name__ == "__main__":
    unittest.main()
