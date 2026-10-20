"""Daily climate totals are a property of the recorded series, not the clock."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sprinklecast.climate_day import apply_series, fresh_climate_day, note_climate

CHICAGO = ZoneInfo("America/Chicago")


def _at(hour: int) -> datetime:
    return datetime(2026, 10, 19, hour, 0, tzinfo=CHICAGO)


def _series() -> list[tuple[datetime, float]]:
    return [(_at(6), 0.0), (_at(10), 700.0), (_at(14), 900.0), (_at(18), 50.0), (_at(22), 0.0)]


def test_the_same_solar_series_integrates_to_the_same_total() -> None:
    start = _at(0)
    end = _at(23)
    first = fresh_climate_day("2026-10-19")
    second = fresh_climate_day("2026-10-19")
    apply_series(first, "solar_w", _series(), start, end)
    apply_series(second, "solar_w", list(reversed(_series())), start, end + timedelta(minutes=3))
    assert first["solar_mj"] == second["solar_mj"]
    assert first["solar_mj"] > 1.0


def test_a_repeated_sample_does_not_replace_the_stored_day() -> None:
    day = fresh_climate_day("2026-10-19")
    note_climate(day, "temperature", 20.0, _at(8))
    note_climate(day, "temperature", 30.0, _at(15))
    note_climate(day, "humidity", 80.0, _at(8))
    note_climate(day, "humidity", 40.0, _at(15))
    before = (day["t_max_c"], day["t_min_c"], day["rh_mean_pct"])
    note_climate(day, "temperature", 5.0, _at(15))
    note_climate(day, "humidity", 10.0, _at(15))
    assert (day["t_max_c"], day["t_min_c"], day["rh_mean_pct"]) == before


def test_a_locked_day_ignores_a_new_series() -> None:
    day = fresh_climate_day("2026-10-18")
    day["locked"] = True
    day["t_max_c"] = 28.0
    day["t_min_c"] = 16.0
    day["et0_mm"] = 4.0
    apply_series(day, "temperature", [(_at(12), 40.0), (_at(18), 10.0)], _at(0), _at(23))
    note_climate(day, "temperature", 1.0, _at(20))
    assert day["t_max_c"] == 28.0
    assert day["et0_mm"] == 4.0
