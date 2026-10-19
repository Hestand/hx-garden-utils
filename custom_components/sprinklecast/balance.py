"""Root-zone water balance.

FAO-56 Chapter 8, Eq. 85:

    Dr,i = Dr,i−1 − (P − RO)i − Ii − CRi + ETc,i + DPi

with 0 ≤ Dr ≤ TAW. Deep percolation is the water that would drive Dr below
zero (Eq. 88); it is not stored. Capillary rise is zero unless a caller
passes it. Rain below about 0.2 × ET0 is ignored, which is the FAO daily
rule. There is no fixed "80% of rain is effective" factor.

TAW = 1000 (θFC − θWP) Zr   (Eq. 82, Zr in m, TAW in mm)
RAW = p × TAW                 (Eq. 83)
p = p_table + 0.04 (5 − ETc) and is limited to 0.1–0.8.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import RAIN_IGNORE_FRACTION_OF_ET0
from .soil import PLANTS, available_water, crop_coefficient
from .units import inches_to_m

P_MIN = 0.1
P_MAX = 0.8


@dataclass(frozen=True)
class RootZone:
    """TAW, RAW, and the coefficients that produced them."""

    taw_mm: float
    raw_mm: float
    p: float
    awc: float
    zr_m: float
    kc: float
    etc_mm: float | None


@dataclass(frozen=True)
class BalanceUpdate:
    """Result of one daily bucket step."""

    deficit_mm: float
    deep_percolation_mm: float
    effective_precip_mm: float
    rain_ignored: bool
    etc_mm: float
    irrigation_mm: float


def adjusted_depletion_fraction(p_table: float, etc_mm: float | None) -> float:
    """FAO-56 depletion fraction. Without ETc the table value is only clamped."""
    if etc_mm is None:
        p = p_table
    else:
        p = p_table + 0.04 * (5.0 - etc_mm)
    return min(P_MAX, max(P_MIN, p))


def total_available_water_mm(awc: float, root_depth_in: float) -> float:
    """FAO-56 Eq. 82. ``awc`` is θFC − θWP and root depth is in inches."""
    if root_depth_in <= 0:
        raise ValueError("root depth must be positive")
    return 1000.0 * awc * inches_to_m(root_depth_in)


def root_zone(
    *,
    soil_type: str,
    plant_type: str,
    sun_exposure: str,
    root_depth_in: float,
    p_table: float | None,
    kc_override: float | None = None,
    awc_override: float | None = None,
    et0_mm: float | None = None,
    month: int | None = None,
) -> RootZone:
    """Build TAW and RAW for one zone from soil, plant, and today's ET0."""
    awc = available_water(soil_type, awc_override)
    kc = crop_coefficient(plant_type, sun_exposure, kc_override, month)
    etc = None if et0_mm is None else kc * et0_mm
    taw = total_available_water_mm(awc, root_depth_in)
    # A missing p uses the plant-table value. The FAO ET adjustment still runs.
    table_p = PLANTS[plant_type].p if p_table is None else p_table
    p = adjusted_depletion_fraction(table_p, etc)
    return RootZone(
        taw_mm=taw,
        raw_mm=p * taw,
        p=p,
        awc=awc,
        zr_m=inches_to_m(root_depth_in),
        kc=kc,
        etc_mm=etc,
    )


def apply_daily_balance(
    deficit_mm: float,
    taw_mm: float,
    *,
    etc_mm: float,
    precip_mm: float,
    et0_mm: float,
    irrigation_mm: float = 0.0,
    runoff_mm: float = 0.0,
    capillary_mm: float = 0.0,
) -> BalanceUpdate:
    """Advance the root-zone deficit by one day and clamp it to 0..TAW."""
    if deficit_mm < 0:
        raise ValueError("deficit cannot start below zero")
    if taw_mm <= 0:
        raise ValueError("TAW must be positive")
    rain_ignored = precip_mm < RAIN_IGNORE_FRACTION_OF_ET0 * max(et0_mm, 0.0)
    if rain_ignored:
        effective_precip = 0.0
    else:
        effective_precip = max(0.0, precip_mm - max(0.0, runoff_mm))
    # Eq. 85 without DP, then Eq. 88: DP is the negative excursion.
    raw_balance = (
        deficit_mm
        - effective_precip
        - max(0.0, irrigation_mm)
        - max(0.0, capillary_mm)
        + max(0.0, etc_mm)
    )
    if raw_balance < 0:
        deep_percolation = -raw_balance
        deficit = 0.0
    else:
        deep_percolation = 0.0
        deficit = min(raw_balance, taw_mm)
    return BalanceUpdate(
        deficit_mm=deficit,
        deep_percolation_mm=deep_percolation,
        effective_precip_mm=effective_precip,
        rain_ignored=rain_ignored,
        etc_mm=max(0.0, etc_mm),
        irrigation_mm=max(0.0, irrigation_mm),
    )


def clamp_deficit(deficit_mm: float, taw_mm: float) -> float:
    """Keep a stored deficit inside the root zone."""
    return min(taw_mm, max(0.0, deficit_mm))


def should_apply_balance(
    balance_date: str | None,
    today: str,
    hour: int,
    plan_hour: int,
    *,
    force: bool,
) -> bool:
    """Return whether today's ET and rain should be committed to the bucket.

    The evening job commits the day once. A manual calculate can commit it
    early. A second call the same day does not add ET again.
    """
    if balance_date == today:
        return False
    if force:
        return True
    return hour >= plan_hour


def zone_is_due(
    deficit_mm: float,
    raw_mm: float,
    taw_mm: float,
    etc_mm: float,
    *,
    days_ahead: int = 1,
) -> tuple[bool, str]:
    """Return whether to irrigate, and a short reason.

    Due when Dr ≥ RAW, or when Dr plus ``days_ahead`` of ETc (capped at TAW)
    would reach RAW before the next chance to water. Forecast rain is not
    subtracted here; a separate skip rule handles a wet forecast.
    """
    if deficit_mm >= raw_mm:
        return (
            True,
            (
                f"Water needed {deficit_mm:.1f} mm has reached the watering point "
                f"{raw_mm:.1f} mm."
            ),
        )
    projected = min(taw_mm, deficit_mm + max(0.0, days_ahead) * max(0.0, etc_mm))
    if projected >= raw_mm:
        return (
            True,
            (
                f"Water needed {deficit_mm:.1f} mm is under the watering point "
                f"{raw_mm:.1f} mm, but {days_ahead} day of water use would reach "
                f"{projected:.1f} mm."
            ),
        )
    return (
        False,
        (
            f"Not dry enough (water needed {deficit_mm:.1f} mm, "
            f"watering point {raw_mm:.1f} mm)."
        ),
    )
