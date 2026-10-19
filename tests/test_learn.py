"""Available-water learning stays inside 30 percent and skips wet days."""

from __future__ import annotations

from datetime import date

from sprinklecast.learn import should_learn, update_awc_factor


def test_a_wetter_sensor_raises_the_factor_slowly() -> None:
    # Model is half full (deficit == half of TAW). Sensor is full.
    factor, confidence, samples = update_awc_factor(1.0, 1.0, 10.0, 20.0, 0)
    assert factor == 1.0 + 0.05 * (1.0 - 0.5)
    assert samples == 1
    assert confidence < 1
    # A full sensor against a half-empty model steps past the 1.3 cap.
    capped, _confidence, count = update_awc_factor(1.29, 1.0, 20.0, 20.0, 13)
    assert capped == 1.3
    assert count == 14
    assert _confidence == 1


def test_rain_and_a_recent_watering_hold_the_factor() -> None:
    today = date(2026, 7, 14)
    assert should_learn(
        enabled=True,
        has_sensor=True,
        rain_today_mm=0,
        last_watered=None,
        today=today,
    )
    assert not should_learn(
        enabled=True,
        has_sensor=True,
        rain_today_mm=2.5,
        last_watered=None,
        today=today,
    )
    assert not should_learn(
        enabled=True,
        has_sensor=True,
        rain_today_mm=0,
        last_watered="2026-07-13",
        today=today,
    )
    assert not should_learn(
        enabled=False,
        has_sensor=True,
        rain_today_mm=0,
        last_watered=None,
        today=today,
    )
