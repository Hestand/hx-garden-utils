"""Compare a flow meter's delivered volume with the planned volume.

This module only classifies. It does not open a valve. Expected gallons come
from the planned runtime and either precipitation rate × area, or a zone GPM.
Delivered gallons are integrated from a total or a rate the same way rain is.
"""

from __future__ import annotations

from datetime import datetime

from .const import FLOW_KIND_RATE, FLOW_KIND_TOTAL

# US gallons in one inch of water over one square foot.
GALLONS_PER_INCH_SQFT = 0.623
_MAX_GAP_HOURS = 6.0
# Flow with nothing scheduled, above this, is treated as a leak.
UNSCHEDULED_LEAK_GAL = 1.0


def expected_gallons(
    *,
    runtime_min: float,
    precipitation_rate_in_hr: float | None,
    area_sqft: float | None,
    flow_gpm: float | None,
) -> float | None:
    """Gallons the plan would apply. None when the zone has no volume basis."""
    if runtime_min <= 0:
        return 0.0
    if precipitation_rate_in_hr and area_sqft and area_sqft > 0:
        inches = runtime_min / 60.0 * precipitation_rate_in_hr
        return inches * area_sqft * GALLONS_PER_INCH_SQFT
    if flow_gpm and flow_gpm > 0:
        return flow_gpm * runtime_min
    return None


def note_flow(
    state: dict[str, object],
    *,
    kind: str,
    gallons: float,
    at: datetime,
    today: str,
) -> None:
    """Fold one flow reading into today's delivered gallons."""
    if state.get("flow_date") != today:
        state["flow_date"] = today
        state["flow_delivered_gal"] = 0.0
        state["flow_cursor"] = None
        state["flow_last_at"] = None
    if kind == FLOW_KIND_TOTAL:
        cursor = state.get("flow_cursor")
        if cursor is None:
            state["flow_cursor"] = gallons
        else:
            delta = gallons - float(cursor)
            if delta >= 0:
                state["flow_delivered_gal"] = float(state["flow_delivered_gal"]) + delta
            state["flow_cursor"] = gallons
        state["flow_last_at"] = at.isoformat()
        return
    if kind != FLOW_KIND_RATE:
        raise ValueError(f"unknown flow kind {kind}")
    last = state.get("flow_last_at")
    cursor = state.get("flow_cursor")
    if last is not None and cursor is not None:
        previous = datetime.fromisoformat(str(last))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=at.tzinfo)
        hours = (at - previous).total_seconds() / 3600.0
        if 0 < hours <= _MAX_GAP_HOURS:
            average_gpm = (float(cursor) + gallons) / 2.0
            state["flow_delivered_gal"] = float(state["flow_delivered_gal"]) + max(
                0.0, average_gpm
            ) * hours * 60.0
    state["flow_cursor"] = gallons
    state["flow_last_at"] = at.isoformat()


def classify_flow(
    *,
    expected_gal: float | None,
    delivered_gal: float,
    scheduled: bool,
    run_finished: bool,
    low_ratio: float,
    leak_ratio: float,
) -> str:
    """Return pending, ok, low_flow, leak, or no_data."""
    if expected_gal is None and delivered_gal <= 0:
        return "no_data"
    if (expected_gal is None or expected_gal <= 0) and delivered_gal >= UNSCHEDULED_LEAK_GAL:
        return "leak"
    if expected_gal is None or expected_gal <= 0:
        return "no_data"
    ratio = delivered_gal / expected_gal
    if ratio > leak_ratio:
        return "leak"
    if scheduled and not run_finished:
        return "pending"
    if ratio < low_ratio:
        return "low_flow"
    return "ok"
