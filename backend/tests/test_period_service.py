"""Natural-period boundary contracts for learning reports and the dashboard."""

import unittest
from datetime import date, datetime, timedelta, timezone

from app.services.period_service import InvalidTimezone, daily_buckets, period_bounds, previous_period


class PeriodServiceTests(unittest.TestCase):
    def test_shanghai_day_bounds_convert_to_utc(self):
        bounds = period_bounds("day", date(2026, 9, 15), "Asia/Shanghai")
        self.assertEqual(bounds.utc_start, datetime(2026, 9, 14, 16, tzinfo=timezone.utc))
        self.assertEqual(bounds.utc_end, datetime(2026, 9, 15, 16, tzinfo=timezone.utc))

    def test_week_starts_on_monday_and_previous_week_is_complete(self):
        bounds = period_bounds("week", date(2026, 9, 16), "Asia/Shanghai")
        previous = previous_period(bounds)
        self.assertEqual(bounds.local_start.date(), date(2026, 9, 14))
        self.assertEqual(bounds.local_end.date(), date(2026, 9, 21))
        self.assertEqual(previous.local_start.date(), date(2026, 9, 7))
        self.assertEqual(previous.local_end.date(), date(2026, 9, 14))

    def test_month_uses_calendar_boundaries_and_daily_buckets(self):
        bounds = period_bounds("month", date(2026, 2, 18), "Asia/Shanghai")
        self.assertEqual(bounds.local_start.date(), date(2026, 2, 1))
        self.assertEqual(bounds.local_end.date(), date(2026, 3, 1))
        buckets = daily_buckets(bounds)
        self.assertEqual((buckets[0], buckets[-1], len(buckets)), (date(2026, 2, 1), date(2026, 2, 28), 28))

    def test_new_york_spring_dst_day_has_23_hours(self):
        bounds = period_bounds("day", date(2026, 3, 8), "America/New_York")
        self.assertEqual(bounds.utc_end - bounds.utc_start, timedelta(hours=23))

    def test_invalid_timezone_is_rejected(self):
        with self.assertRaises(InvalidTimezone):
            period_bounds("day", date(2026, 9, 15), "Mars/Olympus")


if __name__ == "__main__":
    unittest.main()
