"""Flow for the minutes a zone is actually running.

A cloud-polled valve entity can say closed for minutes after water is already
moving, and say open only after the meter has been up. That report is lag,
not the valve itself. When a flow reading exists, the window starts when the
meter rises and ends when it falls. The valve entity is the fallback when
the meter has no reading, and a sanity check so another zone's reported-open
period is not mixed in.

Learn-flow uses the peak in the middle third of that window. A catch-cup or
normal run still uses the median after a short settle, on the same edges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import statistics

# The first minutes after a valve opens are fill, air, and the meter's lag.
SETTLE_SECONDS = 120.0
METER_LAG_SECONDS = 60.0
# How often a running zone is sampled. Short enough for a one-minute meter.
SAMPLE_SECONDS = 30.0
# Do not wait forever for a cloud-polled valve or a meter to catch up.
VALVE_WAIT_TIMEOUT_SECONDS = 300.0

OPEN_STATES = frozenset({"open", "on"})
CLOSED_STATES = frozenset({"closed", "off"})
# Command accepted, water not moving yet. Not an open valve.
TRANSITIONAL_STATES = frozenset({"opening", "closing"})


@dataclass(frozen=True)
class FlowSample:
    """One look at the valve and the meter."""

    at: datetime
    valve: str | None
    gpm: float | None = None
    gallons: float | None = None


def zone_is_flowing(valve: str | None, gpm: float | None, idle_gpm: float) -> bool:
    """True when the meter is up, or the valve says open and the meter is absent.

    A high reading while the valve entity still says closed or opening is this
    zone once it has been commanded on. The entity has not caught up yet.
    """
    if gpm is not None:
        return gpm > idle_gpm
    return valve in OPEN_STATES


def zone_is_quiet(valve: str | None, gpm: float | None, idle_gpm: float) -> bool:
    """True when the meter is back near zero, or the valve is shut and there is no meter.

    The valve entity can still say open after the water has stopped. That does
    not hold the next zone. A meter that is still up does.
    """
    if gpm is not None:
        return gpm <= idle_gpm
    if valve in OPEN_STATES or valve == "opening":
        return False
    return True


def flowing_bounds(
    samples: list[FlowSample], *, idle_gpm: float
) -> tuple[datetime, datetime] | None:
    """Start and end of the first contiguous period the meter (or valve) is up."""
    ordered = sorted(samples, key=lambda sample: sample.at)
    start: datetime | None = None
    for sample in ordered:
        if zone_is_flowing(sample.valve, sample.gpm, idle_gpm):
            start = sample.at
            break
    if start is None:
        return None
    end = start
    for sample in ordered:
        if sample.at < start:
            continue
        if zone_is_flowing(sample.valve, sample.gpm, idle_gpm):
            end = sample.at
            continue
        if sample.at > start:
            break
    return start, end


def steady_gpm(samples: list[FlowSample], *, idle_gpm: float) -> float | None:
    """Median rate while this zone is flowing, after the settle period.

    The window starts when the meter rises, not when the valve entity reports
    open, and ends when the meter falls. The first two minutes plus a minute
    of meter lag are left out when the flowing time is longer than that. A
    shorter run uses the whole flowing window.
    """
    bounds = flowing_bounds(samples, idle_gpm=idle_gpm)
    if bounds is None:
        return None
    start, end = bounds
    settle = SETTLE_SECONDS + METER_LAG_SECONDS
    if (end - start).total_seconds() > settle:
        window_start = start + timedelta(seconds=settle)
    else:
        window_start = start
    ordered = sorted(samples, key=lambda sample: sample.at)
    return _median_in_window(ordered, window_start, end, idle_gpm)


def peak_middle_gpm(samples: list[FlowSample], *, idle_gpm: float) -> float | None:
    """Highest rate in the middle third of the flowing window.

    The ends are fill, air, and the meter catching up or falling off. The
    middle is the run. One sample uses that sample.
    """
    bounds = flowing_bounds(samples, idle_gpm=idle_gpm)
    if bounds is None:
        return None
    start, end = bounds
    span = (end - start).total_seconds()
    if span < 1:
        window_start, window_end = start, end
    else:
        window_start = start + timedelta(seconds=span / 3.0)
        window_end = start + timedelta(seconds=span * 2.0 / 3.0)
    ordered = sorted(samples, key=lambda sample: sample.at)
    rates = _rates_in_window(ordered, window_start, window_end, idle_gpm)
    if not rates:
        rates = _rates_in_window(ordered, start, end, idle_gpm)
    if not rates:
        return None
    return float(max(rates))


def open_intervals(points: list[tuple[datetime, str]]) -> list[tuple[datetime, datetime]]:
    """Periods a valve reported open. The state holds until the next change."""
    intervals: list[tuple[datetime, datetime]] = []
    opened: datetime | None = None
    for moment, state in sorted(points, key=lambda item: item[0]):
        if state in OPEN_STATES and opened is None:
            opened = moment
        elif state not in OPEN_STATES and opened is not None:
            if moment > opened:
                intervals.append((opened, moment))
            opened = None
    return intervals


def baseline_gpm_from_history(
    flow: list[tuple[datetime, float | None]],
    valve: list[tuple[datetime, str]],
    others: list[list[tuple[datetime, str]]],
    *,
    finished_at: datetime,
    minutes: float,
    idle_gpm: float,
) -> float | None:
    """Steady rate for the flowing period nearest a finished catch-cup run.

    ``flow`` entries are ``(time, gpm or None)``. The meter rising is the
    start, including samples from before the valve entity reports open. A
    point is skipped when another valve was reported open then. With no meter
    history, this returns None.
    """
    if not flow:
        return None
    hint_start = finished_at - timedelta(minutes=max(float(minutes), 1.0) + 20.0)
    hint_end = finished_at + timedelta(minutes=20.0)
    intervals = open_intervals(valve)
    best: tuple[datetime, datetime] | None = None
    best_score = 0.0
    for opened, closed in intervals:
        overlap = (min(closed, hint_end) - max(opened, hint_start)).total_seconds()
        if overlap > best_score:
            best_score = overlap
            best = (opened, closed)
    if best is not None:
        opened, closed = best
        # The entity reports open late. Keep flow from a few minutes before that.
        search_from = opened - timedelta(minutes=5)
        search_to = closed + timedelta(minutes=3)
    elif valve:
        return None
    else:
        opened = None
        closed = None
        search_from = hint_start
        search_to = hint_end
    blocked = [interval for series in others for interval in open_intervals(series)]
    samples: list[FlowSample] = []
    for moment, gpm in flow:
        if moment < search_from or moment > search_to:
            continue
        if any(start <= moment < end for start, end in blocked):
            continue
        reported = (
            "open" if opened is not None and opened <= moment < closed else "closed"
        )
        samples.append(FlowSample(at=moment, valve=reported, gpm=gpm))
    if not samples:
        return None
    return steady_gpm(samples, idle_gpm=idle_gpm)


def _rates_in_window(
    samples: list[FlowSample],
    start: datetime,
    end: datetime,
    idle_gpm: float,
) -> list[float]:
    """Gallons per minute inside the window. A volume total is differenced."""
    rates: list[float] = []
    for sample in samples:
        if sample.at < start or sample.at > end:
            continue
        if not zone_is_flowing(sample.valve, sample.gpm, idle_gpm):
            continue
        if sample.gpm is not None and sample.gpm > idle_gpm:
            rates.append(sample.gpm)
    if rates:
        return rates
    totals = [
        sample
        for sample in samples
        if start <= sample.at <= end and sample.gallons is not None
    ]
    steps: list[float] = []
    for earlier, later in zip(totals, totals[1:]):
        minutes = (later.at - earlier.at).total_seconds() / 60.0
        if minutes <= 0 or later.gallons is None or earlier.gallons is None:
            continue
        steps.append((later.gallons - earlier.gallons) / minutes)
    return [step for step in steps if step > idle_gpm]


def _median_in_window(
    samples: list[FlowSample],
    start: datetime,
    end: datetime,
    idle_gpm: float,
) -> float | None:
    rates = _rates_in_window(samples, start, end, idle_gpm)
    if not rates:
        return None
    return float(statistics.median(rates))
