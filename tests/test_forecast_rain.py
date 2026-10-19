"""Forecast rain waits on probability times depth, and not for long."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sprinklecast.forecast_rain import (
    defer_days_before_today,
    defer_reason,
    expected_rain,
    freeze_message,
    upcoming_freeze,
)


def test_expected_rain_is_probability_times_depth_above_the_threshold() -> None:
    now = datetime(2026, 7, 14, 23, 0, tzinfo=timezone.utc)
    slots = [
        (now + timedelta(hours=6), 10.0, 70.0),
        (now + timedelta(hours=12), 20.0, 30.0),
        (now + timedelta(hours=60), 10.0, 90.0),
    ]
    rain = expected_rain(slots, now=now, hours=48, probability_min=60)
    assert rain.slots == 1
    assert rain.expected_mm == 7.0
    assert rain.probability_pct == 70.0


def test_defer_message_and_the_two_day_limit() -> None:
    message = defer_reason(
        expected_mm=10.16,
        probability_pct=70,
        probability_min=60,
        deficit_mm=8,
        threshold_mm=None,
        days_used=0,
        max_days=2,
    )
    assert message == "Deferred for forecast rain (70% / 0.4 in)."
    assert (
        defer_reason(
            expected_mm=10.16,
            probability_pct=70,
            probability_min=60,
            deficit_mm=8,
            threshold_mm=None,
            days_used=2,
            max_days=2,
        )
        is None
    )
    assert (
        defer_reason(
            expected_mm=2,
            probability_pct=40,
            probability_min=60,
            deficit_mm=8,
            threshold_mm=None,
            days_used=0,
            max_days=2,
        )
        is None
    )


def test_a_depth_threshold_can_defer_before_the_deficit_is_covered() -> None:
    message = defer_reason(
        expected_mm=3,
        probability_pct=65,
        probability_min=60,
        deficit_mm=12,
        threshold_mm=2.5,
        days_used=0,
        max_days=2,
    )
    assert message is not None
    assert message.startswith("Deferred for forecast rain")


def test_today_is_not_counted_twice() -> None:
    assert defer_days_before_today(1, "2026-07-14", "2026-07-14") == 0
    assert defer_days_before_today(1, "2026-07-14", "2026-07-15") == 1


def test_hard_freeze_message_differs_from_a_light_freeze() -> None:
    now = datetime(2026, 7, 14, 18, 0, tzinfo=timezone.utc)
    light = upcoming_freeze(
        [(now + timedelta(hours=12), 31.0)],
        now=now,
        hours=48,
        freeze_f=32,
        hard_f=28,
    )
    hard = upcoming_freeze(
        [(now + timedelta(hours=12), 26.0), (now + timedelta(hours=30), 30.0)],
        now=now,
        hours=48,
        freeze_f=32,
        hard_f=28,
    )
    assert light is not None and light.hard is False
    assert "Winterize" in freeze_message(light)
    assert hard is not None and hard.hard is True
    assert hard.low_f == 26.0
    assert "hard freeze" in freeze_message(hard)
    assert (
        upcoming_freeze(
            [(now + timedelta(hours=12), 40.0)],
            now=now,
            hours=48,
            freeze_f=32,
            hard_f=28,
        )
        is None
    )


def test_week_projection_defers_without_crediting_forecast() -> None:
    """Expected rain can postpone a morning. It never shrinks the soil deficit."""
    from zoneinfo import ZoneInfo

    from sprinklecast.week_plan import project_week
    from tests.test_planner import _zone

    zone = _zone(deficit_mm=10.0, raw_mm=8.0, taw_mm=24.0, etc_mm=5.0)
    result = project_week(
        (zone,),
        now=datetime(2026, 7, 13, 23, 0, tzinfo=ZoneInfo("America/Chicago")),
        timezone="America/Chicago",
        forecast_precip_mm=0.0,
        forecast_skip_mm=None,
        hub_rain_wet=False,
        mode="notify_only",
        automatic=False,
        allowed_weekdays=None,
        blackout_start_hour=None,
        blackout_end_hour=None,
        whole_minutes=True,
        max_daily_runtime_min=None,
        areas={"front": 1000.0},
        forecast_expected_mm=25.4,
        forecast_probability_pct=70.0,
        forecast_probability_min=60.0,
        forecast_defer_max=2,
        forecast_horizon_days=2,
        defer_days={"front": 0},
    )
    days = result["days"]
    assert isinstance(days, list)
    first = days[0]["zones"][0]
    assert first["scheduled"] is False
    assert first["reason"] == "Deferred for forecast rain (70% / 1.0 in)."
    assert "Deferred for forecast rain (70% / 1.0 in)." in str(result["markdown"])
    # The third morning is outside the 48-hour window, so the wait ends.
    assert days[2]["zones"][0]["scheduled"] is True
