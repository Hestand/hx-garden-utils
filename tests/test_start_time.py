"""Short runs stay on the configured 05:00 start. Nov 5 and Jan 11 are CST.

Live hubs with start 05:00, finish 09:00, and earliest 04:00 were showing
Thu Nov 5 at 4:04, 4:11, 4:18, and 4:25 AM, and another morning at 4:25 AM.
Those clocks are 7-minute clay-loam spray cycles pulled forward so the soak
gaps would end at 09:00. The valve time fits in the window, so the start
stays 05:00. The day-of planner and the projection use that same rule.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smart_water.planner import build_plan, build_zone_request
from smart_water.presets import PLANTS
from smart_water.schedule import wall_clock
from smart_water.week_plan import describe_outlook, project_week
from tests.test_planner import _request

CHICAGO = ZoneInfo("America/Chicago")


def _clay_spray_zones():
    """Four generic spray zones on clay loam. Max cycle is 7 minutes."""
    zones = []
    for index, name in enumerate(("Front", "Back", "Side", "Park")):
        data = {
            "soil_type": "clay_loam",
            "plant_type": "warm_season_turf",
            "sun_exposure": "full_sun",
            "sprinkler_type": "spray",
            "priority": index + 1,
            "root_depth_in": PLANTS["warm_season_turf"].root_depth_in,
            "slope_pct": 2,
        }
        built = build_zone_request(
            zone_id=name.lower(),
            name=name,
            data=data,
            deficit_mm=1.0,
            et0_mm=4.0,
            month=11,
            days_since_water=10,
        )
        zones.append(
            replace(
                built,
                deficit_mm=round(built.raw_mm + 0.5, 2),
                min_interval_days=None,
                days_since_water=10,
            )
        )
    return tuple(zones)


def _project_morning(morning: datetime):
    evening = morning - timedelta(hours=6)
    zones = _clay_spray_zones()
    result = project_week(
        zones,
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
        areas={zone.zone_id: 1500.0 for zone in zones},
        days=2,
    )
    return zones, result


def test_short_runs_start_at_05_on_nov_5_and_jan_11() -> None:
    expected = {
        datetime(2026, 11, 5, 5, 0, tzinfo=CHICAGO): "Next watering Thu Nov 5, 5:00 AM",
        datetime(2027, 1, 11, 5, 0, tzinfo=CHICAGO): "Next watering Mon Jan 11, 5:00 AM",
    }
    for morning, sentence in expected.items():
        zones, result = _project_morning(morning)
        row = result["days"][0]
        assert row["date"] == morning.date().isoformat()
        clocks = []
        for zone in row["zones"]:
            assert zone["scheduled"] is True
            first = str(zone["starts"]).split(",")[0].strip()
            clocks.append(first)
            hour, minute = (int(part) for part in first.split(":"))
            assert (hour, minute) >= (5, 0)
            assert hour < 9
        assert clocks == ["05:00", "05:07", "05:14", "05:21"]
        outlook = describe_outlook(
            result["days"], timezone="America/Chicago", firm_days=0, horizon=2
        )
        assert outlook["summary"] == sentence
        assert "4:04" not in str(outlook["summary"])
        assert "~" not in str(outlook["summary"])
        for info in outlook["by_zone"].values():
            moment = info["at"]
            assert moment.utcoffset() == timedelta(hours=-6)
            assert moment.hour >= 5

        start = wall_clock(morning.date(), 5, 0, CHICAGO)
        finish = wall_clock(morning.date(), 9, 0, CHICAGO)
        earliest = wall_clock(morning.date(), 4, 0, CHICAGO)
        direct = build_plan(
            _request(*zones, start_at=start, finish_by=finish, earliest_start=earliest)
        )
        assert direct.timeline[0].start == start
        projected = outlook["by_zone"]["front"]["at"]
        assert projected == direct.timeline[0].start
