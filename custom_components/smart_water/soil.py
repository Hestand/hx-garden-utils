"""Soil, plant, and sun lookups.

The numbers live in ``presets.py`` with their citations. This module keeps
the functions the bucket and the cycle-and-soak math already call.
"""

from __future__ import annotations

from dataclasses import dataclass

from .presets import (
    PLANTS as PLANT_PRESETS,
    SOILS,
    SUN,
    available_water_default,
    intake_default,
    plant_kc,
    slope_band,
    sun_factor,
)

# (low, high) available water, m³/m³. The default is ``SoilPreset.awc``.
AWC_RANGE: dict[str, tuple[float, float]] = {
    key: (row.awc_low, row.awc_high) for key, row in SOILS.items()
}
INTAKE_IN_PER_HR: dict[str, tuple[float, float, float, float]] = {
    key: row.intake_in_hr for key, row in SOILS.items()
}

# Clay, clay loam, and compact silt loam used a 60-minute soak through 0.10.1.
# Every soil now uses 30 minutes unless the zone stores its own soak.


@dataclass(frozen=True)
class PlantProfile:
    """Annual coefficient, depletion, and root depth for one planting."""

    kc: float
    p: float
    root_depth_in: float
    note: str


PLANTS: dict[str, PlantProfile] = {
    key: PlantProfile(
        kc=row.kc_annual,
        p=row.p,
        root_depth_in=row.root_depth_in,
        note=row.source,
    )
    for key, row in PLANT_PRESETS.items()
}

SUN_FACTOR: dict[str, float] = {key: value for key, (value, _note) in SUN.items()}

SOIL_TYPES = tuple(SOILS)
PLANT_TYPES = tuple(PLANTS)
SUN_EXPOSURES = tuple(SUN_FACTOR)


def available_water(soil_type: str, override: float | None = None) -> float:
    """Return θFC − θWP (m³/m³). Override wins; otherwise the preset."""
    if override is not None:
        if override <= 0 or override > 0.6:
            raise ValueError(f"available water {override} is outside 0–0.6")
        return override
    return available_water_default(soil_type)


def intake_rate_in_per_hr(soil_type: str, slope_pct: float) -> float:
    """Return the NRCS maximum sprinkler application rate in inches per hour."""
    return intake_default(soil_type, slope_pct)


def default_soak_minutes(soil_type: str) -> int:
    """Return the soak used when a zone leaves Soak blank.

    30 minutes for every soil, including clay, clay loam, and compact silt
    loam. A stored soak on the zone replaces this. Drip and bubbler still
    soak 0 unless that zone sets a number. ``soil_type`` is kept so a zone
    that already calls this with its soil still gets the preset.
    """
    if not soil_type:
        raise ValueError("soil type is required")
    return 30


def crop_coefficient(
    plant_type: str,
    sun_exposure: str,
    kc_override: float | None = None,
    month: int | None = None,
) -> float:
    """Return Kc. An override replaces both the plant coefficient and sun factor.

    ``month`` (1–12) selects the monthly turf coefficient when that plant has
    one. Without a month, the published annual average is used.
    """
    if kc_override is not None:
        if kc_override < 0 or kc_override > 1.5:
            raise ValueError(f"Kc override {kc_override} is outside 0–1.5")
        return kc_override
    return plant_kc(plant_type, month) * sun_factor(sun_exposure)


__all__ = [
    "AWC_RANGE",
    "INTAKE_IN_PER_HR",
    "PLANT_TYPES",
    "PLANTS",
    "SOIL_TYPES",
    "SUN_EXPOSURES",
    "SUN_FACTOR",
    "PlantProfile",
    "available_water",
    "crop_coefficient",
    "default_soak_minutes",
    "intake_rate_in_per_hr",
    "slope_band",
]
