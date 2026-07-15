import unittest

from soccer_ratings.matchhistory import build_form_guide, build_head_to_head


def make_match(**overrides) -> dict:
    match = {
        "date": "01.02.23",
        "competition": "UK1",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "home_odds": 1.9,
        "draw_odds": 3.4,
        "away_odds": 4.0,
        "home_goals": 2,
        "away_goals": 1,
        "result": "2:1",
    }
    match.update(overrides)
    return match


class BuildHeadToHeadTests(unittest.TestCase):
    def test_returns_none_when_teams_never_met(self) -> None:
        matches = [make_match(home_team="Arsenal", away_team="Fulham")]
        self.assertIsNone(build_head_to_head(matches, "Arsenal", "Chelsea"))

    def test_matches_pairing_regardless_of_venue(self) -> None:
        matches = [
            make_match(date="01.01.22", home_team="Arsenal", away_team="Chelsea", home_goals=2, away_goals=1),
            make_match(date="01.01.21", home_team="Chelsea", away_team="Arsenal", home_goals=0, away_goals=0),
            make_match(date="01.01.20", home_team="Fulham", away_team="Everton"),
        ]
        result = build_head_to_head(matches, "Arsenal", "Chelsea")

        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["wins"], 1)
        self.assertEqual(result["draws"], 1)
        self.assertEqual(result["losses"], 0)

    def test_record_is_from_selected_home_team_perspective(self) -> None:
        matches = [
            # Chelsea (selected away team) wins as home side.
            make_match(date="01.01.22", home_team="Chelsea", away_team="Arsenal", home_goals=3, away_goals=0),
        ]
        result = build_head_to_head(matches, "Arsenal", "Chelsea")

        self.assertEqual(result["losses"], 1)
        self.assertEqual(result["wins"], 0)
        self.assertEqual(result["avg_goals_for"], 0.0)
        self.assertEqual(result["avg_goals_against"], 3.0)

    def test_sorted_most_recent_first_and_respects_limit(self) -> None:
        matches = [
            make_match(date="01.01.20"),
            make_match(date="01.01.23"),
            make_match(date="01.01.22"),
            make_match(date="01.01.21"),
        ]
        result = build_head_to_head(matches, "Arsenal", "Chelsea", limit=2)

        self.assertEqual(result["sample_size"], 2)
        self.assertEqual([m["date"] for m in result["matches"]], ["01.01.23", "01.01.22"])

    def test_case_and_whitespace_insensitive(self) -> None:
        matches = [make_match(home_team=" arsenal ", away_team="CHELSEA")]
        result = build_head_to_head(matches, "Arsenal", "Chelsea")
        self.assertIsNotNone(result)

    def test_unplayed_meeting_included_but_excluded_from_record(self) -> None:
        matches = [
            make_match(date="01.01.23", home_goals=None, away_goals=None, result=None),
            make_match(date="01.01.22", home_goals=1, away_goals=1),
        ]
        result = build_head_to_head(matches, "Arsenal", "Chelsea")

        self.assertEqual(result["sample_size"], 2)
        self.assertEqual(result["draws"], 1)
        self.assertEqual(result["wins"] + result["draws"] + result["losses"], 1)


class BuildFormGuideTests(unittest.TestCase):
    def test_returns_none_when_team_has_no_matches(self) -> None:
        matches = [make_match(home_team="Fulham", away_team="Everton")]
        self.assertIsNone(build_form_guide(matches, "Arsenal"))

    def test_computes_result_and_venue_for_home_and_away_matches(self) -> None:
        matches = [
            make_match(date="02.01.23", home_team="Arsenal", away_team="Chelsea", home_goals=2, away_goals=1),
            make_match(date="01.01.23", home_team="Fulham", away_team="Arsenal", home_goals=0, away_goals=3),
        ]
        result = build_form_guide(matches, "Arsenal")

        self.assertEqual(result["sample_size"], 2)
        home_entry = next(m for m in result["matches"] if m["date"] == "02.01.23")
        away_entry = next(m for m in result["matches"] if m["date"] == "01.01.23")
        self.assertEqual(home_entry, {
            "date": "02.01.23", "opponent": "Chelsea", "venue": "H",
            "goals_for": 2, "goals_against": 1, "result": "W",
        })
        self.assertEqual(away_entry, {
            "date": "01.01.23", "opponent": "Fulham", "venue": "A",
            "goals_for": 3, "goals_against": 0, "result": "W",
        })
        self.assertEqual(result["wins"], 2)
        self.assertEqual(result["form_string"], "WW")

    def test_most_recent_first_and_limit(self) -> None:
        matches = [
            make_match(date="01.01.20", home_goals=1, away_goals=0),
            make_match(date="01.01.23", home_goals=0, away_goals=1),
            make_match(date="01.01.22", home_goals=1, away_goals=1),
            make_match(date="01.01.21", home_goals=2, away_goals=0),
        ]
        result = build_form_guide(matches, "Arsenal", limit=2)

        self.assertEqual(result["sample_size"], 2)
        self.assertEqual([m["date"] for m in result["matches"]], ["01.01.23", "01.01.22"])
        # Arsenal is home in every fixture: loss then draw, most-recent-first.
        self.assertEqual(result["form_string"], "LD")

    def test_excludes_unplayed_fixtures(self) -> None:
        matches = [
            make_match(date="01.01.23", home_goals=None, away_goals=None, result=None),
            make_match(date="01.01.22", home_goals=1, away_goals=0),
        ]
        result = build_form_guide(matches, "Arsenal")

        self.assertEqual(result["sample_size"], 1)
        self.assertEqual(result["matches"][0]["date"], "01.01.22")

    def test_goal_averages(self) -> None:
        matches = [
            make_match(date="01.01.23", home_team="Arsenal", away_team="Chelsea", home_goals=3, away_goals=1),
            make_match(date="02.01.23", home_team="Fulham", away_team="Arsenal", home_goals=0, away_goals=1),
        ]
        result = build_form_guide(matches, "Arsenal")

        self.assertEqual(result["goals_for"], 4)
        self.assertEqual(result["goals_against"], 1)
        self.assertEqual(result["avg_goals_for"], 2.0)
        self.assertEqual(result["avg_goals_against"], 0.5)


if __name__ == "__main__":
    unittest.main()
