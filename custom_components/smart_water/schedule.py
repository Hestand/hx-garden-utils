"""Allowed watering days and blackout hours.

The Waco preset follows the City of Waco year-round outdoor rules (effective
1 July 2024): odd addresses water Sunday, Tuesday, and Thursday; even
addresses water Monday, Wednesday, and Saturday; Friday is off; no watering
from 10:00 to 19:00. The window is one interval that ends at the sunrise
deadline, so a blackout keeps only the legal stretch that still ends then.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .const import (
    SCHEDULE_CUSTOM,
    SCHEDULE_NONE,
    SCHEDULE_WACO_EVEN,
    SCHEDULE_WACO_ODD,
    WACO_BLACKOUT_END,
    WACO_BLACKOUT_START,
    WACO_EVEN_DAYS,
    WACO_ODD_DAYS,
    WEEKDAYS,
)

_WEEKDAY_INDEX = {name: index for index, name in enumerate(WEEKDAYS)}


@dataclass(frozen=True)
class ScheduleRules:
    """Resolved day and blackout rules for one plan."""

    allowed_weekdays: tuple[str, ...] | None
    blackout_start: int | None
    blackout_end: int | None
    source: str


def rules_for(
    preset: str | None,
    allowed_weekdays: list[str] | tuple[str, ...] | None,
    blackout_start: int | None,
    blackout_end: int | None,
) -> ScheduleRules:
    """Turn a preset, or custom days and hours, into one rule set."""
    if preset == SCHEDULE_WACO_ODD:
        return ScheduleRules(WACO_ODD_DAYS, WACO_BLACKOUT_START, WACO_BLACKOUT_END, preset)
    if preset == SCHEDULE_WACO_EVEN:
        return ScheduleRules(
            WACO_EVEN_DAYS, WACO_BLACKOUT_START, WACO_BLACKOUT_END, preset
        )
    if preset == SCHEDULE_CUSTOM:
        days = tuple(day for day in WEEKDAYS if allowed_weekdays and day in allowed_weekdays)
        return ScheduleRules(days or None, blackout_start, blackout_end, preset)
    return ScheduleRules(None, blackout_start, blackout_end, preset or SCHEDULE_NONE)


def weekday_name(moment: datetime) -> str:
    """Return mon..sun for a timezone-aware or naive datetime."""
    return WEEKDAYS[moment.weekday()]


def day_allowed(moment: datetime, allowed: tuple[str, ...] | None) -> bool:
    """True when ``allowed`` is empty or contains this weekday."""
    if not allowed:
        return True
    return weekday_name(moment) in allowed


def _in_blackout(moment: datetime, start: int, end: int) -> bool:
    return start <= moment.hour < end


def clip_blackout(
    finish_by: datetime,
    earliest: datetime | None,
    start_hour: int | None,
    end_hour: int | None,
) -> tuple[datetime, datetime | None, str | None]:
    """Shrink the window so it does not cross the blackout.

    The plan is one interval ending at ``finish_by``. If that deadline sits
    inside the blackout, it moves back to the blackout start. The earliest
    legal start is then the beginning of the free period that contains the
    deadline (midnight for a morning finish, blackout end for an evening one).
    """
    if start_hour is None or end_hour is None or start_hour == end_hour:
        return finish_by, earliest, None
    if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23:
        raise ValueError("blackout hours must be 0–23")
    note = None
    finish = finish_by
    if _in_blackout(finish, start_hour, end_hour):
        finish = finish.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        note = (
            f"The sunrise deadline was inside the {start_hour:02d}:00–"
            f"{end_hour:02d}:00 blackout and was moved to {start_hour:02d}:00."
        )
    if finish.hour < start_hour or (
        finish.hour == start_hour and finish.minute == 0 and finish.second == 0
    ):
        barrier = finish.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        barrier = finish.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        note = (
            note
            or (
                f"The watering window starts at {end_hour:02d}:00 so it stays "
                f"out of the {start_hour:02d}:00–{end_hour:02d}:00 blackout."
            )
        )
    if earliest is None or earliest < barrier:
        earliest = barrier
    return finish, earliest, note
