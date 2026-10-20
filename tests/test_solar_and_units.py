"""Sunrise anchor and unit conversions."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from sprinklecast.solar import next_sunrise, sunrise_utc
from sprinklecast.units import (
    depth_mm,
    pressure_kpa,
    rain_rate_mm_h,
    solar_parts,
    speed_m_s,
    temperature_c,
)


def test_known_sunrises_are_within_a_few_minutes() -> None:
    # New York, 21 Jun 2024, civil sunrise is about 09:25 UTC (5:25 AM EDT).
    nyc = sunrise_utc(40.7128, -74.0060, date(2024, 6, 21))
    assert nyc.hour == 9
    assert nyc.minute == pytest.approx(25, abs=3)
    # Design-site coordinates, 15 Oct 2026, about 7:34 AM CDT (12:34 UTC).
    site = sunrise_utc(31.46, -97.23, date(2026, 10, 15))
    assert site.hour == 12
    assert site.minute == pytest.approx(34, abs=5)


def test_next_sunrise_is_strictly_after_the_moment() -> None:
    moment = datetime(2026, 10, 15, 23, 0, tzinfo=timezone(timedelta(hours=-5)))
    rise = next_sunrise(31.46, -97.23, moment)
    assert rise > moment
    local = rise.astimezone(timezone(timedelta(hours=-5)))
    assert local.date().isoformat() == "2026-10-16"
    assert local.hour == 7


def test_unit_conversions() -> None:
    assert temperature_c(32, "°F") == pytest.approx(0.0)
    assert temperature_c(20, "°C") == pytest.approx(20.0)
    assert depth_mm(1, "in") == pytest.approx(25.4)
    assert depth_mm(2, "mm") == pytest.approx(2.0)
    assert speed_m_s(1, "m/s") == pytest.approx(1.0)
    assert speed_m_s(3.6, "km/h") == pytest.approx(1.0)
    assert pressure_kpa(1013.25, "hPa") == pytest.approx(101.325, abs=0.01)
    daily, instant = solar_parts(18.0, "MJ/m²")
    assert daily == pytest.approx(18.0)
    assert instant is None
    daily, instant = solar_parts(800, "W/m²")
    assert daily is None
    assert instant == pytest.approx(800)
    # A UV index is not a radiation total, and a missing unit is not assumed.
    assert solar_parts(8, None) == (None, None)
    assert temperature_c(20, None) is None
    assert temperature_c(20, "K") is None
    assert depth_mm(2, None) is None
    assert depth_mm(1, "cm") is None
    assert speed_m_s(1, None) is None
    assert pressure_kpa(1013, None) is None
    assert pressure_kpa(1013, "hPa") == pytest.approx(101.3)
    assert rain_rate_mm_h(1, "in/h") == pytest.approx(25.4)
    assert rain_rate_mm_h(1, "inches/hr") == pytest.approx(25.4)
    assert rain_rate_mm_h(2, "mm/h") == pytest.approx(2.0)
    assert rain_rate_mm_h(2, "MM/HR") == pytest.approx(2.0)
    assert rain_rate_mm_h(2, None) is None
    assert rain_rate_mm_h(5, "mm") is None
    assert rain_rate_mm_h(1, "in") is None
    assert rain_rate_mm_h(1, "gal/min") is None
