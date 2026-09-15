"""Timezone-aware natural period calculations shared by dashboards and reports."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PeriodType = Literal["day", "week", "month"]


class InvalidTimezone(ValueError):
    """Raised when an IANA timezone name cannot be loaded."""


@dataclass(frozen=True)
class PeriodBounds:
    period_type: PeriodType
    timezone_name: str
    local_start: datetime
    local_end: datetime
    utc_start: datetime
    utc_end: datetime


def _month_after(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1, day=1)
    return value.replace(month=value.month + 1, day=1)


def period_bounds(period_type: PeriodType, anchor_date: date, timezone_name: str) -> PeriodBounds:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidTimezone(timezone_name) from exc

    anchor_start = datetime.combine(anchor_date, datetime.min.time(), tzinfo=zone)
    if period_type == "day":
        local_start = anchor_start
        local_end = local_start + timedelta(days=1)
    elif period_type == "week":
        local_start = anchor_start - timedelta(days=anchor_start.weekday())
        local_end = local_start + timedelta(days=7)
    elif period_type == "month":
        local_start = anchor_start.replace(day=1)
        local_end = _month_after(local_start)
    else:
        raise ValueError(f"Unsupported period type: {period_type}")
    return PeriodBounds(
        period_type=period_type,
        timezone_name=timezone_name,
        local_start=local_start,
        local_end=local_end,
        utc_start=local_start.astimezone(timezone.utc),
        utc_end=local_end.astimezone(timezone.utc),
    )


def previous_period(bounds: PeriodBounds) -> PeriodBounds:
    return period_bounds(
        bounds.period_type,
        (bounds.local_start - timedelta(days=1)).date(),
        bounds.timezone_name,
    )


def daily_buckets(bounds: PeriodBounds) -> list[date]:
    count = (bounds.local_end.date() - bounds.local_start.date()).days
    return [bounds.local_start.date() + timedelta(days=index) for index in range(count)]
