import json
import sys
import unittest
from unittest import mock

import app


class RefreshKnownHistoryCliTests(unittest.TestCase):
    def test_parses_with_no_required_arguments(self) -> None:
        args = app.build_parser().parse_args(["refresh-known-history"])
        self.assertEqual(args.command, "refresh-known-history")
        self.assertIsNone(args.database_url)

    def test_parses_optional_database_url(self) -> None:
        args = app.build_parser().parse_args(
            ["refresh-known-history", "--database-url", "postgresql://x"]
        )
        self.assertEqual(args.database_url, "postgresql://x")

    def test_main_dispatches_to_refresh_known_history_and_prints_json(self) -> None:
        with mock.patch.object(sys, "argv", ["app.py", "refresh-known-history"]), mock.patch(
            "app.refresh_known_history", return_value={"countries_processed": 2}
        ) as mock_refresh:
            exit_code = app.main()

        self.assertEqual(exit_code, 0)
        mock_refresh.assert_called_once_with(None)

    def test_main_passes_database_url_through(self) -> None:
        with mock.patch.object(
            sys, "argv", ["app.py", "refresh-known-history", "--database-url", "postgresql://x"]
        ), mock.patch("app.refresh_known_history", return_value={}) as mock_refresh:
            app.main()

        mock_refresh.assert_called_once_with("postgresql://x")

    def test_main_prints_json_payload(self) -> None:
        with mock.patch.object(sys, "argv", ["app.py", "refresh-known-history"]), mock.patch(
            "app.refresh_known_history", return_value={"countries_processed": 3}
        ):
            with mock.patch("builtins.print") as mock_print:
                app.main()

        printed = mock_print.call_args[0][0]
        self.assertEqual(json.loads(printed), {"countries_processed": 3})


class FitModelCliTests(unittest.TestCase):
    def test_parses_required_league_url(self) -> None:
        args = app.build_parser().parse_args(["fit-model", "--league-url", "/England/UK1/"])
        self.assertEqual(args.command, "fit-model")
        self.assertEqual(args.league_url, "/England/UK1/")
        self.assertEqual(args.min_matches, 30)
        self.assertFalse(args.persist)

    def test_main_dispatches_to_fit_league_model(self) -> None:
        with mock.patch.object(
            sys, "argv", ["app.py", "fit-model", "--league-url", "/England/UK1/"]
        ), mock.patch("app.load_league_history_matches", return_value=[]) as mock_load, mock.patch(
            "app.fit_league_model", return_value={"fitted": None, "validation": None}
        ) as mock_fit:
            exit_code = app.main()

        self.assertEqual(exit_code, 0)
        mock_load.assert_called_once_with("/England/UK1/", None)
        mock_fit.assert_called_once_with([], min_matches=30)

    def test_persist_flag_saves_fitted_parameters(self) -> None:
        fitted = {"rho": -0.1, "home_goal_scale": 1.5}
        with mock.patch.object(
            sys, "argv", ["app.py", "fit-model", "--league-url", "/England/UK1/", "--persist"]
        ), mock.patch("app.load_league_history_matches", return_value=[]), mock.patch(
            "app.fit_league_model", return_value={"fitted": fitted, "validation": None}
        ), mock.patch("app.update_league_tuning_parameters") as mock_update:
            app.main()

        mock_update.assert_called_once_with("/England/UK1/", fitted, None)

    def test_persist_flag_is_a_no_op_when_the_fit_is_unavailable(self) -> None:
        with mock.patch.object(
            sys, "argv", ["app.py", "fit-model", "--league-url", "/England/UK1/", "--persist"]
        ), mock.patch("app.load_league_history_matches", return_value=[]), mock.patch(
            "app.fit_league_model", return_value={"fitted": None, "validation": None}
        ), mock.patch("app.update_league_tuning_parameters") as mock_update:
            app.main()

        mock_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
