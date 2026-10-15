"""Allowed watering days and an optional blackout window.

``allowed_weekdays`` of None means every day (older hubs that never chose).
An explicit empty selection means no day is allowed. A blackout is a local
hour range the shared timeline must stay outside of. Drip can ignore the
weekday list when the hub option says so; the blackout still applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .const import WEEKDAYS

# Retired option values from hubs set up before allowed days replaced presets.
# They exist only so migration can map a stored string onto a day set.
_RETIRED_ODD = "waco_odd"
_RETIRED_EVEN = "waco_even"
_RETIRED_ODD_DAYS = ("sun", "tue", "thu")
_RETIRED_EVEN_DAYS = ("mon", "wed", "sat")
_RETIRED_BLACKOUT_START = 10
_RETIRED_BLACKOUT_END = 19

@dataclass(frozen=True)
class ScheduleRules:
    """Resolved day and blackout rules for one plan."""

    allowed_weekdays: tuple[str, ...] | None
    blackout_start: int | None
    blackout_end: int | None
    source: str


def normalize_weekdays(
    allowed: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    """None stays None (every day). Any list is filtered into weekday order.

    An empty list stays empty, which allows no day.
    """
    if allowed is None:
        return None
    chosen = {str(day) for day in allowed}
    return tuple(day for day in WEEKDAYS if day in chosen)


def rules_for(
    allowed_weekdays: list[str] | tuple[str, ...] | None,
    blackout_start: int | None,
    blackout_end: int | None,
) -> ScheduleRules:
    """Turn stored days and hours into one rule set."""
    return ScheduleRules(
        normalize_weekdays(allowed_weekdays),
        blackout_start,
        blackout_end,
        "days",
    )


def migrate_options(options: dict[str, Any]) -> dict[str, Any]:
    """Rewrite hub options onto allowed days. Zone data is not touched.

    A retired odd-address preset becomes Sun/Tue/Thu and a 10:00–19:00
    blackout. The even-address preset becomes Mon/Wed/Sat with the same
    blackout. Anything else, including a missing preset, allows every day
    and keeps a blackout the user already stored. The old dry-run flag is
    dropped; automatic watering stays off in the store until the user
    turns the switch on.
    """
    updated = dict(options)
    preset = updated.pop("schedule_preset", None)
    updated.pop("dry_run", None)
    if preset == _RETIRED_ODD:
        updated["allowed_weekdays"] = list(_RETIRED_ODD_DAYS)
        updated["blackout_start_hour"] = _RETIRED_BLACKOUT_START
        updated["blackout_end_hour"] = _RETIRED_BLACKOUT_END
    elif preset == _RETIRED_EVEN:
        updated["allowed_weekdays"] = list(_RETIRED_EVEN_DAYS)
        updated["blackout_start_hour"] = _RETIRED_BLACKOUT_START
        updated["blackout_end_hour"] = _RETIRED_BLACKOUT_END
    elif preset == "custom":
        days = updated.get("allowed_weekdays") or []
        if not days:
            updated["allowed_weekdays"] = list(WEEKDAYS)
    else:
        updated["allowed_weekdays"] = list(WEEKDAYS)
    return updated


def weekday_name(moment: datetime) -> str:
    """Return mon..sun for a timezone-aware or naive datetime."""
    return WEEKDAYS[moment.weekday()]


def day_allowed(moment: datetime, allowed: tuple[str, ...] | None) -> bool:
    """True when ``allowed`` is None or contains this weekday.

    None means every day. An empty tuple means no day.
    """
    if allowed is None:
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
