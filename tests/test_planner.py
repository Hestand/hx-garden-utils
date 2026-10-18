"""Dry-run morning plan: one valve, whole minutes, finish by the set time."""

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
    start = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    base = dict(
        zones=zones or (_zone(),),
        start_at=start,
        finish_by=finish,
        earliest_start=start,
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


def test_clay_loam_plan_uses_four_minute_cycles_and_starts_on_time() -> None:
    plan = build_plan(_request())
    zone = plan.zones[0]
    assert zone.scheduled is True
    assert zone.max_cycle_min == 4
    assert zone.soak_min == 60
    assert zone.cycles
    assert all(minutes <= 4 for minutes in zone.cycles)
    assert all(isinstance(minutes, int) for minutes in zone.cycles)
    assert sum(zone.cycles) == zone.runtime_min
    assert plan.timeline[0].start == plan.start_at
    assert plan.timeline[-1].end <= plan.finish_by
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


def test_window_overflow_carries_the_rest_of_a_long_cycle() -> None:
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
        _request(
            zone,
            start_at=earliest,
            finish_by=finish,
            earliest_start=earliest,
        )
    )
    assert plan.warning is not None
    assert "bucket" in plan.warning.lower()
    assert plan.timeline[-1].end == finish
    assert plan.timeline[0].start == earliest
    assert plan.zones[0].runtime_min <= 30
    assert plan.zones[0].carried_min > 0
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
    assert "finish" in plan.warning


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
    morning = thursday.replace(hour=0, minute=0, second=0, microsecond=0)
    kept = build_plan(
        _request(
            finish_by=thursday,
            start_at=morning,
            earliest_start=morning,
            allowed_weekdays=("sun", "tue", "thu"),
        )
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
    assert plan.timeline[-1].end <= plan.finish_by
    assert plan.timeline[0].start >= plan.earliest_start
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


def test_per_zone_cap_does_not_limit_the_other_zone() -> None:
    """One zone's 10-minute cap leaves the other zone at its full runtime."""
    front = _zone(zone_id="front", name="Front", max_run_min=10, priority=1)
    back = _zone(zone_id="back", name="Back", priority=2)
    plan = build_plan(_request(front, back, max_run_min=None))
    by_name = {zone.name: zone for zone in plan.zones}
    assert by_name["Front"].runtime_min <= 10
    assert by_name["Front"].carried_min > 0
    assert by_name["Back"].runtime_min > 10
    assert sum(event.duration_min for event in plan.timeline if event.zone_id == "back") > 10


def test_nightly_valve_cap_keeps_the_schedule_at_or_under_60() -> None:
    """A 63-minute sequence is trimmed to the cap and still ends by the finish time."""
    zone = _zone(
        soil_type="loam",
        slope_pct=0,
        precipitation_rate_in_hr=1.25,
        efficiency=0.60,
        deficit_mm=20.0,
        raw_mm=8.0,
        taw_mm=24.0,
        max_cycle_override_min=24,
        soak_override_min=30,
    )
    uncapped = build_plan(_request(zone))
    assert uncapped.zones[0].runtime_min == 63
    plan = build_plan(_request(zone, max_run_min=60))
    assert plan.zones[0].scheduled is True
    assert plan.zones[0].runtime_min == 60
    assert plan.zones[0].carried_min == pytest.approx(3)
    assert plan.zones[0].completed is False
    assert sum(event.duration_min for event in plan.timeline) <= 60
    assert plan.timeline[0].start == plan.start_at
    assert plan.timeline[-1].end <= plan.finish_by
    assert plan.warning is not None
    assert "capped at 60" in plan.warning


def test_three_zones_interleave_inside_the_nightly_cap() -> None:
    """One zone's soak is another's run, and the night stays within the valve cap."""
    front = _zone(
        zone_id="front",
        name="Front lawn",
        priority=1,
        deficit_mm=12.0,
        raw_mm=8.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        max_cycle_override_min=6,
        soak_override_min=30,
    )
    back = _zone(
        zone_id="back",
        name="Back lawn",
        priority=1,
        soil_type="sandy_loam",
        slope_pct=0,
        deficit_mm=8.0,
        raw_mm=5.0,
        precipitation_rate_in_hr=0.5,
        efficiency=1.0,
        max_cycle_override_min=12,
        soak_override_min=20,
        sprinkler_type="rotor",
    )
    bed = _zone(
        zone_id="bed",
        name="Shrub bed",
        priority=1,
        soil_type="loam",
        slope_pct=0,
        deficit_mm=6.0,
        raw_mm=4.0,
        precipitation_rate_in_hr=0.5,
        efficiency=1.0,
        max_cycle_override_min=10,
        soak_override_min=0,
        sprinkler_type="drip",
    )
    plan = build_plan(_request(front, back, bed, max_run_min=60))
    names = {event.zone_name for event in plan.timeline}
    assert names == {"Front lawn", "Back lawn", "Shrub bed"}
    assert sum(event.duration_min for event in plan.timeline) <= 60
    _assert_one_valve(plan.timeline)
    _assert_soaks(plan)
    front_events = [event for event in plan.timeline if event.zone_id == "front"]
    assert len(front_events) >= 2
    guest = next(event for event in plan.timeline if event.zone_id != "front")
    assert front_events[0].end <= guest.start
    assert guest.end <= front_events[1].start
    assert plan.timeline[0].start == plan.start_at
    assert plan.timeline[-1].end <= plan.finish_by


def test_hourly_wind_moves_the_finish_earlier_inside_the_window() -> None:
    finish = datetime(2026, 7, 14, 6, 30, tzinfo=timezone.utc)
    earliest = datetime(2026, 7, 14, 4, 0, tzinfo=timezone.utc)
    hourly = (
        (datetime(2026, 7, 14, 5, 0, tzinfo=timezone.utc), 8.0),
        (datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc), 14.0),
    )
    plan = build_plan(
        _request(
            _zone(wind_limit_mph=10),
            start_at=datetime(2026, 7, 14, 5, 0, tzinfo=timezone.utc),
            finish_by=finish,
            earliest_start=earliest,
            hourly_wind=hourly,
            max_run_min=60,
        )
    )
    assert plan.finish_by == datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)
    assert plan.timeline[-1].end <= plan.finish_by
    assert plan.timeline[0].start >= earliest
    assert plan.warning is not None
    assert "wind" in plan.warning.lower()


def test_a_short_run_starts_at_05_and_finishes_before_09() -> None:
    """A sequence that fits the preferred window does not slide earlier."""
    start = datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc)
    earliest = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
    finish = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
    zone = _zone(
        name="Test1",
        deficit_mm=12.0,
        raw_mm=8.0,
        soak_override_min=0,
        max_cycle_override_min=60,
    )
    plan = build_plan(
        _request(zone, start_at=start, earliest_start=earliest, finish_by=finish)
    )
    assert plan.zones[0].scheduled is True
    assert plan.timeline[0].start == start
    assert plan.timeline[-1].end < finish
    assert plan.timeline[-1].end > start
    assert plan.zones[0].carried_min == 0


def test_overflow_starts_at_04_and_carries_the_rest() -> None:
    """A soak sequence longer than 05:00–09:00 starts at 04:00 and stops at 09:00."""
    start = datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc)
    earliest = datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc)
    finish = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
    plan = build_plan(
        _request(start_at=start, earliest_start=earliest, finish_by=finish)
    )
    assert earliest <= plan.timeline[0].start < start
    assert plan.timeline[-1].end == finish
    assert plan.zones[0].carried_min > 0
    assert plan.zones[0].scheduled is True
    assert plan.warning is not None
    assert "bucket" in plan.warning.lower()


def test_priority_then_deficit_keeps_the_first_zone_when_the_window_is_short() -> None:
    """The higher priority runs. The same priority yields to the larger deficit."""
    start = datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc)
    finish = start + timedelta(minutes=10)
    first = _zone(
        zone_id="first",
        name="First",
        priority=1,
        deficit_mm=10.0,
        raw_mm=8.0,
        soak_override_min=0,
        max_cycle_override_min=60,
    )
    second = _zone(
        zone_id="second",
        name="Second",
        priority=2,
        deficit_mm=20.0,
        raw_mm=8.0,
        soak_override_min=0,
        max_cycle_override_min=60,
    )
    plan = build_plan(
        _request(
            first,
            second,
            start_at=start,
            earliest_start=start,
            finish_by=finish,
        )
    )
    by_name = {zone.name: zone for zone in plan.zones}
    assert by_name["First"].scheduled is True
    assert by_name["Second"].scheduled is False
    assert "morning window" in by_name["Second"].reason
    thirsty = _zone(
        zone_id="thirsty",
        name="Thirsty",
        priority=1,
        deficit_mm=20.0,
        raw_mm=8.0,
        soak_override_min=0,
        max_cycle_override_min=60,
    )
    light = _zone(
        zone_id="light",
        name="Light",
        priority=1,
        deficit_mm=10.0,
        raw_mm=8.0,
        soak_override_min=0,
        max_cycle_override_min=60,
    )
    ordered = build_plan(
        _request(
            light,
            thirsty,
            start_at=start,
            earliest_start=start,
            finish_by=finish,
        )
    )
    names = [event.zone_name for event in ordered.timeline]
    assert names
    assert names[0] == "Thirsty"


def test_allowed_day_uses_the_morning_the_valve_opens() -> None:
    start = datetime(2026, 10, 25, 5, 0, tzinfo=timezone.utc)
    finish = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
    zone = _zone(soak_override_min=0, max_cycle_override_min=60, deficit_mm=12.0, raw_mm=8.0)
    skipped = build_plan(
        _request(
            zone,
            start_at=start,
            earliest_start=start,
            finish_by=finish,
            allowed_weekdays=("sat",),
        )
    )
    assert skipped.zones[0].scheduled is False
    assert skipped.zones[0].reason == "Not an allowed watering day (sun)."
    assert skipped.run_on == start


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
