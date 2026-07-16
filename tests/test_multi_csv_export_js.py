import json
import shutil
import subprocess
import unittest
from pathlib import Path

APP_JS_PATH = Path(__file__).resolve().parent.parent / "soccer_ratings" / "static" / "app.js"

# Minimal DOM stubs so app.js's top-level addEventListener calls don't throw
# when executed outside a browser; buildMultiRowsCsv/slugifyLeagueUrl are
# pure functions with no DOM dependency, so this is enough to exercise them.
_NODE_HARNESS = """
global.document = {
  addEventListener: () => {},
  getElementById: () => null,
  createElement: () => ({ style: {}, click: () => {}, remove: () => {} }),
  body: { appendChild: () => {}, removeChild: () => {} },
  querySelectorAll: () => [],
};
global.window = global;
global.HTMLSelectElement = class {};

const fs = require("fs");
eval(fs.readFileSync(process.argv[1], "utf8"));

const rows = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  csv: buildMultiRowsCsv(rows),
  slug: slugifyLeagueUrl(process.argv[3]),
}));
"""


@unittest.skipUnless(shutil.which("node"), "node is not available in this environment")
class BuildMultiRowsCsvTests(unittest.TestCase):
    def _run(self, rows, league_url="/England/Premier-League/") -> dict:
        result = subprocess.run(
            ["node", "-e", _NODE_HARNESS, "--", str(APP_JS_PATH), json.dumps(rows), league_url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_skips_fully_blank_rows(self) -> None:
        output = self._run([{"homeTeam": "", "awayTeam": "", "status": "pending", "odds": None}])
        lines = output["csv"].split("\r\n")
        self.assertEqual(len(lines), 1)  # header only, blank row dropped

    def test_header_row(self) -> None:
        output = self._run([])
        self.assertEqual(
            output["csv"],
            "Home Team,Away Team,1,X,2,DNB 1,DNB 2,O2.5,U2.5,BTTS Y,BTTS N",
        )

    def test_formats_ready_row_with_two_decimal_odds(self) -> None:
        row = {
            "homeTeam": "Arsenal",
            "awayTeam": "Chelsea",
            "status": "ready",
            "odds": {
                "1": 1.8,
                "X": 3.5,
                "2": 4.2,
                "DNB1": 1.4,
                "DNB2": 2.8,
                "O25": 1.9,
                "U25": 1.95,
                "BTTSY": 1.7,
                "BTTSN": 2.1,
            },
        }
        output = self._run([row])
        lines = output["csv"].split("\r\n")
        self.assertEqual(lines[1], "Arsenal,Chelsea,1.80,3.50,4.20,1.40,2.80,1.90,1.95,1.70,2.10")

    def test_partial_row_with_missing_odds_uses_dash(self) -> None:
        row = {"homeTeam": "Liverpool", "awayTeam": "", "status": "pending", "odds": None}
        output = self._run([row])
        lines = output["csv"].split("\r\n")
        self.assertEqual(lines[1], "Liverpool,,-,-,-,-,-,-,-,-,-")

    def test_escapes_commas_and_quotes_in_team_names(self) -> None:
        row = {
            "homeTeam": "Man City, FC",
            "awayTeam": 'Spurs "The"',
            "status": "pending",
            "odds": None,
        }
        output = self._run([row])
        lines = output["csv"].split("\r\n")
        self.assertEqual(
            lines[1],
            '"Man City, FC","Spurs ""The""",-,-,-,-,-,-,-,-,-',
        )

    def test_loading_and_error_rows_show_placeholder(self) -> None:
        output = self._run(
            [
                {"homeTeam": "A", "awayTeam": "B", "status": "loading", "odds": None},
                {"homeTeam": "C", "awayTeam": "D", "status": "error", "odds": None},
            ]
        )
        lines = output["csv"].split("\r\n")
        self.assertTrue(lines[1].startswith("A,B,…,…,…"))
        self.assertTrue(lines[2].startswith("C,D,Err,Err,Err"))

    def test_slugify_league_url(self) -> None:
        output = self._run([], league_url="/England/Premier-League/")
        self.assertEqual(output["slug"], "England-Premier-League")

    def test_slugify_empty_url_falls_back_to_league(self) -> None:
        output = self._run([], league_url="")
        self.assertEqual(output["slug"], "league")


if __name__ == "__main__":
    unittest.main()
