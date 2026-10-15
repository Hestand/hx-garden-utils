"""Dry-run nightly plan: one valve, whole minutes, finish by sunrise."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from smart_water.balance import root_zone
from smart_water.planner import PlanRequest, ZoneRequest, build_plan
from smart_water.safety import EXECUTION_IMPLEMENTED, block_reason, would_execute


def _zone(**overrides: object) -> ZoneRequest:
    limits = root_zone(
        soil_type=str(overrides.get("soil_type", "clay_loam")),
        plant_type="warm_season_turf",
        sun_exposure="full_sun",
        root_depth_in=6,
        p_table=0.50,
        et0_mm=5.0,
    )
    base = dict(
        zone_id="front",
        name="Front Yard",
        soil_type="clay_loam",
        slope_pct=6.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        deficit_mm=20.0,
        taw_mm=limits.taw_mm,
        raw_mm=limits.raw_mm,
        etc_mm=limits.etc_mm or 0.0,
        kc=limits.kc,
        p=limits.p,
        enabled=True,
        rain_sensor_wet=False,
        skipped_until=None,
        priority=1,
    )
    base.update(overrides)
    return ZoneRequest(**base)  # type: ignore[arg-type]


def _request(*zones: ZoneRequest, **overrides: object) -> PlanRequest:
    finish = datetime(2026, 10, 16, 11, 45, tzinfo=timezone.utc)
    base = dict(
        zones=zones or (_zone(),),
        finish_by=finish,
        earliest_start=None,
        forecast_precip_mm=0.0,
        forecast_skip_mm=None,
        hub_rain_wet=False,
        mode="notify_only",
        automatic=False,
    )
    base.update(overrides)
    return PlanRequest(**base)  # type: ignore[arg-type]


def test_automatic_off_does_not_report_that_it_would_water() -> None:
    assert EXECUTION_IMPLEMENTED is True
    assert "automatic watering is off" in block_reason(automatic=False, mode="auto")
    assert would_execute(automatic=False, mode="auto") is False
    assert would_execute(automatic=True, mode="auto") is True
    assert would_execute(automatic=True, mode="off") is False
    plan = build_plan(_request())
    assert plan.would_execute is False
    assert plan.automatic is False
    assert plan.summary.startswith("PLANNED")
    assert "automatic watering is off" in plan.summary
    armed = build_plan(_request(automatic=True, mode="auto"))
    assert armed.would_execute is True
    assert armed.summary.startswith("AUTOMATIC")


def test_clay_loam_plan_uses_four_minute_cycles_and_ends_at_sunrise() -> None:
    plan = build_plan(_request())
    zone = plan.zones[0]
    assert zone.scheduled is True
    assert zone.max_cycle_min == 4
    assert zone.soak_min == 60
    assert zone.cycles
    assert all(minutes <= 4 for minutes in zone.cycles)
    assert all(isinstance(minutes, int) for minutes in zone.cycles)
    assert sum(zone.cycles) == zone.runtime_min
    assert plan.timeline[-1].end == plan.finish_by
    assert plan.timeline[0].start < plan.finish_by
    _assert_one_valve(plan.timeline)
    _assert_soaks(plan)


def test_zones_are_interleaved_during_soak_and_never_overlap() -> None:
    # Days-ahead is 0, so the deficit has to be past RAW (about 14.1 mm
    # for this clay loam) before the zone is scheduled.
    front = _zone(zone_id="front", name="Front Yard", priority=1, deficit_mm=20.0)
    bed = _zone(
        zone_id="bed",
        name="Bed",
        priority=2,
        deficit_mm=12.0,
        soil_type="sand",
        slope_pct=0,
        precipitation_rate_in_hr=0.5,
    )
    plan = build_plan(_request(front, bed))
    names = [event.zone_name for event in plan.timeline]
    assert "Front Yard" in names and "Bed" in names
    _assert_one_valve(plan.timeline)
    _assert_soaks(plan)
    # Sand's single cycle should sit inside the clay loam soak, not after
    # every clay cycle has finished.
    front_events = [event for event in plan.timeline if event.zone_id == "front"]
    bed_event = next(event for event in plan.timeline if event.zone_id == "bed")
    assert front_events[0].end <= bed_event.start
    if len(front_events) > 1:
        assert bed_event.end <= front_events[1].start


def test_zone_below_raw_is_not_scheduled() -> None:
    quiet = _zone(deficit_mm=1.0, etc_mm=0.5, raw_mm=14.0, taw_mm=24.0)
    plan = build_plan(_request(quiet))
    assert plan.timeline == ()
    assert plan.zones[0].scheduled is False
    assert "Below RAW" in plan.zones[0].reason
    assert "No zones scheduled" in plan.summary


def test_rain_sensor_and_forecast_skip() -> None:
    wet = build_plan(_request(hub_rain_wet=True))
    assert wet.timeline == ()
    assert "rain sensor" in wet.zones[0].reason
    forecast = build_plan(_request(forecast_precip_mm=10.0, forecast_skip_mm=6.0))
    assert forecast.timeline == ()
    assert "forecast rain" in forecast.zones[0].reason
    # No threshold means forecast rain does not skip.
    kept = build_plan(_request(forecast_precip_mm=10.0, forecast_skip_mm=None))
    assert kept.zones[0].scheduled is True


def test_skip_and_disabled_zone() -> None:
    skipped = build_plan(_request(_zone(skipped_until="2026-10-16")))
    assert skipped.timeline == ()
    assert "Skipped until 2026-10-16" in skipped.zones[0].reason
    disabled = build_plan(_request(_zone(enabled=False)))
    assert disabled.zones[0].scheduled is False
    assert disabled.zones[0].reason == "Zone is disabled."


def test_window_trim_scales_a_long_cycle() -> None:
    finish = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    earliest = finish - timedelta(minutes=30)
    # Sand at a low rate makes one long cycle, longer than the 30 minute window.
    zone = _zone(
        soil_type="sand",
        slope_pct=0,
        precipitation_rate_in_hr=0.2,
        deficit_mm=20.0,
    )
    plan = build_plan(
        _request(zone, finish_by=finish, earliest_start=earliest)
    )
    assert plan.warning is not None
    assert "trimmed" in plan.warning.lower()
    assert plan.timeline[-1].end == finish
    assert plan.zones[0].runtime_min <= 30
    _assert_one_valve(plan.timeline)


def test_closed_window_schedules_nothing() -> None:
    finish = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    plan = build_plan(
        _request(
            finish_by=finish,
            earliest_start=finish + timedelta(minutes=5),
        )
    )
    assert plan.timeline == ()
    assert plan.warning is not None
    assert "deadline" in plan.warning


def test_daily_runtime_cap_trims_before_scheduling() -> None:
    plan = build_plan(_request(max_daily_runtime_min=10))
    assert plan.zones[0].scheduled is True
    assert plan.zones[0].runtime_min <= 10
    assert plan.warning is not None
    assert "daily cap" in plan.warning


def test_adjustment_scales_runtime_and_zero_drops_the_zone() -> None:
    half = build_plan(_request(_zone(adjustment_pct=50)))
    assert half.zones[0].scheduled is True
    # 10 mm net at 1.5 in/hr rounds to 16 minutes.
    assert half.zones[0].runtime_min == 16
    stopped = build_plan(_request(_zone(adjustment_pct=0)))
    assert stopped.zones[0].scheduled is False
    assert stopped.zones[0].reason == "Adjustment percent is 0."


def test_allowed_weekday_skips_friday_and_keeps_thursday() -> None:
    friday = datetime(2026, 10, 16, 11, 45, tzinfo=timezone.utc)
    skipped = build_plan(
        _request(finish_by=friday, allowed_weekdays=("sun", "tue", "thu"))
    )
    assert skipped.zones[0].scheduled is False
    assert "fri" in skipped.zones[0].reason
    thursday = datetime(2026, 10, 15, 11, 45, tzinfo=timezone.utc)
    kept = build_plan(
        _request(finish_by=thursday, allowed_weekdays=("sun", "tue", "thu"))
    )
    assert kept.zones[0].scheduled is True


def test_drip_can_ignore_the_weekday_and_does_not_soak() -> None:
    friday = datetime(2026, 10, 16, 11, 45, tzinfo=timezone.utc)
    plan = build_plan(
        _request(
            _zone(sprinkler_type="drip", ignores_schedule=True),
            finish_by=friday,
            allowed_weekdays=("sun",),
        )
    )
    assert plan.zones[0].scheduled is True
    assert plan.zones[0].soak_min == 0


def test_blackout_clips_a_midday_deadline_back_to_morning() -> None:
    finish = datetime(2026, 10, 16, 11, 45, tzinfo=timezone.utc)
    plan = build_plan(
        _request(finish_by=finish, blackout_start_hour=10, blackout_end_hour=19)
    )
    assert plan.finish_by == datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
    assert plan.earliest_start == datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    assert plan.timeline[-1].end == plan.finish_by
    assert plan.warning is not None
    evening = datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc)
    late = build_plan(
        _request(finish_by=evening, blackout_start_hour=10, blackout_end_hour=19)
    )
    assert late.finish_by == evening
    assert late.earliest_start == datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc)


def test_fractional_runtime_stays_off_the_whole_minute_grid() -> None:
    plan = build_plan(_request(whole_minutes=False))
    assert plan.zones[0].runtime_min == pytest.approx(31.5)
    assert all(isinstance(minutes, float) for minutes in plan.zones[0].cycles)


def _assert_one_valve(timeline: tuple) -> None:
    ordered = sorted(timeline, key=lambda event: event.start)
    for previous, current in zip(ordered, ordered[1:]):
        assert previous.end <= current.start


def _assert_soaks(plan) -> None:
    by_zone: dict[str, list] = {}
    for event in plan.timeline:
        by_zone.setdefault(event.zone_id, []).append(event)
    soak = {zone.zone_id: zone.soak_min for zone in plan.zones}
    for zone_id, events in by_zone.items():
        events = sorted(events, key=lambda event: event.start)
        for previous, current in zip(events, events[1:]):
            gap = (current.start - previous.end).total_seconds() / 60
            assert gap + 1e-6 >= soak[zone_id]
