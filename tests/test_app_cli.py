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


if __name__ == "__main__":
    unittest.main()
