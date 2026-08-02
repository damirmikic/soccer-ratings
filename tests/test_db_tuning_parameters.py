import unittest
from contextlib import contextmanager
from unittest import mock

from soccer_ratings.db import (
    _TUNING_PARAM_COLUMNS,
    load_league_tuning_parameters,
    update_league_tuning_parameters,
)


class _FetchOneCursor:
    def __init__(self, row):
        self._row = row
        self.queries: list[str] = []
        self.params: list = []

    def execute(self, query, params=None):
        self.queries.append(" ".join(query.split()))
        self.params.append(params)

    def fetchone(self):
        return self._row


@contextmanager
def _fake_cursor(cur, conn=None):
    yield (conn or mock.Mock(), cur)


class LoadLeagueTuningParametersTests(unittest.TestCase):
    def test_selects_every_tuning_column(self) -> None:
        cur = _FetchOneCursor(row=(1.5, 60.0, -0.1, 1.4, 700.0, 1.0, 800.0, 0.9))
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)):
            params = load_league_tuning_parameters("/England/Premier-League/")

        for column in _TUNING_PARAM_COLUMNS:
            self.assertIn(column, cur.queries[0])
        self.assertEqual(
            params,
            {
                "weight_scale": 1.5,
                "home_advantage": 60.0,
                "rho": -0.1,
                "home_goal_scale": 1.4,
                "home_goal_rate": 700.0,
                "away_goal_scale": 1.0,
                "away_goal_rate": 800.0,
                "temperature": 0.9,
            },
        )

    def test_null_columns_are_omitted_not_returned_as_none(self) -> None:
        # Only weight_scale/home_advantage/rho tuned (e.g. by
        # sweep_league_parameters); the goal-curve/temperature columns
        # haven't been fit yet and should be absent, not present-as-None —
        # callers default missing keys themselves (see evaluate_match).
        cur = _FetchOneCursor(row=(1.5, 60.0, -0.1, None, None, None, None, None))
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)):
            params = load_league_tuning_parameters("/England/Premier-League/")

        self.assertEqual(params, {"weight_scale": 1.5, "home_advantage": 60.0, "rho": -0.1})

    def test_returns_none_for_an_unknown_league(self) -> None:
        cur = _FetchOneCursor(row=None)
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)):
            params = load_league_tuning_parameters("/Nowhere/Nothing/")

        self.assertIsNone(params)


class UpdateLeagueTuningParametersTests(unittest.TestCase):
    def test_only_writes_the_columns_present_in_params(self) -> None:
        # sweep_league_parameters's output shape: weight_scale/home_advantage/rho
        # only. The goal-curve/temperature columns must not be touched —
        # writing them as NULL here would clobber whatever fit_league_model
        # had previously stored.
        cur = _FetchOneCursor(row=None)
        conn = mock.Mock()
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur, conn)):
            update_league_tuning_parameters(
                "/England/Premier-League/",
                {"weight_scale": 2.0, "home_advantage": 60.0, "rho": -0.1},
            )

        query = cur.queries[0]
        self.assertIn("weight_scale = %s", query)
        self.assertIn("home_advantage = %s", query)
        self.assertIn("rho = %s", query)
        self.assertNotIn("home_goal_scale", query)
        self.assertNotIn("temperature", query)
        self.assertEqual(cur.params[0], (2.0, 60.0, -0.1, "/England/Premier-League/"))
        conn.commit.assert_called_once()

    def test_fit_league_model_shape_only_writes_its_own_columns(self) -> None:
        # fit_league_model's output: the goal curve, rho, and temperature —
        # never weight_scale, and home_advantage is always present but
        # always 0.0 (see fit_league_model's docstring). Confirms the other
        # side of the same partial-update contract as the test above.
        cur = _FetchOneCursor(row=None)
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)):
            update_league_tuning_parameters(
                "/England/Premier-League/",
                {
                    "home_advantage": 0.0,
                    "rho": -0.08,
                    "temperature": 0.92,
                    "home_goal_scale": 1.5,
                    "home_goal_rate": 700.0,
                    "away_goal_scale": 1.0,
                    "away_goal_rate": 800.0,
                },
            )

        query = cur.queries[0]
        self.assertNotIn("weight_scale", query)
        self.assertIn("home_goal_scale = %s", query)
        self.assertIn("temperature = %s", query)

    def test_empty_params_does_not_touch_the_database(self) -> None:
        cur = _FetchOneCursor(row=None)
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)) as patched:
            update_league_tuning_parameters("/England/Premier-League/", {})

        self.assertEqual(cur.queries, [])

    def test_ignores_keys_outside_the_known_tuning_columns(self) -> None:
        cur = _FetchOneCursor(row=None)
        with mock.patch("soccer_ratings.db.db_cursor", lambda *a, **k: _fake_cursor(cur)):
            update_league_tuning_parameters(
                "/England/Premier-League/",
                {"rho": -0.1, "matches_evaluated": 500, "avg_brier": 0.5},
            )

        query = cur.queries[0]
        self.assertIn("rho = %s", query)
        self.assertNotIn("matches_evaluated", query)
        self.assertNotIn("avg_brier", query)
        self.assertEqual(cur.params[0], (-0.1, "/England/Premier-League/"))


if __name__ == "__main__":
    unittest.main()
