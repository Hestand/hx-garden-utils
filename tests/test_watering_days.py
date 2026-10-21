"""The schedule lists the next watering days, not seven calendar rows."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sprinklecast.planner import build_plan
from sprinklecast.schedule import wall_clock
from sprinklecast.solar import local_sunrise
from sprinklecast.week_plan import split_outlook, watering_day_limit
from tests.test_planner import _request, _zone
from tests.test_week_plan import _project

CHICAGO = ZoneInfo("America/Chicago")
LAT = 31.5493
LON = -97.1467
ELEV = 219.0
CARD = Path("custom_components/sprinklecast/frontend/sprinklecast-card.js")


def _due(**overrides: object):
    base = dict(
        name="Front",
        deficit_mm=25.0,
        raw_mm=10.0,
        etc_mm=8.0,
        taw_mm=80.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soak_override_min=30,
        max_cycle_override_min=7,
        min_interval_days=None,
        max_run_min=60,
    )
    base.update(overrides)
    return _zone(**base)


def _shown(zone, **overrides):
    project_args = dict(overrides)
    allowed = project_args.get("allowed_weekdays", ("mon", "wed", "fri"))
    horizon = project_args.pop("forecast_horizon_days", 2)
    limit = project_args.pop("watering_days", None)
    result = _project(zone, areas={zone.zone_id: 1000.0}, **project_args)
    week, outlook = split_outlook(
        result,
        timezone="America/Chicago",
        allowed_weekdays=allowed,
        forecast_horizon_days=horizon,
        watering_days=limit,
    )
    return result, week, outlook


def test_the_count_follows_the_allowed_weekdays() -> None:
    assert watering_day_limit(None) == 7
    assert watering_day_limit(()) == 0
    assert watering_day_limit(("mon", "wed", "fri")) == 3


def test_three_allowed_days_are_the_next_three_watering_mornings() -> None:
    """Dry calendar days are left out, even when the next run is weeks away."""
    _result, week, _outlook = _shown(_due(), days=90, allowed_weekdays=("mon", "wed", "fri"))
    days = week["days"]
    assert [day["date"] for day in days] == ["2026-10-26", "2026-10-28", "2026-10-30"]
    assert week["summary"] == "Next watering Mon Oct 26, 5:00 AM"
    assert "~" not in str(week["summary"])
    assert "estimated" not in str(week["summary"]).lower()
    assert "estimated" not in str(week["markdown"]).lower()
    assert "Not dry enough" not in str(week["markdown"])
    assert "Not an allowed watering day" not in str(week["markdown"])
    assert days[0]["estimated"] is False
    assert days[1]["estimated"] is True
    assert days[2]["estimated"] is True
    first = days[0]
    assert first["start"] == "05:00"
    assert first["finish"]
    assert str(first["start_at"]).startswith("2026-10-26T05:00:00")
    zone = first["zones"][0]
    assert zone["name"] == "Front Yard" or zone["name"] == "Front"
    assert zone["scheduled"] is True
    assert zone["minutes"] > 0
    assert zone["mm"] > 0
    assert zone["inches"] > 0
    assert zone["gallons"] is not None and zone["gallons"] > 0
    assert zone["soak_min"] == 30
    assert zone["cycles"]
    assert zone["bursts"]
    burst = zone["bursts"][0]
    assert burst["cycle"] == 1
    assert burst["start"] and burst["end"]
    assert burst["minutes"] > 0
    assert "soak 30 min" in str(week["markdown"])
    assert "gal" in str(week["markdown"])
    # The bucket is refilled, so the later mornings are not another 25 mm.
    assert days[1]["zones"][0]["mm"] < days[0]["zones"][0]["mm"]
    assert days[1]["zones"][0]["mm"] < 25
    assert days[2]["zones"][0]["mm"] < days[0]["zones"][0]["mm"]


def test_every_day_lists_seven_watering_mornings_and_skips_the_dry_ones() -> None:
    result, week, _outlook = _shown(
        _due(), days=60, allowed_weekdays=None, watering_days=None
    )
    assert len(week["days"]) == 7
    dates = [day["date"] for day in week["days"]]
    assert dates[0] == "2026-10-25"
    assert all(day["zones"][0]["scheduled"] for day in week["days"])
    scheduled = [
        day["date"]
        for day in result["days"]
        if day["zones"][0]["scheduled"]
    ]
    assert len(scheduled) > 7
    assert scheduled[7] not in dates


def test_an_empty_selection_lists_no_watering_days() -> None:
    _result, week, _outlook = _shown(_due(), allowed_weekdays=())
    assert week["days"] == []
    assert week["summary"] == "No watering days in the next 365 days"


def test_a_month_out_monday_is_still_listed_and_marked_estimated() -> None:
    zone = _zone(
        name="Front",
        deficit_mm=1.0,
        raw_mm=20.0,
        etc_mm=0.2,
        taw_mm=80.0,
        min_interval_days=None,
        soak_override_min=0,
        max_cycle_override_min=30,
    )
    _result, week, _outlook = _shown(zone, days=365, allowed_weekdays=("mon",))
    assert len(week["days"]) == 1
    day = week["days"][0]
    assert day["estimated"] is True
    moment = datetime.fromisoformat(str(day["start_at"]))
    assert (moment.date() - date(2026, 10, 25)).days > 60
    assert week["summary"].startswith("Next watering ")
    assert moment.strftime("%b") in str(week["summary"])
    assert "estimated" not in str(week["summary"]).lower()
    assert str(day["date"]) in str(week["markdown"])


def test_the_zone_cap_limits_a_projected_day_and_the_bucket_continues() -> None:
    zone = _zone(
        name="Lawn",
        deficit_mm=80.0,
        raw_mm=8.0,
        etc_mm=2.0,
        taw_mm=120.0,
        precipitation_rate_in_hr=0.4,
        efficiency=1.0,
        soak_override_min=0,
        max_cycle_override_min=20,
        min_interval_days=None,
        max_run_min=60,
    )
    _result, week, _outlook = _shown(
        zone, days=10, allowed_weekdays=None, watering_days=3
    )
    first, second = week["days"][0], week["days"][1]
    assert first["zones"][0]["minutes"] <= 60
    assert second["zones"][0]["minutes"] <= 60
    assert first["zones"][0]["mm"] < 80
    assert "carries" in str(first["zones"][0]["note"])
    assert second["zones"][0]["scheduled"] is True
    assert second["zones"][0]["mm"] > 0
    burst_minutes = sum(burst["minutes"] for burst in first["zones"][0]["bursts"])
    assert burst_minutes == first["zones"][0]["minutes"]


def test_a_projected_day_does_not_start_before_the_hard_limit() -> None:
    zone = _zone(
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
        max_run_min=400,
    )
    _result, week, _outlook = _shown(
        zone,
        days=3,
        allowed_weekdays=None,
        watering_days=1,
        earliest_start="04:30:00",
    )
    day = week["days"][0]
    assert str(day["start"]).startswith("04:30")
    for burst in day["zones"][0]["bursts"]:
        hour, minute = (int(part) for part in str(burst["start"]).split(":")[:2])
        assert (hour, minute) >= (4, 30)
        assert hour < 9


def test_a_later_watering_day_uses_the_same_dynamic_plan() -> None:
    zone = _zone(
        name="Bed",
        deficit_mm=12.0,
        raw_mm=8.0,
        etc_mm=15.0,
        taw_mm=80.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soak_override_min=0,
        max_cycle_override_min=60,
        min_interval_days=None,
    )
    result, week, _outlook = _shown(
        zone,
        days=5,
        allowed_weekdays=None,
        watering_days=2,
        dynamic_start=True,
        latitude=LAT,
        longitude=LON,
        elevation_m=ELEV,
    )
    assert len(week["days"]) == 2
    shown = {day["date"]: day for day in week["days"]}
    compared = 0
    for row in result["days"]:
        if row["date"] not in shown:
            continue
        calendar = date.fromisoformat(str(row["date"]))
        sunrise = local_sunrise(LAT, LON, calendar, CHICAGO, ELEV)
        earliest = wall_clock(calendar, 4, 0, CHICAGO)
        start_at = wall_clock(calendar, 5, 0, CHICAGO)
        finish_by = wall_clock(calendar, 9, 0, CHICAGO)
        # The stored request is the original bucket. The projection's later
        # morning has already refilled, so compare clocks to that sunrise
        # rather than replaying the original deficit.
        direct = build_plan(
            _request(
                zone,
                start_at=start_at,
                finish_by=finish_by,
                earliest_start=earliest,
                dynamic_start=True,
                sunrise_at=sunrise,
            )
        )
        opened = datetime.fromisoformat(str(shown[row["date"]]["start_at"]))
        closed = datetime.fromisoformat(str(shown[row["date"]]["finish_at"]))
        assert opened >= earliest
        assert closed <= finish_by
        assert abs((closed - sunrise).total_seconds()) < 90 or opened == earliest
        if direct.timeline and row["offset"] == 0:
            assert opened == direct.timeline[0].start.astimezone(CHICAGO)
            assert closed == direct.timeline[-1].end.astimezone(CHICAGO)
        compared += 1
    assert compared == 2
    assert week["summary"].startswith("Next watering ")
    assert "estimated" not in str(week["summary"]).lower()


def test_two_zones_keep_their_cycles_and_the_soak_gap() -> None:
    front = _zone(
        name="Front",
        zone_id="front",
        deficit_mm=15.0,
        raw_mm=8.0,
        precipitation_rate_in_hr=1.5,
        soak_override_min=30,
        max_cycle_override_min=7,
        min_interval_days=None,
    )
    back = _zone(
        name="Back",
        zone_id="back",
        deficit_mm=12.0,
        raw_mm=8.0,
        precipitation_rate_in_hr=1.5,
        soak_override_min=30,
        max_cycle_override_min=7,
        min_interval_days=None,
    )
    result = _project(
        front,
        zones=(front, back),
        areas={"front": 800.0, "back": 600.0},
        allowed_weekdays=("sun",),
        days=3,
    )
    week, _outlook = split_outlook(
        result,
        timezone="America/Chicago",
        allowed_weekdays=("sun",),
        forecast_horizon_days=2,
    )
    assert len(week["days"]) == 1
    zones = {zone["zone_id"]: zone for zone in week["days"][0]["zones"]}
    assert set(zones) == {"front", "back"}
    assert all(zone["soak_min"] == 30 for zone in zones.values())
    assert all(zone["gallons"] is not None for zone in zones.values())
    assert zones["front"]["bursts"][0]["soak_min"] == 30
    assert zones["front"]["bursts"][-1]["soak_min"] == 0
    timed = sorted(
        (
            (str(burst["start"]), zone["zone_id"])
            for zone in week["days"][0]["zones"]
            for burst in zone["bursts"]
        ),
        key=lambda item: item[0],
    )
    assert [zone_id for _start, zone_id in timed[:4]] == ["front", "back", "front", "back"]


def test_the_card_renders_each_watering_day_without_estimate_wording() -> None:
    text = CARD.read_text(encoding="utf-8")
    assert "_appendDay" in text
    assert "day.zones" in text
    assert "zone.minutes" in text
    assert "day.date" in text
    assert "day.start" in text
    assert "estimated" not in text.lower()
