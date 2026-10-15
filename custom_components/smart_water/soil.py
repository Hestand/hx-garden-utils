"""Soil, plant, and slope tables used by the bucket and cycle-and-soak math.

Available water is the midpoint of the FAO-56 Table 19 ranges, as reproduced
in the Nevada DWR annex (m³/m³ = in/in). Intake rates are the NRCS maximum
sprinkler application rates by soil and slope band (the same table is in the
MSU/NRCS irrigation sheet and UC ANR 8216). Slope multipliers are not applied
on top of that table; the band is the lookup.

Silt loam over compact soil has intake rates in the NRCS table and no separate
AWC row, so it uses the silt-loam available-water range.
"""

from __future__ import annotations

from dataclasses import dataclass

# (low, high) available water, m³/m³. Midpoint is the default θFC − θWP.
AWC_RANGE: dict[str, tuple[float, float]] = {
    "sand": (0.05, 0.11),
    "sandy_loam": (0.11, 0.15),
    "loam": (0.13, 0.19),
    "silt_loam": (0.13, 0.19),
    # NRCS intake row only; AWC falls back to silt loam.
    "silt_loam_compact": (0.13, 0.19),
    "clay_loam": (0.12, 0.20),
    "clay": (0.12, 0.20),
}

# in/hr at slope bands 0–5 / 5–8 / 8–12 / 12–16 percent.
INTAKE_IN_PER_HR: dict[str, tuple[float, float, float, float]] = {
    "sand": (2.0, 1.5, 1.0, 0.50),
    "sandy_loam": (1.0, 0.80, 0.60, 0.40),
    "loam": (0.50, 0.40, 0.30, 0.20),
    "silt_loam": (0.50, 0.40, 0.30, 0.20),
    "silt_loam_compact": (0.30, 0.25, 0.15, 0.10),
    "clay_loam": (0.15, 0.10, 0.08, 0.06),
    "clay": (0.15, 0.10, 0.08, 0.06),
}

# Soils that get the longer EPA WaterSense soak (60 min). Others use 30 min.
LONG_SOAK_SOILS = frozenset({"clay", "clay_loam", "silt_loam_compact"})


@dataclass(frozen=True)
class PlantProfile:
    """Default crop settings. Unverified cells stay editable per zone."""

    kc: float
    p: float
    root_depth_in: float
    kc_verified: bool
    p_verified: bool
    note: str


# Turf Kc values are UC ANR annual averages. Cool-season p is FAO-56 Table 22.
# Warm-season p was missing from the fetched table and is marked unverified.
# Shrub, native, vegetable, and tree values are starting points, not WUCOLS.
PLANTS: dict[str, PlantProfile] = {
    "cool_season_turf": PlantProfile(
        kc=0.80,
        p=0.40,
        root_depth_in=6.0,
        kc_verified=True,
        p_verified=True,
        note="UC ANR Kc 0.8; FAO-56 Table 22 p=0.40; root depth 6 in default",
    ),
    "warm_season_turf": PlantProfile(
        kc=0.60,
        p=0.50,
        root_depth_in=6.0,
        kc_verified=True,
        p_verified=False,
        note="UC ANR Kc 0.6; p=0.50 is unverified; root depth 6 in default",
    ),
    "shrub": PlantProfile(
        kc=0.50,
        p=0.50,
        root_depth_in=12.0,
        kc_verified=False,
        p_verified=False,
        note="Approximate Kc; root depth 12 in default",
    ),
    "native": PlantProfile(
        kc=0.30,
        p=0.50,
        root_depth_in=12.0,
        kc_verified=False,
        p_verified=False,
        note="Approximate Kc; root depth 12 in default",
    ),
    "vegetable": PlantProfile(
        kc=0.90,
        p=0.40,
        root_depth_in=12.0,
        kc_verified=False,
        p_verified=False,
        note="Kc is the middle of the 0.8–1.0 range; root depth 12 in default",
    ),
    "tree": PlantProfile(
        kc=0.50,
        p=0.50,
        root_depth_in=18.0,
        kc_verified=False,
        p_verified=False,
        note="Editable default; tree root depth was not verified",
    ),
}

# Not a verified WUCOLS shade table. A per-zone Kc override bypasses these.
SUN_FACTOR: dict[str, float] = {
    "full_sun": 1.0,
    "part_sun": 0.80,
    "shade": 0.60,
}

SOIL_TYPES = tuple(AWC_RANGE)
PLANT_TYPES = tuple(PLANTS)
SUN_EXPOSURES = tuple(SUN_FACTOR)


def available_water(soil_type: str, override: float | None = None) -> float:
    """Return θFC − θWP (m³/m³). Override wins; otherwise the range midpoint."""
    if override is not None:
        if override <= 0 or override > 0.6:
            raise ValueError(f"available water {override} is outside 0–0.6")
        return override
    low, high = AWC_RANGE[soil_type]
    return (low + high) / 2.0


def slope_band(slope_pct: float) -> int:
    """Return 0..3 for NRCS bands 0–5 / 5–8 / 8–12 / 12–16 percent.

    The upper edge of a band stays in that band (5% is 0–5). Steeper than
    16% uses the 12–16% rate, which is the lowest in the table.
    """
    if slope_pct <= 5:
        return 0
    if slope_pct <= 8:
        return 1
    if slope_pct <= 12:
        return 2
    return 3


def intake_rate_in_per_hr(soil_type: str, slope_pct: float) -> float:
    """Return the NRCS maximum sprinkler application rate in inches per hour."""
    return INTAKE_IN_PER_HR[soil_type][slope_band(slope_pct)]


def default_soak_minutes(soil_type: str) -> int:
    """Return the EPA WaterSense soak: 60 minutes on slow soils, else 30."""
    if soil_type in LONG_SOAK_SOILS:
        return 60
    return 30


def crop_coefficient(
    plant_type: str,
    sun_exposure: str,
    kc_override: float | None = None,
) -> float:
    """Return Kc. An override replaces both the plant coefficient and sun factor."""
    if kc_override is not None:
        if kc_override < 0 or kc_override > 1.5:
            raise ValueError(f"Kc override {kc_override} is outside 0–1.5")
        return kc_override
    return PLANTS[plant_type].kc * SUN_FACTOR[sun_exposure]
