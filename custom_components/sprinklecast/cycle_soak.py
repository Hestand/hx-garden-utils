"""Cycle-and-soak from soil intake, slope, and precipitation rate.

Max cycle minutes = 60 × NRCS intake rate (in/hr) ÷ precipitation rate (in/hr).
That matches the design example: 1.5 in/hr sprays on clay loam at a 5–8% slope
(0.10 in/hr) produce a 4 minute cycle. The result is floored so a cycle does
not exceed the intake rate, then raised to 1 minute. A warning is set when 1 minute still exceeds
the intake rate.

Soak time is 30 minutes for every soil, including clay, clay loam, and
compact silt loam. A measured pooling test can override that number. Drip
and bubbler soak 0 unless the zone sets one.

Total runtime (minutes) = 60 × gross depth (in) ÷ precipitation rate.
Gross depth = net depth ÷ efficiency. Efficiency defaults to 1.0; this
integration does not assume an unverified distribution uniformity.
Cycles are whole minutes and sum to the rounded total runtime.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .const import SPRINKLERS_WITHOUT_SOAK
from .soil import default_soak_minutes, intake_rate_in_per_hr
from .units import mm_to_inches

# 60 min/hr ÷ 7.48 gal/ft³ × 12 in/ft. Rain Bird publishes 96.3.
PRECIP_RATE_GPM_AREA = 96.25


def precipitation_rate_in_per_hr(flow_gpm: float, area_sqft: float) -> float:
    """Total-area precipitation rate, inches per hour."""
    if flow_gpm <= 0 or area_sqft <= 0:
        raise ValueError("flow and area must be positive")
    return PRECIP_RATE_GPM_AREA * flow_gpm / area_sqft


def resolve_precipitation_rate(
    precipitation_rate_in_hr: float | None,
    flow_gpm: float | None,
    area_sqft: float | None,
    preset_in_hr: float | None = None,
) -> float:
    """Prefer a user-entered rate, then GPM and area, then the sprinkler preset."""
    if precipitation_rate_in_hr is not None and precipitation_rate_in_hr > 0:
        return precipitation_rate_in_hr
    if flow_gpm is not None and area_sqft is not None:
        return precipitation_rate_in_per_hr(flow_gpm, area_sqft)
    if preset_in_hr is not None and preset_in_hr > 0:
        return preset_in_hr
    raise ValueError("set a precipitation rate in/hr, or both GPM and area")


def max_cycle_minutes(intake_in_hr: float, precipitation_rate_in_hr: float) -> int:
    """Floor of 60 × intake ÷ PR, at least 1."""
    if intake_in_hr <= 0 or precipitation_rate_in_hr <= 0:
        raise ValueError("intake and precipitation rate must be positive")
    raw = 60.0 * intake_in_hr / precipitation_rate_in_hr
    return max(1, math.floor(raw + 1e-9))


def split_runtime(total_minutes: int, max_cycle: int) -> tuple[int, ...]:
    """Split a whole-minute runtime into cycles that respect the maximum.

    As many cycles as needed are used so each one is an integer and the
    pieces differ by at most one minute.
    """
    if total_minutes <= 0:
        return ()
    if max_cycle < 1:
        max_cycle = 1
    count = math.ceil(total_minutes / max_cycle)
    base, remainder = divmod(total_minutes, count)
    longer = (base + 1,) * remainder
    shorter = (base,) * (count - remainder)
    return tuple(minutes for minutes in (*longer, *shorter) if minutes > 0)


@dataclass(frozen=True)
class CycleSoak:
    """Whole-minute cycle plan for one zone."""

    intake_in_hr: float
    max_cycle_min: int
    soak_min: int
    net_mm: float
    gross_in: float
    total_runtime_min: int | float
    cycles_min: tuple[int | float, ...]
    intake_exceeded_by_minimum: bool
    note: str | None


def plan_cycles(
    *,
    net_mm: float,
    precipitation_rate_in_hr: float,
    efficiency: float,
    soil_type: str,
    slope_pct: float,
    max_cycle_override_min: int | None = None,
    soak_override_min: int | None = None,
    whole_minutes: bool = True,
    sprinkler_type: str | None = None,
    intake_override_in_hr: float | None = None,
) -> CycleSoak:
    """Turn a net irrigation depth into cycles and a soak.

    ``whole_minutes`` rounds the runtime to an integer. When it is false the
    runtime is kept to 0.1 minute. Drip and bubbler zones soak for 0 unless
    the zone sets an override, because those rates do not pond the way sprays do.
    """
    if efficiency <= 0 or efficiency > 1:
        raise ValueError("efficiency must be in (0, 1]")
    if precipitation_rate_in_hr <= 0:
        raise ValueError("precipitation rate must be positive")
    if intake_override_in_hr is not None and intake_override_in_hr > 0:
        intake = intake_override_in_hr
    else:
        intake = intake_rate_in_per_hr(soil_type, slope_pct)
    computed_max = max_cycle_minutes(intake, precipitation_rate_in_hr)
    unlimited = 60.0 * intake / precipitation_rate_in_hr
    exceeded = unlimited < 1.0 and max_cycle_override_min is None
    max_cycle = (
        computed_max if max_cycle_override_min is None else max(1, max_cycle_override_min)
    )
    if soak_override_min is not None:
        soak = max(0, soak_override_min)
    elif sprinkler_type in SPRINKLERS_WITHOUT_SOAK:
        soak = 0
    else:
        soak = default_soak_minutes(soil_type)
    net_in = mm_to_inches(max(0.0, net_mm))
    gross_in = net_in / efficiency
    raw_total = 60.0 * gross_in / precipitation_rate_in_hr
    if whole_minutes:
        total: int | float = int(round(raw_total))
        cycles = split_runtime(int(total), max_cycle)
    else:
        total = round(raw_total, 1)
        tenths = int(round(total * 10))
        cycles = tuple(
            piece / 10 for piece in split_runtime(tenths, max(1, max_cycle * 10))
        )
    note = None
    if exceeded:
        note = (
            "Precipitation rate exceeds the NRCS intake rate so badly that "
            "even a 1 minute cycle overshoots it."
        )
    elif max_cycle_override_min is not None:
        note = "Max cycle uses the zone override instead of the NRCS table."
    return CycleSoak(
        intake_in_hr=intake,
        max_cycle_min=max_cycle,
        soak_min=soak,
        net_mm=max(0.0, net_mm),
        gross_in=gross_in,
        total_runtime_min=total,
        cycles_min=cycles,
        intake_exceeded_by_minimum=exceeded,
        note=note,
    )
