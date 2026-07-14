import unittest
from datetime import datetime, timedelta, timezone

from soccer_ratings.timeutil import format_relative_time

_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)


class FormatRelativeTimeTests(unittest.TestCase):
    def test_none_returns_empty_string(self) -> None:
        self.assertEqual(format_relative_time(None), "")

    def test_under_a_minute_is_just_now(self) -> None:
        moment = _NOW - timedelta(seconds=30)
        self.assertEqual(format_relative_time(moment, now=_NOW), "just now")

    def test_minutes_ago(self) -> None:
        moment = _NOW - timedelta(minutes=5)
        self.assertEqual(format_relative_time(moment, now=_NOW), "5m ago")

    def test_hours_ago(self) -> None:
        moment = _NOW - timedelta(hours=3, minutes=10)
        self.assertEqual(format_relative_time(moment, now=_NOW), "3h ago")

    def test_days_ago(self) -> None:
        moment = _NOW - timedelta(days=2)
        self.assertEqual(format_relative_time(moment, now=_NOW), "2d ago")

    def test_weeks_ago(self) -> None:
        moment = _NOW - timedelta(days=10)
        self.assertEqual(format_relative_time(moment, now=_NOW), "1w ago")

    def test_months_ago(self) -> None:
        moment = _NOW - timedelta(days=100)
        self.assertEqual(format_relative_time(moment, now=_NOW), "3mo ago")

    def test_years_ago(self) -> None:
        moment = _NOW - timedelta(days=800)
        self.assertEqual(format_relative_time(moment, now=_NOW), "2y ago")

    def test_naive_datetime_is_treated_as_utc(self) -> None:
        moment = (_NOW - timedelta(hours=1)).replace(tzinfo=None)
        self.assertEqual(format_relative_time(moment, now=_NOW), "1h ago")

    def test_future_moment_clamped_to_just_now(self) -> None:
        moment = _NOW + timedelta(minutes=5)
        self.assertEqual(format_relative_time(moment, now=_NOW), "just now")


if __name__ == "__main__":
    unittest.main()
