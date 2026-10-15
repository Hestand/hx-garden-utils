"""FAO-56 checkpoints and the design-site daily ET0 case."""

from __future__ import annotations

import math

import pytest

from smart_water.et import (
    ETInputs,
    atmospheric_pressure_kpa,
    daily_et0,
    extraterrestrial_radiation_mj,
    hargreaves_et0_mm,
    penman_monteith_et0_mm,
    saturation_vapor_pressure_kpa,
    slope_saturation_curve_kpa_c,
    wind_at_2m,
)


def test_saturation_vapor_pressure_matches_fao_table_values() -> None:
    # FAO-56 Eq. 11. Published checkpoints: 2.338 kPa at 20 °C, 3.168 at 25 °C.
    assert saturation_vapor_pressure_kpa(20) == pytest.approx(2.338, abs=0.001)
    assert saturation_vapor_pressure_kpa(25) == pytest.approx(3.168, abs=0.001)
    assert saturation_vapor_pressure_kpa(30) == pytest.approx(4.243, abs=0.001)


def test_slope_and_pressure_match_fao_examples() -> None:
    # Δ(25 °C) is 0.189 kPa/°C in the FAO tables.
    assert slope_saturation_curve_kpa_c(25) == pytest.approx(0.189, abs=0.001)
    # Eq. 7: 100 m → 100.1 kPa, 1800 m → 81.8 kPa.
    assert atmospheric_pressure_kpa(100) == pytest.approx(100.1, abs=0.05)
    assert atmospheric_pressure_kpa(1800) == pytest.approx(81.8, abs=0.1)
    # Design site, USGS 218.6 m, rounded to the 219 m default.
    assert atmospheric_pressure_kpa(219) == pytest.approx(98.74, abs=0.05)


def test_wind_at_two_meters_is_unchanged() -> None:
    assert wind_at_2m(3.0, 2.0) == pytest.approx(3.0)
    # Eq. 47 at 10 m is the standard 0.748 factor, within a percent.
    assert wind_at_2m(1.0, 10.0) == pytest.approx(0.748, abs=0.01)


def test_hargreaves_and_penman_for_central_texas_october() -> None:
    # 15 Oct, latitude 31.46 °N. Ra is computed from Eq. 21.
    ra = extraterrestrial_radiation_mj(31.46, 288)
    assert ra == pytest.approx(26.8, abs=0.1)
    hargreaves = hargreaves_et0_mm(28.0, 16.0, ra)
    assert hargreaves == pytest.approx(3.47, abs=0.02)

    # Humidity and wind are present, so the daily selector uses Penman-Monteith.
    # Radiation is estimated with Eq. 50 because no daily MJ sensor is set.
    penman = daily_et0(
        ETInputs(
            t_max_c=28.0,
            t_min_c=16.0,
            latitude_deg=31.46,
            day_of_year=288,
            elevation_m=219,
            rh_max_pct=80,
            rh_min_pct=40,
            wind_m_s=2.0,
            solar_w_m2=640,
        )
    )
    assert penman.method == "penman_monteith"
    assert penman.radiation == "hargreaves_estimate"
    assert penman.et0_mm == pytest.approx(3.73, abs=0.03)
    assert "W/m²" in penman.detail
    assert "not used" in penman.detail

    # The same temperatures with no humidity fall back to Hargreaves Eq. 52.
    fallback = daily_et0(
        ETInputs(
            t_max_c=28.0,
            t_min_c=16.0,
            latitude_deg=31.46,
            day_of_year=288,
            elevation_m=219,
        )
    )
    assert fallback.method == "hargreaves"
    assert fallback.et0_mm == pytest.approx(hargreaves, abs=0.001)


def test_measured_radiation_is_used_when_a_daily_total_is_supplied() -> None:
    estimated = daily_et0(
        ETInputs(
            t_max_c=28,
            t_min_c=16,
            latitude_deg=31.46,
            day_of_year=288,
            elevation_m=219,
            rh_mean_pct=60,
            wind_m_s=2,
        )
    )
    measured = daily_et0(
        ETInputs(
            t_max_c=28,
            t_min_c=16,
            latitude_deg=31.46,
            day_of_year=288,
            elevation_m=219,
            rh_mean_pct=60,
            wind_m_s=2,
            rs_mj_m2_day=22.0,
        )
    )
    assert measured.radiation == "measured"
    assert measured.et0_mm != pytest.approx(estimated.et0_mm, abs=0.05)


def test_penman_monteith_reference_arithmetic() -> None:
    # Eq. 6 with a hand-built numerator, G = 0.
    et0 = penman_monteith_et0_mm(
        rn_mj=10.0,
        t_mean_c=20.0,
        wind_2m_m_s=2.0,
        saturation_kpa=2.338,
        actual_kpa=1.169,
        slope_kpa_c=0.145,
        psychrometric_kpa_c=0.066,
    )
    numerator = 0.408 * 0.145 * 10 + 0.066 * (900 / 293) * 2 * (2.338 - 1.169)
    denominator = 0.145 + 0.066 * (1 + 0.34 * 2)
    assert et0 == pytest.approx(numerator / denominator, abs=1e-6)
    assert et0 > 0
    assert math.isfinite(et0)


def test_missing_temperature_does_not_invent_et0() -> None:
    result = daily_et0(
        ETInputs(
            t_max_c=None,
            t_min_c=20,
            latitude_deg=31.46,
            day_of_year=288,
            elevation_m=219,
        )
    )
    assert result.et0_mm is None
    assert result.method == "unavailable"
