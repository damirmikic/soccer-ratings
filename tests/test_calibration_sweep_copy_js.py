import json
import shutil
import subprocess
import unittest
from pathlib import Path

APP_JS_PATH = Path(__file__).resolve().parent.parent / "soccer_ratings" / "static" / "app.js"

# Minimal DOM stubs so app.js's top-level addEventListener calls don't throw
# when executed outside a browser; buildCalibrationSweepSummaryText is a pure
# function with no DOM dependency, so this is enough to exercise it.
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

const result = JSON.parse(process.argv[2]);
console.log(JSON.stringify({ text: buildCalibrationSweepSummaryText(result) }));
"""


@unittest.skipUnless(shutil.which("node"), "node is not available in this environment")
class BuildCalibrationSweepSummaryTextTests(unittest.TestCase):
    def _run(self, result) -> str:
        proc = subprocess.run(
            ["node", "-e", _NODE_HARNESS, "--", str(APP_JS_PATH), json.dumps(result)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)["text"]

    def test_header_and_counts_line(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 3,
                "leagues_considered": 4,
                "leagues_skipped": 1,
                "leagues": [],
                "skipped_leagues": [],
                "summary": None,
            }
        )
        lines = text.split("\n")
        self.assertEqual(lines[0], "Calibration Sweep Results")
        self.assertEqual(lines[1], "Evaluated: 3 of 4 leagues (1 skipped)")

    def test_omits_skipped_suffix_when_zero(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 2,
                "leagues_considered": 2,
                "leagues_skipped": 0,
                "leagues": [],
                "skipped_leagues": [],
                "summary": None,
            }
        )
        self.assertIn("Evaluated: 2 of 2 leagues\n", text)
        self.assertNotIn("skipped)", text)

    def test_summary_lines_present_when_summary_given(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 2,
                "leagues_considered": 2,
                "leagues_skipped": 0,
                "leagues": [],
                "skipped_leagues": [],
                "summary": {"median_best_weight_scale": 1.25, "avg_brier_improvement_vs_default": 0.0203},
            }
        )
        self.assertIn("Median Best Weight Scale: 1.25", text)
        self.assertIn("Avg Brier Improvement vs Default: 0.0203", text)

    def test_summary_improvement_dash_when_none(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 1,
                "leagues_considered": 1,
                "leagues_skipped": 0,
                "leagues": [],
                "skipped_leagues": [],
                "summary": {"median_best_weight_scale": 1.0, "avg_brier_improvement_vs_default": None},
            }
        )
        self.assertIn("Avg Brier Improvement vs Default: -", text)

    def test_league_rows_are_tab_separated(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 1,
                "leagues_considered": 1,
                "leagues_skipped": 0,
                "leagues": [
                    {
                        "country": "England",
                        "league": "Premier League",
                        "league_path": "/England/Premier-League/",
                        "matches_available": 620,
                        "best": {"weight_scale": 1.5, "avg_brier": 0.512},
                        "default_avg_brier": 0.548,
                    }
                ],
                "skipped_leagues": [],
                "summary": None,
            }
        )
        lines = text.split("\n")
        self.assertIn("Country\tLeague\tMatches\tBest Scale\tBest Brier\tDefault (1.0) Brier", lines)
        self.assertIn("England\tPremier League\t620\t1.5\t0.5120\t0.5480", lines)

    def test_league_row_falls_back_to_league_path_and_dash_country(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 1,
                "leagues_considered": 1,
                "leagues_skipped": 0,
                "leagues": [
                    {
                        "country": None,
                        "league": None,
                        "league_path": "/Spain/La-Liga/",
                        "matches_available": 100,
                        "best": {"weight_scale": 1.0, "avg_brier": 0.55},
                        "default_avg_brier": None,
                    }
                ],
                "skipped_leagues": [],
                "summary": None,
            }
        )
        self.assertIn("-\t/Spain/La-Liga/\t100\t1\t0.5500\t-", text)

    def test_no_leagues_evaluated_shows_placeholder(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 0,
                "leagues_considered": 2,
                "leagues_skipped": 2,
                "leagues": [],
                "skipped_leagues": [],
                "summary": None,
            }
        )
        self.assertIn("No league had enough imported history to evaluate.", text)

    def test_skipped_leagues_listed_with_min_matches(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 1,
                "leagues_considered": 2,
                "leagues_skipped": 1,
                "leagues": [
                    {
                        "country": "England",
                        "league": "Premier League",
                        "matches_available": 620,
                        "best": {"weight_scale": 1.0, "avg_brier": 0.55},
                        "default_avg_brier": 0.55,
                    }
                ],
                "skipped_leagues": [
                    {"league": "Tercera Division", "league_path": "/Spain/Tercera/", "min_matches_required": 30}
                ],
                "summary": None,
            }
        )
        self.assertIn("Skipped (fewer than 30 matches): Tercera Division", text)

    def test_no_skipped_line_when_none_skipped(self) -> None:
        text = self._run(
            {
                "leagues_evaluated": 1,
                "leagues_considered": 1,
                "leagues_skipped": 0,
                "leagues": [
                    {
                        "country": "England",
                        "league": "Premier League",
                        "matches_available": 620,
                        "best": {"weight_scale": 1.0, "avg_brier": 0.55},
                        "default_avg_brier": 0.55,
                    }
                ],
                "skipped_leagues": [],
                "summary": None,
            }
        )
        self.assertNotIn("Skipped", text)


if __name__ == "__main__":
    unittest.main()
