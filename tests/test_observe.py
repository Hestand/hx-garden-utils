"""Daily accumulation of temperature, rain, and solar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from smart_water.observe import (
    fresh_day,
    note_rain,
    note_solar_w,
    note_temperature,
    observed_temperature_range,
    uv_index_to_w_m2,
)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 15, hour, minute, tzinfo=timezone.utc)


def test_temperature_tracks_the_daily_range() -> None:
    track = fresh_day("2026-10-15")
    note_temperature(track, 22.0)
    assert observed_temperature_range(track) is None
    note_temperature(track, 31.0)
    note_temperature(track, 18.0)
    assert observed_temperature_range(track) == (31.0, 18.0)


def test_daily_rain_replaces_and_cumulative_ignores_the_baseline() -> None:
    track = fresh_day("2026-10-15")
    note_rain(track, kind="daily_total", value_mm=4.0, at=_at(8))
    note_rain(track, kind="daily_total", value_mm=1.5, at=_at(9))
    assert track["rain_mm"] == pytest.approx(1.5)

    cumulative = fresh_day("2026-10-15")
    note_rain(cumulative, kind="cumulative", value_mm=100.0, at=_at(8))
    assert cumulative["rain_mm"] == 0
    note_rain(cumulative, kind="cumulative", value_mm=103.2, at=_at(10))
    assert cumulative["rain_mm"] == pytest.approx(3.2)
    note_rain(cumulative, kind="cumulative", value_mm=1.0, at=_at(11))
    assert cumulative["rain_mm"] == pytest.approx(3.2)


def test_rain_rate_uses_the_trapezoid_and_drops_long_gaps() -> None:
    track = fresh_day("2026-10-15")
    note_rain(track, kind="rate", value_mm=2.0, at=_at(8))
    note_rain(track, kind="rate", value_mm=4.0, at=_at(10))
    # Average 3 mm/h for 2 hours.
    assert track["rain_mm"] == pytest.approx(6.0)
    note_rain(track, kind="rate", value_mm=4.0, at=_at(10) + timedelta(hours=7))
    assert track["rain_mm"] == pytest.approx(6.0)


def test_solar_integral_and_uv_fallback() -> None:
    track = fresh_day("2026-10-15")
    note_solar_w(track, 100.0, _at(12))
    note_solar_w(track, 100.0, _at(13))
    # 100 W/m² for 1 hour is 0.36 MJ/m².
    assert track["solar_mj"] == pytest.approx(0.36)
    assert uv_index_to_w_m2(5) == pytest.approx(500.0)
    assert uv_index_to_w_m2(-1) == 0
