"""Water on the last allowed morning before the soil crosses the watering point."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sprinklecast.planner import build_plan
from sprinklecast.week_plan import project_week
from tests.test_planner import _request, _zone

CHICAGO = ZoneInfo("America/Chicago")
# Monday evening. The first morning in the schedule is Tuesday 2026-10-20.
MONDAY_EVENING = datetime(2026, 10, 19, 18, 0, tzinfo=CHICAGO)
ALLOWED = ("tue", "thu", "sun")


def _quiet(**overrides):
    base = dict(
        name="Lawn",
        deficit_mm=8.0,
        raw_mm=12.0,
        taw_mm=40.0,
        etc_mm=5.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soak_override_min=0,
        max_cycle_override_min=30,
        min_interval_days=None,
    )
    base.update(overrides)
    return _zone(**base)


def _week(zone, **overrides):
    settings = dict(
        zones=(zone,),
        now=MONDAY_EVENING,
        timezone="America/Chicago",
        forecast_precip_mm=0.0,
        forecast_skip_mm=None,
        hub_rain_wet=False,
        mode="notify_only",
        automatic=False,
        allowed_weekdays=ALLOWED,
        blackout_start_hour=None,
        blackout_end_hour=None,
        whole_minutes=True,
        max_daily_runtime_min=None,
        areas={zone.zone_id: 1000.0},
        days=8,
        plan_hour=23,
    )
    settings.update(overrides)
    return project_week(**settings)


def _scheduled(result) -> list[str]:
    dates = []
    for day in result["days"]:
        zone = day["zones"][0]
        if zone["scheduled"]:
            dates.append(day["date"])
    return dates


def test_crossing_on_wednesday_waters_tuesday() -> None:
    """Tue/Thu/Sun. Wednesday would already be past, so Tuesday refills."""
    result = _week(_quiet(deficit_mm=8.0, etc_mm=5.0, raw_mm=12.0))
    assert _scheduled(result)[0] == "2026-10-20"
    reason = result["days"][0]["zones"][0]["reason"]
    assert "Watering early" in reason
    assert "watering point" in reason
    assert "Wed" in reason
    # Thursday can water later, after Tuesday's refill dries out again.
    # That row is a new crossing, not this Wednesday.
    thursday = next(day for day in result["days"] if day["date"] == "2026-10-22")
    assert "Wed" not in str(thursday["zones"][0]["reason"])


def test_thursday_morning_depends_on_the_plan_hour() -> None:
    """The evening plan hour crosses before Thursday's start, so water Tuesday.

    A plan hour after the start leaves Thursday morning still under the point.
    Thursday then waters, before that later loss, and Tuesday does not.
    """
    evening = _week(_quiet(deficit_mm=3.0, etc_mm=5.0, raw_mm=12.0), plan_hour=23)
    assert _scheduled(evening)[0] == "2026-10-20"
    assert "Thu" in evening["days"][0]["zones"][0]["reason"]

    morning = _week(_quiet(deficit_mm=2.0, etc_mm=3.0, raw_mm=10.0), plan_hour=6)
    dates = _scheduled(morning)
    assert "2026-10-20" not in dates
    assert dates[0] == "2026-10-22"
    thursday = next(day for day in morning["days"] if day["date"] == "2026-10-22")
    assert "Watering early" in thursday["zones"][0]["reason"]
    assert "Thu" in thursday["zones"][0]["reason"]


def test_no_crossing_before_sunday_does_not_water_early() -> None:
    result = _week(_quiet(deficit_mm=1.0, etc_mm=1.0, raw_mm=30.0, taw_mm=40.0))
    assert _scheduled(result) == []
    for day in result["days"]:
        assert "Watering early" not in str(day["zones"][0]["reason"])


def test_the_live_plan_uses_the_same_early_reason() -> None:
    """Diagnostics copies this reason from the plan and from the schedule days."""
    start = datetime(2026, 10, 20, 5, 0, tzinfo=CHICAGO)
    plan = build_plan(
        _request(
            _quiet(),
            start_at=start,
            earliest_start=datetime(2026, 10, 20, 4, 0, tzinfo=CHICAGO),
            finish_by=datetime(2026, 10, 20, 9, 0, tzinfo=CHICAGO),
            allowed_weekdays=ALLOWED,
            plan_hour=23,
        )
    )
    assert plan.zones[0].scheduled is True
    assert "on Wed" in plan.zones[0].reason
