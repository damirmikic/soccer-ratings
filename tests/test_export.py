import io
import json
import sys
import unittest
from unittest import mock

import app
from fastapi.testclient import TestClient
from soccer_ratings.dashboard import create_dashboard_app
from soccer_ratings.db import matches_to_csv


class ExportTests(unittest.TestCase):
    def test_matches_to_csv(self) -> None:
        matches = [
            {
                "date": "15.07.26",
                "competition": "UK1",
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "home_goals": 2,
                "away_goals": 1,
                "home_odds": 2.10,
                "draw_odds": 3.40,
                "away_odds": 3.50,
                "home_rating": 1500.0,
                "away_rating": 1450.0,
            }
        ]
        csv_str = matches_to_csv(matches)
        lines = csv_str.split("\r\n")
        self.assertEqual(
            lines[0],
            "Date,Competition,Home Team,Away Team,Home Goals,Away Goals,Total Goals,Winner,BTTS?,Home Odds,Draw Odds,Away Odds,Home Rating,Away Rating",
        )
        self.assertIn("15.07.26,UK1,Arsenal,Chelsea,2,1,3,home,Y,2.10,3.40,3.50,1500.00,1450.00", lines[1])

    def test_cli_export_history_csv(self) -> None:
        mock_matches = [{"date": "10.05.26", "competition": "UK1", "home_team": "A", "away_team": "B", "home_odds": 2.0}]
        with mock.patch.object(sys, "argv", ["app.py", "export-history", "--format", "csv"]), mock.patch(
            "app.load_all_history_matches", return_value=mock_matches
        ) as mock_load, mock.patch("sys.stdout.buffer.write") as mock_write:
            exit_code = app.main()

        self.assertEqual(exit_code, 0)
        mock_load.assert_called_once()
        printed = mock_write.call_args[0][0].decode("utf-8")
        self.assertIn("Date,Competition,Home Team", printed)
        self.assertIn("10.05.26,UK1,A,B", printed)

    def test_cli_export_history_json(self) -> None:
        mock_matches = [{"date": "10.05.26", "competition": "UK1", "home_team": "A", "away_team": "B"}]
        with mock.patch.object(sys, "argv", ["app.py", "export-history", "--format", "json"]), mock.patch(
            "app.load_all_history_matches", return_value=mock_matches
        ) as mock_load, mock.patch("builtins.print") as mock_print:
            exit_code = app.main()

        self.assertEqual(exit_code, 0)
        printed = mock_print.call_args[0][0]
        data = json.loads(printed)
        self.assertEqual(data["match_count"], 1)
        self.assertEqual(data["matches"], mock_matches)

    def test_api_history_export_endpoint_csv(self) -> None:
        webapp = create_dashboard_app()
        client = TestClient(webapp)
        with mock.patch.object(
            webapp.state.services,
            "export_history_matches",
            return_value=[{"date": "12.03.26", "competition": "ES1", "home_team": "Real", "away_team": "Barca", "home_odds": 2.25}],
        ):
            resp = client.get("/api/history/export?format=csv")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers["content-type"], "text/csv; charset=utf-8")
            self.assertIn("Date,Competition,Home Team", resp.text)
            self.assertIn("Real,Barca", resp.text)

    def test_api_history_export_endpoint_json(self) -> None:
        webapp = create_dashboard_app()
        client = TestClient(webapp)
        with mock.patch.object(
            webapp.state.services,
            "export_history_matches",
            return_value=[{"date": "12.03.26", "competition": "ES1", "home_team": "Real", "away_team": "Barca"}],
        ):
            resp = client.get("/api/history/export?format=json&league_url=/Spain/La-Liga/")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("application/json", resp.headers["content-type"])
            self.assertIn("history-Spain-La-Liga.json", resp.headers["content-disposition"])
            data = resp.json()
            self.assertEqual(data["match_count"], 1)
            self.assertEqual(data["matches"][0]["home_team"], "Real")


if __name__ == "__main__":
    unittest.main()
