import unittest
from contextlib import contextmanager
from unittest import mock

from soccer_ratings.db import _upsert_team, merge_duplicate_teams


class _UpsertCursor:
    """Records queries and replays a scripted sequence of fetchone() results,
    so tests can assert both what SQL ran and what _upsert_team returns for
    it — without a real Postgres connection.
    """

    def __init__(self, fetchone_results):
        self._fetchone_results = list(fetchone_results)
        self.queries: list[str] = []

    def execute(self, query, params=None):
        self.queries.append(" ".join(query.split()))

    def fetchone(self):
        return self._fetchone_results.pop(0) if self._fetchone_results else None


class UpsertTeamTests(unittest.TestCase):
    def test_with_team_path_uses_on_conflict_upsert(self) -> None:
        cur = _UpsertCursor(fetchone_results=[(42,)])

        team_id = _upsert_team(cur, "Arsenal FC", "/England/Arsenal/")

        self.assertEqual(team_id, 42)
        self.assertEqual(len(cur.queries), 1)
        self.assertIn("ON CONFLICT (team_path)", cur.queries[0])

    def test_without_team_path_reuses_existing_row_by_name(self) -> None:
        # SELECT finds an existing NULL-path row for this name.
        cur = _UpsertCursor(fetchone_results=[(7,)])

        team_id = _upsert_team(cur, "Leicester City", None)

        self.assertEqual(team_id, 7)
        self.assertEqual(len(cur.queries), 2)
        self.assertIn("SELECT id FROM teams WHERE name", cur.queries[0])
        self.assertIn("team_path IS NULL", cur.queries[0])
        self.assertIn("UPDATE teams", cur.queries[1])
        # No fresh INSERT should have happened.
        self.assertFalse(any("INSERT INTO teams" in q for q in cur.queries))

    def test_without_team_path_inserts_when_no_existing_row(self) -> None:
        # SELECT finds nothing, so a single fresh row is inserted.
        cur = _UpsertCursor(fetchone_results=[None, (9,)])

        team_id = _upsert_team(cur, "Ipswich Town", None)

        self.assertEqual(team_id, 9)
        self.assertEqual(len(cur.queries), 2)
        self.assertIn("SELECT id FROM teams WHERE name", cur.queries[0])
        self.assertIn("INSERT INTO teams", cur.queries[1])

    def test_repeated_calls_for_the_same_null_path_team_reuse_one_row(self) -> None:
        # First call inserts (no existing row); second call must find and
        # reuse it rather than minting a second row for the same name —
        # this is the exact bug merge_duplicate_teams cleans up after.
        cur = _UpsertCursor(fetchone_results=[None, (9,), (9,)])

        first_id = _upsert_team(cur, "Ipswich Town", None)
        second_id = _upsert_team(cur, "Ipswich Town", None)

        self.assertEqual(first_id, second_id)


class _MergeCursor:
    """Fake cursor for merge_duplicate_teams: reacts to specific queries by
    query prefix rather than call order, since exact statement order is an
    implementation detail the tests shouldn't be coupled to.
    """

    def __init__(self, duplicate_team_count: int, matches_removed: int, teams_merged: int):
        self._duplicate_team_count = duplicate_team_count
        self._matches_removed = matches_removed
        self._teams_merged = teams_merged
        self.rowcount = 0
        self.queries: list[str] = []
        self._last_result = None

    def execute(self, query, params=None):
        q = " ".join(query.split())
        self.queries.append(q)
        if q.startswith("SELECT COUNT(*) FROM team_merge_map"):
            self._last_result = (self._duplicate_team_count,)
        elif "DELETE FROM matches" in q:
            self.rowcount = self._matches_removed
        elif q.startswith("DELETE FROM teams"):
            self.rowcount = self._teams_merged
        else:
            self.rowcount = 0

    def fetchone(self):
        return self._last_result


def _fake_db_cursor(cursor):
    @contextmanager
    def db_cursor(*args, **kwargs):
        yield (mock.Mock(), cursor)

    return db_cursor


class MergeDuplicateTeamsTests(unittest.TestCase):
    def test_no_duplicates_is_a_no_op(self) -> None:
        cur = _MergeCursor(duplicate_team_count=0, matches_removed=0, teams_merged=0)

        with mock.patch("soccer_ratings.db.db_cursor", _fake_db_cursor(cur)):
            result = merge_duplicate_teams()

        self.assertEqual(result, {"teams_merged": 0, "matches_removed": 0})
        # Should bail out right after counting — no DELETE/UPDATE statements.
        self.assertFalse(any(q.startswith("DELETE FROM matches") for q in cur.queries))
        self.assertFalse(any(q.startswith("UPDATE matches") for q in cur.queries))
        self.assertFalse(any(q.startswith("DELETE FROM teams") for q in cur.queries))

    def test_duplicates_are_merged_and_reported(self) -> None:
        cur = _MergeCursor(duplicate_team_count=3, matches_removed=5, teams_merged=3)

        with mock.patch("soccer_ratings.db.db_cursor", _fake_db_cursor(cur)):
            result = merge_duplicate_teams()

        self.assertEqual(result, {"teams_merged": 3, "matches_removed": 5})
        # Matches must be remapped onto the canonical team before the
        # duplicate team rows are deleted (ON DELETE CASCADE would wipe
        # out any match still pointing at a row deleted first).
        delete_matches_index = next(i for i, q in enumerate(cur.queries) if "DELETE FROM matches" in q)
        delete_teams_index = next(i for i, q in enumerate(cur.queries) if q.startswith("DELETE FROM teams"))
        self.assertLess(delete_matches_index, delete_teams_index)
        self.assertTrue(any(q.startswith("UPDATE matches") and "home_team_id" in q for q in cur.queries))
        self.assertTrue(any(q.startswith("UPDATE matches") and "away_team_id" in q for q in cur.queries))
        self.assertTrue(any(q.startswith("UPDATE rating_snapshots") for q in cur.queries))


if __name__ == "__main__":
    unittest.main()
