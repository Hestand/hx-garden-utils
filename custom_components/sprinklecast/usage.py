"""Gallons used, a fixed-timer baseline, and a weekly budget check.

Daily, weekly, and monthly figures are sums of a date→gallons log. The
number published to Home Assistant for the water dashboard is the lifetime
total, which only increases. Period totals are derived from the log.
"""

from __future__ import annotations

from datetime import date, timedelta

from .flow import expected_gallons

# A common hose-timer comparison: 15 minutes, three mornings a week.
# It is a baseline for "gallons saved", not a watering recommendation.
DEFAULT_BASELINE_MINUTES = 15.0
DEFAULT_BASELINE_DAYS = 3
LOG_DAYS = 400


def add_use(days: dict[str, float] | None, day: str, gallons: float) -> dict[str, float]:
    """Add gallons to one date and drop entries older than the log window."""
    updated = {str(key): float(value) for key, value in dict(days or {}).items()}
    if gallons > 0:
        updated[day] = round(float(updated.get(day) or 0.0) + gallons, 3)
    cutoff = date.fromisoformat(day) - timedelta(days=LOG_DAYS)
    return {
        key: value
        for key, value in updated.items()
        if _parse(key) is not None and _parse(key) >= cutoff
    }


def period_gallons(days: dict[str, float] | None, today: date, *, span: str) -> float:
    """Sum the log for today, the last 7 days, or the calendar month."""
    total = 0.0
    for key, gallons in dict(days or {}).items():
        stamp = _parse(str(key))
        if stamp is None:
            continue
        if span == "day" and stamp == today:
            total += float(gallons)
        elif span == "week" and today - timedelta(days=6) <= stamp <= today:
            total += float(gallons)
        elif span == "month" and stamp.year == today.year and stamp.month == today.month:
            total += float(gallons)
    return round(total, 3)


def baseline_week_gallons(
    *,
    minutes: float,
    days_per_week: float,
    precipitation_rate_in_hr: float | None,
    area_sqft: float | None,
    flow_gpm: float | None,
) -> float | None:
    """Gallons a fixed timer would use in seven days, or None without a volume basis."""
    if minutes <= 0 or days_per_week <= 0:
        return None
    per_run = expected_gallons(
        runtime_min=minutes,
        precipitation_rate_in_hr=precipitation_rate_in_hr,
        area_sqft=area_sqft,
        flow_gpm=flow_gpm,
    )
    if per_run is None:
        return None
    return round(per_run * days_per_week, 3)


def saved_gallons(baseline: float | None, actual: float) -> float | None:
    """Baseline minus actual. Positive means the plan used less than the timer."""
    if baseline is None:
        return None
    return round(baseline - actual, 3)


def cost_of(gallons: float, per_thousand: float | None) -> float | None:
    """Dollars for a gallon total at a price per 1,000 gallons."""
    if per_thousand is None or per_thousand < 0:
        return None
    return round(gallons / 1000.0 * per_thousand, 2)


def _parse(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
