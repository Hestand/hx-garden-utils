"""Dynamic start finishes at sunrise and never opens before Don't start before."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smart_water.cycle_soak import plan_cycles
from smart_water.planner import build_plan
from smart_water.schedule import elapsed_seconds, wall_clock
from smart_water.soil import default_soak_minutes
from smart_water.solar import local_sunrise
from smart_water.week_plan import project_week
from tests.test_planner import _request, _zone

CHICAGO = ZoneInfo("America/Chicago")
LAT = 31.5493
LON = -97.1467
ELEV = 219.0


def _short(**overrides: object):
    base = dict(
        name="Bed",
        deficit_mm=12.0,
        raw_mm=8.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soak_override_min=0,
        max_cycle_override_min=60,
        min_interval_days=None,
    )
    base.update(overrides)
    return _zone(**base)


def _long(**overrides: object):
    """A run whose wall span is longer than a 04:00–09:00 morning."""
    base = dict(
        name="Lawn",
        soil_type="sand",
        slope_pct=0,
        deficit_mm=40.0,
        raw_mm=5.0,
        precipitation_rate_in_hr=0.2,
        efficiency=1.0,
        soak_override_min=0,
        max_cycle_override_min=30,
        min_interval_days=None,
    )
    base.update(overrides)
    return _zone(**base)


def _clock(text: str) -> tuple[int, int]:
    hour, minute = text.split(":")
    return int(hour), int(minute)


def _bounds(day, earliest="04:00", start="05:00", finish="09:00"):
    from datetime import date

    year, month, dom = (int(part) for part in day.split("-"))
    calendar = date(year, month, dom)
    return (
        wall_clock(calendar, *_clock(earliest), CHICAGO),
        wall_clock(calendar, *_clock(start), CHICAGO),
        wall_clock(calendar, *_clock(finish), CHICAGO),
        local_sunrise(LAT, LON, calendar, CHICAGO, ELEV),
    )


def _plan(day, zone, *, dynamic, earliest="04:00", start="05:00", finish="09:00"):
    early, start_at, finish_by, sunrise = _bounds(day, earliest, start, finish)
    return build_plan(
        _request(
            zone,
            start_at=start_at,
            finish_by=finish_by,
            earliest_start=early,
            dynamic_start=dynamic,
            sunrise_at=sunrise if dynamic else None,
        )
    ), sunrise, early, finish_by


def _assert_not_before(plan, earliest) -> None:
    assert plan.timeline
    for event in plan.timeline:
        assert event.start >= earliest
        assert event.end <= plan.finish_by + timedelta(seconds=1)


def test_clay_family_soak_default_is_30_and_an_override_wins() -> None:
    for soil in ("clay", "clay_loam", "silt_loam_compact", "silt_loam", "loam", "sand"):
        assert default_soak_minutes(soil) == 30
    preset = plan_cycles(
        net_mm=20.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soil_type="clay_loam",
        slope_pct=6,
    )
    assert preset.soak_min == 30
    overridden = plan_cycles(
        net_mm=20.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soil_type="clay",
        slope_pct=6,
        soak_override_min=45,
    )
    assert overridden.soak_min == 45
    drip = plan_cycles(
        net_mm=20.0,
        precipitation_rate_in_hr=0.5,
        efficiency=1.0,
        soil_type="clay_loam",
        slope_pct=0,
        sprinkler_type="drip",
    )
    assert drip.soak_min == 0


def test_dynamic_off_keeps_the_fixed_start() -> None:
    plan, _sunrise, _early, finish = _plan("2026-11-05", _short(), dynamic=False)
    assert plan.timeline[0].start == plan.start_at
    assert plan.timeline[-1].end <= finish
    assert plan.zones[0].carried_min == 0
    assert "after sunrise" not in (plan.warning or "")


def test_fixed_start_never_opens_before_dont_start_before() -> None:
    """A start time earlier than the limit is raised, including a long catch-up."""
    plan, _sunrise, earliest, finish = _plan(
        "2026-11-05", _short(), dynamic=False, earliest="04:30", start="03:00"
    )
    assert plan.timeline[0].start == earliest
    assert plan.timeline[0].start > plan.start_at or plan.start_at == earliest
    _assert_not_before(plan, earliest)
    long_plan, _, long_earliest, long_finish = _plan(
        "2026-11-05",
        _long(),
        dynamic=False,
        earliest="04:30",
        start="03:00",
    )
    _assert_not_before(long_plan, long_earliest)
    assert long_plan.timeline[-1].end <= long_finish
    assert long_plan.zones[0].carried_min > 0
    assert "next allowed day" in (long_plan.warning or "").lower()


def test_dynamic_on_finishes_at_sunrise_when_it_fits() -> None:
    plan, sunrise, earliest, finish = _plan("2026-07-14", _short(), dynamic=True)
    assert plan.timeline[0].start > earliest
    assert plan.timeline[0].start > plan.start_at
    assert abs(elapsed_seconds(plan.timeline[-1].end, sunrise)) < 1
    assert plan.timeline[-1].end < finish
    assert plan.zones[0].carried_min == 0


def test_dynamic_on_uses_dont_start_before_and_may_pass_sunrise() -> None:
    """A span that would open too early starts at the limit and may pass sunrise."""
    plan, sunrise, earliest, finish = _plan(
        "2026-06-21",
        _short(deficit_mm=40.0, soak_override_min=30, max_cycle_override_min=10),
        dynamic=True,
        earliest="05:30",
    )
    assert plan.timeline[0].start == earliest
    assert plan.timeline[-1].end > sunrise
    assert plan.timeline[-1].end <= finish
    _assert_not_before(plan, earliest)
    assert "after sunrise" in (plan.warning or "")


def test_dynamic_on_defers_what_still_does_not_fit() -> None:
    plan, sunrise, earliest, finish = _plan(
        "2026-12-21", _long(soak_override_min=40), dynamic=True
    )
    _assert_not_before(plan, earliest)
    assert plan.timeline[0].start == earliest
    assert plan.timeline[-1].end <= finish
    assert plan.zones[0].carried_min > 0
    assert "next allowed day" in (plan.warning or "").lower()
    assert plan.timeline[-1].end >= sunrise or plan.timeline[-1].end == finish


def test_season_shift_moves_the_dynamic_start() -> None:
    summer, summer_rise, _, _ = _plan("2026-06-21", _short(), dynamic=True)
    winter, winter_rise, _, _ = _plan("2026-12-21", _short(), dynamic=True)
    assert abs(elapsed_seconds(summer.timeline[-1].end, summer_rise)) < 1
    assert abs(elapsed_seconds(winter.timeline[-1].end, winter_rise)) < 1
    def _minutes(moment: datetime) -> int:
        local = moment.astimezone(CHICAGO)
        return local.hour * 60 + local.minute

    start_gap = _minutes(summer.timeline[0].start) - _minutes(winter.timeline[0].start)
    rise_gap = _minutes(summer_rise) - _minutes(winter_rise)
    assert start_gap == rise_gap
    assert abs(rise_gap) >= 30
    assert summer.timeline[0].start >= summer.earliest_start
    assert winter.timeline[0].start >= winter.earliest_start


def test_dynamic_start_on_both_daylight_saving_mornings() -> None:
    """Sunrise is that calendar day's wall clock, not a fixed offset."""
    for day, offset in (("2026-03-08", -5), ("2026-11-01", -6)):
        plan, sunrise, earliest, finish = _plan(day, _short(), dynamic=True)
        opened = plan.timeline[0].start.astimezone(CHICAGO)
        ended = plan.timeline[-1].end.astimezone(CHICAGO)
        assert opened.utcoffset() == timedelta(hours=offset)
        assert ended.utcoffset() == timedelta(hours=offset)
        assert sunrise.utcoffset() == timedelta(hours=offset)
        assert abs(elapsed_seconds(plan.timeline[-1].end, sunrise)) < 1
        assert opened >= earliest
        assert ended <= finish
        assert opened.hour >= 4


def test_projection_uses_the_same_dynamic_rule_and_defers() -> None:
    zone = _long(soak_override_min=20)
    evening = datetime(2026, 11, 4, 23, 0, tzinfo=CHICAGO)
    result = project_week(
        (zone,),
        now=evening,
        timezone="America/Chicago",
        earliest_start="04:00:00",
        start_time="05:00:00",
        finish_time="09:00:00",
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
        areas={zone.zone_id: 1000.0},
        days=2,
        dynamic_start=True,
        latitude=LAT,
        longitude=LON,
        elevation_m=ELEV,
    )
    assert "don't start before 04:00" in str(result["window"])
    assert "sunrise" in str(result["window"])
    direct, sunrise, earliest, _finish = _plan("2026-11-05", zone, dynamic=True)
    first = result["days"][0]["zones"][0]
    first_clock = str(first["starts"]).split(",")[0].strip()
    assert first_clock == direct.timeline[0].start.astimezone(CHICAGO).strftime("%H:%M")
    assert direct.timeline[0].start == earliest
    assert "carries" in str(first["note"])
    # The next allowed morning catches up and still respects the same floor.
    second = result["days"][1]["zones"][0]
    if second["scheduled"]:
        hour, minute = (int(part) for part in str(second["starts"]).split(",")[0].split(":"))
        assert (hour, minute) >= (4, 0)
        assert hour < 9
    summer = project_week(
        (_short(),),
        now=datetime(2026, 6, 20, 23, 0, tzinfo=CHICAGO),
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
        days=1,
        dynamic_start=True,
        latitude=LAT,
        longitude=LON,
        elevation_m=ELEV,
    )
    winter = project_week(
        (_short(),),
        now=datetime(2026, 12, 20, 23, 0, tzinfo=CHICAGO),
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
        days=1,
        dynamic_start=True,
        latitude=LAT,
        longitude=LON,
        elevation_m=ELEV,
    )
    summer_start = str(summer["days"][0]["zones"][0]["starts"]).split(",")[0]
    winter_start = str(winter["days"][0]["zones"][0]["starts"]).split(",")[0]
    assert summer_start != winter_start
    assert summer_start >= "04:00"
    assert winter_start >= "04:00"
