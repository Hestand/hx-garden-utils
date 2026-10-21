"""Watering schedule attributes stay small enough for the recorder."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sprinklecast.week_plan import project_week, schedule_attributes, split_outlook
from tests.test_planner import _zone

CHICAGO = ZoneInfo("America/Chicago")
# Home Assistant skips recording attributes at 16 KB. Stay under 12 KB.
RECORDER_BUDGET = 12 * 1024


def _six_zone_week():
    now = datetime(2026, 10, 24, 23, 0, tzinfo=CHICAGO)
    names = (
        "Front lawn",
        "Back lawn",
        "Side strip",
        "Foundation shrubs",
        "Vegetable bed",
        "Shade bed",
    )
    zones = []
    areas = {}
    for index, name in enumerate(names):
        zone = _zone(
            zone_id=f"z{index}",
            name=name,
            deficit_mm=28.0,
            raw_mm=10.0,
            etc_mm=7.5,
            taw_mm=80.0,
            precipitation_rate_in_hr=1.5,
            efficiency=0.75,
            soak_override_min=30,
            max_cycle_override_min=4,
            min_interval_days=None,
            max_run_min=60,
            priority=index + 1,
        )
        zones.append(zone)
        areas[zone.zone_id] = 800.0 + index * 100
    result = project_week(
        tuple(zones),
        now=now,
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
        areas=areas,
        days=40,
        max_run_min=60,
    )
    week, _outlook = split_outlook(
        result,
        timezone="America/Chicago",
        allowed_weekdays=None,
        forecast_horizon_days=3,
    )
    return week


def test_six_zones_and_seven_days_stay_under_twelve_kilobytes() -> None:
    """Every allowed weekday, six zones, cycle-and-soak. The sensor stays small."""
    week = _six_zone_week()
    assert len(week["days"]) == 7
    assert len(week["days"][0]["zones"]) == 6
    attrs = schedule_attributes(
        list(week["days"]),
        window=str(week["window"]),
        alerts=["Front lawn: high flow", "Freeze warning through Tuesday morning."],
        week_gal=1234.5,
        saved_gal=88.2,
    )
    encoded = json.dumps(attrs).encode()
    assert len(encoded) < RECORDER_BUDGET
    day = attrs["days"][0]
    assert day["date"]
    assert day["start"]
    assert day["zones"][0]["minutes"]
    text = encoded.decode()
    assert "reason" not in text
    assert "bursts" not in text
    assert "markdown" not in text
    full = json.dumps(
        {
            "days": week["days"],
            "markdown": week["markdown"],
        }
    ).encode()
    assert len(full) > 16 * 1024
    assert "reason" in full.decode()
