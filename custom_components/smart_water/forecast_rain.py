"""Forecast rain and freeze, without ever crediting a forecast to the bucket.

Expected rain is probability times amount over the next one or two days.
Watering waits only when that chance is high enough, and only for a few
mornings. Measured rain is a separate path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_FORECAST_PROBABILITY_PCT = 60.0
DEFAULT_FORECAST_DEFER_DAYS = 2
DEFAULT_FORECAST_HOURS = 48
DEFAULT_FREEZE_ALERT_F = 32.0
DEFAULT_HARD_FREEZE_F = 28.0


@dataclass(frozen=True)
class ExpectedRain:
    """Confident forecast rain over one window."""

    expected_mm: float
    probability_pct: float
    slots: int


@dataclass(frozen=True)
class FreezeOutlook:
    """The first cold morning in the window, and whether it is a hard freeze."""

    when: datetime
    low_f: float
    hard: bool


def expected_rain(
    slots: tuple[tuple[datetime, float, float | None], ...] | list[tuple[datetime, float, float | None]],
    *,
    now: datetime,
    hours: float,
    probability_min: float,
) -> ExpectedRain:
    """Sum probability × depth for slots at or above ``probability_min``.

    Each slot is ``(time, depth_mm, probability_pct)``. A missing probability
    is not treated as certain. The reported probability is the highest one
    that counted.
    """
    if hours <= 0:
        return ExpectedRain(0.0, 0.0, 0)
    until = now + timedelta(hours=hours)
    expected = 0.0
    peak = 0.0
    counted = 0
    for stamp, depth, probability in slots:
        if stamp < now or stamp >= until:
            continue
        if probability is None or probability < probability_min:
            continue
        if depth <= 0:
            continue
        expected += depth * (probability / 100.0)
        peak = max(peak, probability)
        counted += 1
    return ExpectedRain(round(expected, 3), peak, counted)


def defer_reason(
    *,
    expected_mm: float,
    probability_pct: float | None,
    probability_min: float,
    deficit_mm: float,
    threshold_mm: float | None,
    days_used: int,
    max_days: int,
) -> str | None:
    """The schedule sentence, or None when this morning should not wait.

    Waiting stops after ``max_days`` even if the forecast still looks wet.
    Forecast depth is never subtracted from the soil bucket.
    """
    if not wants_defer(
        expected_mm=expected_mm,
        probability_pct=probability_pct,
        probability_min=probability_min,
        deficit_mm=deficit_mm,
        threshold_mm=threshold_mm,
    ):
        return None
    if days_used >= max_days:
        return None
    assert probability_pct is not None
    inches = expected_mm / 25.4
    return f"Deferred for forecast rain ({probability_pct:.0f}% / {inches:.1f} in)."


def wants_defer(
    *,
    expected_mm: float,
    probability_pct: float | None,
    probability_min: float,
    deficit_mm: float,
    threshold_mm: float | None,
) -> bool:
    """True when confident expected rain covers the deficit or the threshold."""
    if probability_pct is None or probability_pct < probability_min or expected_mm <= 0:
        return False
    covers_deficit = deficit_mm > 0 and expected_mm >= deficit_mm
    covers_threshold = threshold_mm is not None and expected_mm >= threshold_mm
    if threshold_mm is None:
        return covers_deficit
    return covers_deficit or covers_threshold


def defer_days_before_today(days: int, last_date: str | None, today: str) -> int:
    """Mornings already spent waiting, not counting a deferral recorded today."""
    if last_date == today and days > 0:
        return days - 1
    return days


def upcoming_freeze(
    lows: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]],
    *,
    now: datetime,
    hours: float,
    freeze_f: float,
    hard_f: float,
) -> FreezeOutlook | None:
    """The first forecast low at or below ``freeze_f`` inside the window."""
    if hours <= 0:
        return None
    until = now + timedelta(hours=hours)
    chosen: tuple[datetime, float] | None = None
    coldest = None
    for stamp, low in lows:
        if stamp < now or stamp >= until:
            continue
        if coldest is None or low < coldest:
            coldest = low
        if low <= freeze_f and (chosen is None or stamp < chosen[0]):
            chosen = (stamp, low)
    if chosen is None:
        return None
    low = coldest if coldest is not None else chosen[1]
    return FreezeOutlook(when=chosen[0], low_f=low, hard=low <= hard_f)


def freeze_message(outlook: FreezeOutlook) -> str:
    """One sentence for the notification, the repair, and the event."""
    when = outlook.when.strftime("%A")
    if outlook.hard:
        return (
            f"Forecast low is {outlook.low_f:.0f}°F on {when}, a hard freeze. "
            "Shut off and drain the irrigation, and protect the backflow "
            "preventer and exposed pipes."
        )
    return (
        f"Forecast low is {outlook.low_f:.0f}°F on {when}. Winterize or protect "
        "the backflow preventer and any exposed pipes before then."
    )
