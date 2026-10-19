"""Soil-moisture correction of the root-zone deficit.

Relative readings are percent of available water: 100 is field capacity
(deficit 0) and 0 is wilting (deficit = TAW). Values in 0–1 are treated as
fractions. Volumetric water content needs a field-capacity figure:

    deficit mm = max(0, (θFC − θ) × Zr_m × 1000)

``correct`` blends the bucket toward the sensor. ``override`` replaces it.
"""

from __future__ import annotations

from .const import MOISTURE_CORRECT, MOISTURE_KIND_RELATIVE, MOISTURE_KIND_VWC, MOISTURE_OVERRIDE


def reading_percent(reading: float, unit: str | None) -> float:
    """Show a moisture sensor as a percent.

    A 0–1 fraction becomes 0–100. A reading that is already a percent, or
    whose unit says so, is left as it is.
    """
    if unit and unit.strip().casefold() in {"%", "percent", "pct"}:
        return reading
    if abs(reading) <= 1.5:
        return reading * 100.0
    return reading


def deficit_from_reading(
    *,
    reading: float,
    kind: str,
    taw_mm: float,
    zr_m: float,
    field_capacity_vwc: float | None,
) -> float:
    """Convert one moisture reading into a root-zone deficit in millimeters."""
    if taw_mm <= 0:
        raise ValueError("TAW must be positive")
    if kind == MOISTURE_KIND_RELATIVE:
        percent = reading * 100.0 if 0.0 <= reading <= 1.0 else reading
        percent = min(100.0, max(0.0, percent))
        return taw_mm * (1.0 - percent / 100.0)
    if kind != MOISTURE_KIND_VWC:
        raise ValueError(f"unknown moisture kind {kind}")
    if field_capacity_vwc is None:
        raise ValueError("field capacity is required for volumetric moisture")
    theta = reading / 100.0 if reading > 1.5 else reading
    capacity = (
        field_capacity_vwc / 100.0 if field_capacity_vwc > 1.5 else field_capacity_vwc
    )
    return max(0.0, (capacity - theta) * zr_m * 1000.0)


def apply_moisture(
    bucket_mm: float,
    sensor_mm: float,
    *,
    mode: str,
    weight: float,
) -> float:
    """Return the deficit after a correct or override step."""
    if mode == MOISTURE_OVERRIDE:
        return sensor_mm
    if mode == MOISTURE_CORRECT:
        blend = min(1.0, max(0.0, weight))
        return (1.0 - blend) * bucket_mm + blend * sensor_mm
    return bucket_mm
