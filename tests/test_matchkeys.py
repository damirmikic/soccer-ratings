import unittest
from datetime import datetime, timezone

from soccer_ratings.matchkeys import (
    chronological_key,
    dedupe_matches,
    match_identity_key,
    normalize_name,
    sort_matches_by_date,
)


def make_row(**overrides) -> dict:
    row = {
        "date": "01.02.23",
        "competition": "UK1",
        "home_team": "Home FC",
        "away_team": "Away FC",
        "home_odds": 1.8,
        "draw_odds": 3.6,
        "away_odds": 4.5,
        "home_rating": 2200.0,
        "away_rating": 2000.0,
        "home_goals": 2,
        "away_goals": 1,
    }
    row.update(overrides)
    return row


class NormalizeNameTests(unittest.TestCase):
    def test_collapses_case_and_whitespace(self) -> None:
        self.assertEqual(normalize_name("  Arsenal   FC "), normalize_name("arsenal fc"))

    def test_none_becomes_empty(self) -> None:
        self.assertEqual(normalize_name(None), "")


class ChronologicalKeyTests(unittest.TestCase):
    def test_orders_across_mixed_date_formats(self) -> None:
        # The old string-reordering key sorted every ISO date before every
        # dotted one regardless of when they actually happened.
        dates = ["2023-06-01", "01.02.23", "15.12.24", "2022-01-01"]
        ordered = sorted(dates, key=chronological_key)

        self.assertEqual(ordered, ["2022-01-01", "01.02.23", "2023-06-01", "15.12.24"])

    def test_unparseable_dates_sort_first_and_stay_deterministic(self) -> None:
        ordered = sorted(["01.02.23", "not-a-date", "01.01.20"], key=chronological_key)

        self.assertEqual(ordered[0], "not-a-date")
        self.assertEqual(ordered[1:], ["01.01.20", "01.02.23"])

    def test_two_digit_and_four_digit_years_agree(self) -> None:
        self.assertEqual(chronological_key("01.02.23"), chronological_key("01.02.2023"))


class SortMatchesByDateTests(unittest.TestCase):
    def test_ascending_by_default_and_reversible(self) -> None:
        matches = [make_row(date="15.12.24"), make_row(date="01.02.23"), make_row(date="2023-06-01")]

        ascending = [row["date"] for row in sort_matches_by_date(matches)]
        descending = [row["date"] for row in sort_matches_by_date(matches, reverse=True)]

        self.assertEqual(ascending, ["01.02.23", "2023-06-01", "15.12.24"])
        self.assertEqual(descending, list(reversed(ascending)))

    def test_same_date_ties_break_stably_on_teams(self) -> None:
        matches = [
            make_row(home_team="Zed FC"),
            make_row(home_team="Alpha FC"),
            make_row(home_team="Mid FC"),
        ]

        ordered = [row["home_team"] for row in sort_matches_by_date(matches)]

        self.assertEqual(ordered, ["Alpha FC", "Mid FC", "Zed FC"])


class MatchIdentityKeyTests(unittest.TestCase):
    def test_same_fixture_despite_name_formatting(self) -> None:
        self.assertEqual(
            match_identity_key(make_row(home_team="Home FC", away_team="Away FC")),
            match_identity_key(make_row(home_team=" home   fc ", away_team="AWAY FC")),
        )

    def test_same_fixture_despite_date_format(self) -> None:
        self.assertEqual(
            match_identity_key(make_row(date="01.02.23")),
            match_identity_key(make_row(date="2023-02-01")),
        )

    def test_reversed_fixture_is_a_different_match(self) -> None:
        self.assertNotEqual(
            match_identity_key(make_row(home_team="A", away_team="B")),
            match_identity_key(make_row(home_team="B", away_team="A")),
        )


class DedupeMatchesTests(unittest.TestCase):
    def test_collapses_repeats_and_counts_them(self) -> None:
        deduped, dropped = dedupe_matches([make_row(), make_row(), make_row()])

        self.assertEqual(len(deduped), 1)
        self.assertEqual(dropped, 2)

    def test_distinct_fixtures_are_kept(self) -> None:
        deduped, dropped = dedupe_matches(
            [make_row(home_team="A"), make_row(home_team="B"), make_row(date="02.02.23")]
        )

        self.assertEqual(len(deduped), 3)
        self.assertEqual(dropped, 0)

    def test_prefers_the_settled_result_over_an_unplayed_row(self) -> None:
        unplayed = make_row(home_goals=None, away_goals=None, row_id=99)
        settled = make_row(home_goals=3, away_goals=0, row_id=1)

        deduped, dropped = dedupe_matches([unplayed, settled])

        self.assertEqual(dropped, 1)
        self.assertEqual(deduped[0]["home_goals"], 3)

    def test_prefers_usable_odds_over_missing_ones(self) -> None:
        broken = make_row(home_odds=0.0, row_id=99)
        usable = make_row(home_odds=1.95, row_id=1)

        deduped, _ = dedupe_matches([broken, usable])

        self.assertEqual(deduped[0]["home_odds"], 1.95)

    def test_breaks_remaining_ties_on_the_newest_row(self) -> None:
        older = make_row(home_odds=1.5, row_id=10)
        newer = make_row(home_odds=2.5, row_id=42)

        # Order of arrival must not decide the winner.
        for arrival in ([older, newer], [newer, older]):
            deduped, _ = dedupe_matches(arrival)
            self.assertEqual(deduped[0]["home_odds"], 2.5)

    def test_output_is_chronological_oldest_first(self) -> None:
        deduped, _ = dedupe_matches(
            [make_row(date="15.12.24"), make_row(date="01.02.23"), make_row(date="01.02.23")]
        )

        self.assertEqual([row["date"] for row in deduped], ["01.02.23", "15.12.24"])

    def test_empty_input(self) -> None:
        self.assertEqual(dedupe_matches([]), ([], 0))

    def test_rows_without_row_id_are_handled(self) -> None:
        # Cached-scrape rows carry no row_id; first seen should win rather
        # than raising on the missing key.
        deduped, dropped = dedupe_matches([make_row(home_odds=1.5), make_row(home_odds=2.5)])

        self.assertEqual(dropped, 1)
        self.assertEqual(deduped[0]["home_odds"], 1.5)


if __name__ == "__main__":
    unittest.main()
