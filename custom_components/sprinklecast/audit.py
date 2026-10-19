"""Catch-cup audit: precipitation rate, DU_lq, and scheduling efficiency.

Distribution uniformity of the low quarter is the average of the lowest
quarter of the cups divided by the average of every cup, including cups
that stayed empty. Scheduling efficiency is that same fraction. The
planner divides by efficiency, so storing it makes the driest quarter
receive the net depth (the runtime multiplier is 1 / DU_lq).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# 1 US fluid millilitre in cubic inches.
ML_TO_CUBIC_INCH = 1.0 / 16.387064


@dataclass(frozen=True)
class AuditResult:
    """Numbers from one catch-cup test."""

    precipitation_rate_in_hr: float
    du_lq: float
    scheduling_efficiency: float
    average_in: float
    low_quarter_in: float
    cups: int


def depths_inches(
    readings: list[float],
    *,
    unit: str,
    cup_diameter_in: float | None,
) -> list[float]:
    """Convert cup readings to inches of depth. Zeros stay zeros."""
    if unit in {"in", "inch", "inches"}:
        return [float(value) for value in readings]
    if unit not in {"ml", "mL"}:
        raise ValueError("Cup readings must be inches or mL.")
    if cup_diameter_in is None or cup_diameter_in <= 0:
        raise ValueError("A cup diameter in inches is required for mL readings.")
    area = math.pi * (cup_diameter_in / 2.0) ** 2
    return [float(value) * ML_TO_CUBIC_INCH / area for value in readings]


def precipitation_rate_in_hr(depths_in: list[float], minutes: float) -> float:
    """Average catch depth spread over the test, in inches per hour."""
    if minutes <= 0:
        raise ValueError("The audit must run for at least a minute.")
    if not depths_in:
        raise ValueError("Enter at least one cup reading.")
    average = sum(depths_in) / len(depths_in)
    return average * (60.0 / minutes)


def du_lq(depths_in: list[float]) -> float:
    """Low-quarter distribution uniformity, from 0 to 1.

    The lowest quarter is ``max(1, n // 4)`` cups, so 16 cups use 4 and a
    short test still has a low quarter of one cup.
    """
    if not depths_in:
        raise ValueError("Enter at least one cup reading.")
    ordered = sorted(float(value) for value in depths_in)
    if any(value < 0 for value in ordered):
        raise ValueError("Cup readings cannot be negative.")
    average = sum(ordered) / len(ordered)
    if average <= 0:
        raise ValueError("Every cup was empty, so uniformity is undefined.")
    quarter = max(1, len(ordered) // 4)
    low = sum(ordered[:quarter]) / quarter
    return low / average


def scheduling_efficiency(uniformity: float) -> float:
    """Efficiency the planner should store. Equal to DU_lq, clamped to 0–1."""
    if uniformity <= 0 or uniformity > 1:
        raise ValueError("Distribution uniformity must be between 0 and 1.")
    return uniformity


def audit_result(
    readings: list[float],
    *,
    minutes: float,
    unit: str,
    cup_diameter_in: float | None,
) -> AuditResult:
    """Rate, DU_lq, and scheduling efficiency for one set of cups."""
    if len(readings) < 4:
        raise ValueError("Enter at least 4 cup readings. 16 in a grid is better.")
    depths = depths_inches(readings, unit=unit, cup_diameter_in=cup_diameter_in)
    uniformity = du_lq(depths)
    ordered = sorted(depths)
    quarter = max(1, len(ordered) // 4)
    return AuditResult(
        precipitation_rate_in_hr=round(precipitation_rate_in_hr(depths, minutes), 3),
        du_lq=round(uniformity, 3),
        scheduling_efficiency=round(scheduling_efficiency(uniformity), 3),
        average_in=round(sum(depths) / len(depths), 3),
        low_quarter_in=round(sum(ordered[:quarter]) / quarter, 3),
        cups=len(depths),
    )
