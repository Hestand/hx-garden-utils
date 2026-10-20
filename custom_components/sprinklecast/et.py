"""Reference evapotranspiration (ET0).

Daily FAO-56 Penman-Monteith (Chapter 2) is used when humidity and wind are
available. Radiation is the measured daily total when a sensor provides one,
otherwise the Hargreaves radiation estimate (Eq. 50) inside Penman-Monteith.
Temperature-only days fall back to the Hargreaves ET0 equation (Eq. 52).

An instantaneous W/m² reading is not itself the daily total. The coordinator
integrates those samples (and a UV-index fallback) to MJ/m²/day and passes
that integral in as ``rs_mj_m2_day``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# FAO-56 constants.
SOLAR_CONSTANT_MJ = 0.0820  # Gsc, MJ m⁻² min⁻¹
STEFAN_BOLTZMANN = 4.903e-9  # σ, MJ K⁻⁴ m⁻² day⁻¹
ALBEDO = 0.23  # grass reference
LATENT_HEAT_MJ_KG = 2.45
# Interior coefficient for Eq. 50. Coastal sites are closer to 0.19.
HARGREAVES_KRS = 0.16
# Eq. 35 Angstrom coefficients when a local calibration is not available.
ANGSTROM_A = 0.25
ANGSTROM_B = 0.50

METHOD_PENMAN = "penman_monteith"
METHOD_HARGREAVES = "hargreaves"
METHOD_NONE = "unavailable"
RADIATION_MEASURED = "measured"
RADIATION_ESTIMATED = "hargreaves_estimate"
RADIATION_NONE = "none"


@dataclass(frozen=True)
class ETInputs:
    """Daily inputs. Missing optionals select the fallback."""

    t_max_c: float | None
    t_min_c: float | None
    latitude_deg: float | None
    day_of_year: int | None
    elevation_m: float
    rh_mean_pct: float | None = None
    rh_max_pct: float | None = None
    rh_min_pct: float | None = None
    wind_m_s: float | None = None
    wind_height_m: float = 2.0
    pressure_kpa: float | None = None
    rs_mj_m2_day: float | None = None
    solar_w_m2: float | None = None


@dataclass(frozen=True)
class ETResult:
    """One day's ET0, plus how it was produced."""

    et0_mm: float | None
    method: str
    radiation: str
    detail: str


def saturation_vapor_pressure_kpa(temperature_c: float) -> float:
    """FAO-56 Eq. 11, saturation vapor pressure e°(T) in kPa."""
    return 0.6108 * math.exp(17.27 * temperature_c / (temperature_c + 237.3))


def slope_saturation_curve_kpa_c(temperature_c: float) -> float:
    """FAO-56 Eq. 13, slope of the saturation curve Δ at temperature T."""
    vapor = saturation_vapor_pressure_kpa(temperature_c)
    return 4098.0 * vapor / (temperature_c + 237.3) ** 2


def atmospheric_pressure_kpa(elevation_m: float) -> float:
    """FAO-56 Eq. 7, atmospheric pressure from elevation."""
    return 101.3 * ((293.0 - 0.0065 * elevation_m) / 293.0) ** 5.26


def psychrometric_constant_kpa_c(pressure_kpa: float) -> float:
    """FAO-56 Eq. 8, psychrometric constant γ."""
    return 0.000665 * pressure_kpa


def wind_at_2m(wind_m_s: float, measurement_height_m: float) -> float:
    """FAO-56 Eq. 47, wind speed adjusted to 2 m."""
    if measurement_height_m <= 0.5:
        raise ValueError("wind sensor height must be above 0.5 m")
    if abs(measurement_height_m - 2.0) < 0.05:
        return wind_m_s
    return wind_m_s * 4.87 / math.log(67.8 * measurement_height_m - 5.42)


def extraterrestrial_radiation_mj(latitude_deg: float, day_of_year: int) -> float:
    """FAO-56 Eq. 21, extraterrestrial radiation Ra in MJ m⁻² day⁻¹.

    The FAO equations use a 365-day year. Day 366 is clamped.
    """
    if latitude_deg < -90 or latitude_deg > 90:
        raise ValueError(f"latitude {latitude_deg} is outside ±90")
    julian = min(max(day_of_year, 1), 365)
    phi = math.radians(latitude_deg)
    inverse_relative_distance = 1 + 0.033 * math.cos(2 * math.pi * julian / 365)
    declination = 0.409 * math.sin(2 * math.pi * julian / 365 - 1.39)
    sunset_argument = -math.tan(phi) * math.tan(declination)
    sunset_hour = math.acos(max(-1.0, min(1.0, sunset_argument)))
    return (
        (24 * 60 / math.pi)
        * SOLAR_CONSTANT_MJ
        * inverse_relative_distance
        * (
            sunset_hour * math.sin(phi) * math.sin(declination)
            + math.cos(phi) * math.cos(declination) * math.sin(sunset_hour)
        )
    )


def radiation_mm(radiation_mj: float) -> float:
    """Convert MJ m⁻² day⁻¹ to equivalent evaporation millimeters."""
    return radiation_mj / LATENT_HEAT_MJ_KG


def radiation_from_sunshine_mj(ra_mj: float, sunshine_fraction: float) -> float:
    """FAO-56 Eq. 35, solar radiation Rs from relative sunshine duration n/N.

    ``sunshine_fraction`` is n/N, from 0 (no sun) to 1 (clear all day). A
    cloudiness fraction from the simulation form is ``1 - sunshine_fraction``.
    """
    fraction = min(1.0, max(0.0, sunshine_fraction))
    return (ANGSTROM_A + ANGSTROM_B * fraction) * ra_mj


def solar_radiation_from_temperature_mj(
    t_max_c: float,
    t_min_c: float,
    ra_mj: float,
    k_rs: float = HARGREAVES_KRS,
) -> float:
    """FAO-56 Eq. 50, Rs estimated from the daily temperature range."""
    return k_rs * math.sqrt(max(0.0, t_max_c - t_min_c)) * ra_mj


def hargreaves_et0_mm(
    t_max_c: float,
    t_min_c: float,
    ra_mj: float,
) -> float:
    """FAO-56 Eq. 52, Hargreaves ET0 in mm day⁻¹. Ra is passed in MJ."""
    t_mean = (t_max_c + t_min_c) / 2.0
    return (
        0.0023
        * (t_mean + 17.8)
        * math.sqrt(max(0.0, t_max_c - t_min_c))
        * radiation_mm(ra_mj)
    )


def _actual_vapor_pressure_kpa(
    t_max_c: float,
    t_min_c: float,
    rh_mean_pct: float | None,
    rh_max_pct: float | None,
    rh_min_pct: float | None,
) -> tuple[float, float] | None:
    """Return (es, ea) in kPa, or None when humidity is missing.

    Pair of max/min relative humidity uses FAO-56 Eq. 17. A single mean
    relative humidity uses Eq. 19.
    """
    if rh_max_pct is not None and rh_min_pct is not None:
        ea = (
            saturation_vapor_pressure_kpa(t_min_c) * rh_max_pct
            + saturation_vapor_pressure_kpa(t_max_c) * rh_min_pct
        ) / 200.0
        es = (
            saturation_vapor_pressure_kpa(t_max_c)
            + saturation_vapor_pressure_kpa(t_min_c)
        ) / 2.0
        return es, max(0.0, ea)
    if rh_mean_pct is None:
        return None
    es = (
        saturation_vapor_pressure_kpa(t_max_c)
        + saturation_vapor_pressure_kpa(t_min_c)
    ) / 2.0
    return es, max(0.0, es * rh_mean_pct / 100.0)


def net_radiation_mj(
    t_max_c: float,
    t_min_c: float,
    actual_vapor_kpa: float,
    rs_mj: float,
    ra_mj: float,
    elevation_m: float,
) -> float:
    """FAO-56 Eq. 38–40, net radiation Rn. Soil heat flux is not included."""
    clear_sky = (0.75 + 2e-5 * elevation_m) * ra_mj
    shortwave = (1.0 - ALBEDO) * rs_mj
    if clear_sky <= 0:
        ratio = 0.0
    else:
        # FAO limits Rs/Rso to 1.
        ratio = min(1.0, rs_mj / clear_sky)
    t_max_k = t_max_c + 273.16
    t_min_k = t_min_c + 273.16
    longwave = (
        STEFAN_BOLTZMANN
        * ((t_max_k**4 + t_min_k**4) / 2.0)
        * (0.34 - 0.14 * math.sqrt(max(0.0, actual_vapor_kpa)))
        * (1.35 * ratio - 0.35)
    )
    return shortwave - longwave


def penman_monteith_et0_mm(
    rn_mj: float,
    t_mean_c: float,
    wind_2m_m_s: float,
    saturation_kpa: float,
    actual_kpa: float,
    slope_kpa_c: float,
    psychrometric_kpa_c: float,
    soil_heat_mj: float = 0.0,
) -> float:
    """FAO-56 Eq. 6, daily reference ET0 in mm day⁻¹. G is 0 for a daily step."""
    vapor_deficit = max(0.0, saturation_kpa - actual_kpa)
    numerator = (
        0.408 * slope_kpa_c * (rn_mj - soil_heat_mj)
        + psychrometric_kpa_c
        * (900.0 / (t_mean_c + 273.0))
        * wind_2m_m_s
        * vapor_deficit
    )
    denominator = slope_kpa_c + psychrometric_kpa_c * (1.0 + 0.34 * wind_2m_m_s)
    if denominator == 0:
        return 0.0
    return max(0.0, numerator / denominator)


def _ordered_temps(
    t_max_c: float | None, t_min_c: float | None
) -> tuple[float, float] | None:
    if t_max_c is None or t_min_c is None:
        return None
    if t_max_c < t_min_c:
        return t_min_c, t_max_c
    return t_max_c, t_min_c


def _missing_clause(missing: tuple[str, ...]) -> str:
    """Name the humidity and wind inputs that kept Penman-Monteith from running."""
    if not missing:
        return "Humidity or wind was missing"
    if len(missing) == 1:
        return f"{missing[0]} was missing"
    if len(missing) == 2:
        return f"{missing[0]} and {missing[1]} were missing"
    return f"{', '.join(missing[:-1])}, and {missing[-1]} were missing"


def daily_et0(inputs: ETInputs, *, missing: tuple[str, ...] = ()) -> ETResult:
    """Select Penman-Monteith or Hargreaves and return ET0 for one day.

    ``missing`` names the configured sensors that had no usable humidity or
    wind reading. The Hargreaves detail quotes those names.
    """
    temps = _ordered_temps(inputs.t_max_c, inputs.t_min_c)
    if (
        temps is None
        or inputs.latitude_deg is None
        or inputs.day_of_year is None
    ):
        return ETResult(
            None,
            METHOD_NONE,
            RADIATION_NONE,
            "Need daily high and low temperature, latitude, and day of year.",
        )
    t_max, t_min = temps
    ra = extraterrestrial_radiation_mj(inputs.latitude_deg, inputs.day_of_year)
    if ra <= 0:
        return ETResult(
            0.0,
            METHOD_HARGREAVES,
            RADIATION_NONE,
            "Extraterrestrial radiation is zero.",
        )

    humidity = _actual_vapor_pressure_kpa(
        t_max,
        t_min,
        inputs.rh_mean_pct,
        inputs.rh_max_pct,
        inputs.rh_min_pct,
    )
    solar_note = ""
    if inputs.solar_w_m2 is not None:
        solar_note = (
            f" Instantaneous solar {inputs.solar_w_m2:.0f} W/m² was recorded "
            "and not used as the daily total."
        )

    if humidity is not None and inputs.wind_m_s is not None:
        saturation, actual = humidity
        if inputs.rs_mj_m2_day is not None and inputs.rs_mj_m2_day > 0:
            rs = inputs.rs_mj_m2_day
            radiation = RADIATION_MEASURED
        else:
            rs = solar_radiation_from_temperature_mj(t_max, t_min, ra)
            radiation = RADIATION_ESTIMATED
        rn = net_radiation_mj(t_max, t_min, actual, rs, ra, inputs.elevation_m)
        pressure = (
            inputs.pressure_kpa
            if inputs.pressure_kpa is not None
            else atmospheric_pressure_kpa(inputs.elevation_m)
        )
        t_mean = (t_max + t_min) / 2.0
        et0 = penman_monteith_et0_mm(
            rn_mj=rn,
            t_mean_c=t_mean,
            wind_2m_m_s=wind_at_2m(inputs.wind_m_s, inputs.wind_height_m),
            saturation_kpa=saturation,
            actual_kpa=actual,
            slope_kpa_c=slope_saturation_curve_kpa_c(t_mean),
            psychrometric_kpa_c=psychrometric_constant_kpa_c(pressure),
        )
        return ETResult(
            et0,
            METHOD_PENMAN,
            radiation,
            (
                f"Penman-Monteith with {radiation.replace('_', ' ')} radiation "
                f"at {inputs.elevation_m:.0f} m.{solar_note}"
            ),
        )

    et0 = hargreaves_et0_mm(t_max, t_min, ra)
    return ETResult(
        et0,
        METHOD_HARGREAVES,
        RADIATION_ESTIMATED,
        (
            "Hargreaves fallback from temperature. "
            f"{_missing_clause(missing)}, so Penman-Monteith was not used."
            + solar_note
        ),
    )
