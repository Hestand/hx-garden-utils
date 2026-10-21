"""Steady flow for the minutes a zone is actually running.

A controller that is polled from the cloud can open and close minutes after
the command. A flow meter can be a minute behind that. The scheduled clock
then starts while the previous zone is still running and ends while this one
still is, so an average of the two ends mixes the two zones.

The rate used here is the median of samples after the valve is open and the
line has settled, and before it closes or the flow falls away. Samples while
another zone's valve is open are left out.
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
    """True when this zone's valve is open, or the meter rose and the valve is unknown.

    A high reading while this valve is still closed or opening belongs to
    whatever ran before it. It does not start this zone's window.
    """
    if valve in OPEN_STATES:
        return True
    if valve in CLOSED_STATES or valve in TRANSITIONAL_STATES:
        return False
    return gpm is not None and gpm > idle_gpm


def zone_is_quiet(valve: str | None, gpm: float | None, idle_gpm: float) -> bool:
    """True when the valve is shut and the meter is back near zero.

    An unknown valve with no meter does not block the next zone. A meter that
    is still up does, even after the valve says closed, because the reading
    can lag the close.
    """
    if valve in OPEN_STATES or valve == "opening":
        return False
    if gpm is not None and gpm > idle_gpm:
        return False
    if valve in CLOSED_STATES or valve == "closing" or valve is None:
        return True
    return gpm is not None and gpm <= idle_gpm


def steady_gpm(samples: list[FlowSample], *, idle_gpm: float) -> float | None:
    """Median rate while this zone is flowing, after the settle period.

    The window starts when this zone is flowing and ends when it stops. The
    first two minutes plus a minute of meter lag are left out when the open
    time is longer than that, so a slow meter does not keep the previous
    zone's water. A shorter run uses the whole open window instead, still
    only samples from this zone.
    """
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
    settle = SETTLE_SECONDS + METER_LAG_SECONDS
    if (end - start).total_seconds() > settle:
        window_start = start + timedelta(seconds=settle)
    else:
        window_start = start
    return _median_in_window(ordered, window_start, end, idle_gpm)


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
    """Steady rate for the open period nearest a finished catch-cup run.

    ``flow`` entries are ``(time, gpm or None)``. A point is skipped when
    another valve was open then, so two zones are not averaged together.
    Returns None when the valve or the meter has no history to read.
    """
    if not flow or not valve:
        return None
    intervals = open_intervals(valve)
    if not intervals:
        return None
    hint_start = finished_at - timedelta(minutes=max(float(minutes), 1.0) + 20.0)
    hint_end = finished_at + timedelta(minutes=20.0)
    best: tuple[datetime, datetime] | None = None
    best_score = 0.0
    for opened, closed in intervals:
        overlap = (min(closed, hint_end) - max(opened, hint_start)).total_seconds()
        if overlap > best_score:
            best_score = overlap
            best = (opened, closed)
    if best is None:
        return None
    opened, closed = best
    blocked = [interval for series in others for interval in open_intervals(series)]
    samples: list[FlowSample] = []
    for moment, gpm in flow:
        if moment < opened or moment > closed:
            continue
        if any(start <= moment < end for start, end in blocked):
            continue
        samples.append(FlowSample(at=moment, valve="open", gpm=gpm))
    return steady_gpm(samples, idle_gpm=idle_gpm)


def _median_in_window(
    samples: list[FlowSample],
    start: datetime,
    end: datetime,
    idle_gpm: float,
) -> float | None:
    rates: list[float] = []
    for sample in samples:
        if sample.at < start or sample.at > end:
            continue
        if not zone_is_flowing(sample.valve, sample.gpm, idle_gpm):
            continue
        if sample.gpm is not None:
            rates.append(sample.gpm)
    if rates:
        return float(statistics.median(rates))
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
    usable = [step for step in steps if step > idle_gpm]
    if not usable:
        return None
    return float(statistics.median(usable))
