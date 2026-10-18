"""Schedule rows are dated by the morning the valves open, not the evening before."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_water.const import (
    CONF_ALLOWED_WEEKDAYS,
    CONF_ELEVATION_M,
    CONF_MODE,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_SOAK_MIN,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    MODE_NOTIFY_ONLY,
)
from custom_components.smart_water.planner import build_plan
from custom_components.smart_water.week_plan import project_week
from tests.test_planner import _request, _zone

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CHICAGO = ZoneInfo("America/Chicago")
SATURDAY_EVENING = datetime(2026, 10, 24, 23, 0, tzinfo=CHICAGO)


def _project(zone, **overrides):
    settings = dict(
        zones=(zone,),
        now=SATURDAY_EVENING,
        latitude=31.5493,
        longitude=-97.1467,
        timezone="America/Chicago",
        sunrise_buffer_min=30,
        earliest_hour=None,
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
        max_run_min=None,
    )
    settings.update(overrides)
    return project_week(**settings)


def _morning_zone():
    """One cycle that opens after midnight and finishes just before sunrise."""
    return _zone(
        name="Test1",
        deficit_mm=12.0,
        raw_mm=8.0,
        precipitation_rate_in_hr=1.5,
        soak_override_min=0,
        max_cycle_override_min=60,
        min_interval_days=None,
    )


def test_morning_run_is_dated_the_day_the_valve_opens() -> None:
    """Saturday's 23:00 plan opens Sunday morning, so the row is Sunday."""
    result = _project(_morning_zone())
    days = result["days"]
    assert isinstance(days, list)
    first = days[0]
    zone = first["zones"][0]
    assert zone["scheduled"] is True
    assert first["date"] == "2026-10-25"
    assert zone["starts"]
    assert "2026-10-24" not in str(zone["starts"])
    assert "next 2026-10-25 Test1" in str(result["summary"])
    assert "| 2026-10-25 | Test1 |" in str(result["markdown"])
    assert "| 2026-10-24 | Test1 |" not in str(result["markdown"])


def test_allowed_day_is_the_morning_the_water_would_run() -> None:
    """A Sunday-morning open is 'sun', on a row dated Sunday, even from Saturday night."""
    blocked = _project(_morning_zone(), allowed_weekdays=("sat",))
    days = blocked["days"]
    assert isinstance(days, list)
    row = days[0]
    zone = row["zones"][0]
    assert zone["scheduled"] is False
    assert row["date"] == "2026-10-25"
    assert zone["reason"] == "Not an allowed watering day (sun)."

    allowed = _project(_morning_zone(), allowed_weekdays=("sun",))
    assert allowed["days"][0]["zones"][0]["scheduled"] is True
    assert allowed["days"][0]["date"] == "2026-10-25"


def test_a_sequence_that_starts_before_midnight_uses_that_start_date() -> None:
    """Soak time can open the valve the evening before sunrise.

    The row date and the allowed day follow that first cycle. A later cycle
    prints its own date so the two mornings are not mixed together.
    """
    sunday_sunrise = datetime(2026, 10, 25, 6, 30, tzinfo=CHICAGO)
    long_run = build_plan(_request(finish_by=sunday_sunrise))
    assert long_run.timeline
    first = long_run.timeline[0].start.astimezone(CHICAGO)
    last = long_run.timeline[-1].start.astimezone(CHICAGO)
    assert first.date().isoformat() == "2026-10-24"
    assert last.date().isoformat() == "2026-10-25"
    assert long_run.run_on.astimezone(CHICAGO).date().isoformat() == "2026-10-24"

    kept = build_plan(
        _request(finish_by=sunday_sunrise, allowed_weekdays=("sat",))
    )
    assert kept.zones[0].scheduled is True
    rejected = build_plan(
        _request(finish_by=sunday_sunrise, allowed_weekdays=("sun",))
    )
    assert rejected.zones[0].scheduled is False
    assert rejected.zones[0].reason == "Not an allowed watering day (sat)."
    assert rejected.run_on.astimezone(CHICAGO).date().isoformat() == "2026-10-24"

    week = _project(_zone(name="Front", min_interval_days=None))
    row = week["days"][0]
    assert row["date"] == "2026-10-24"
    starts = str(row["zones"][0]["starts"])
    assert "2026-10-25" in starts
    assert starts.split(", ")[0].count("-") == 0


def _live_entry(**options) -> MockConfigEntry:
    base = {
        CONF_ELEVATION_M: 219.0,
        CONF_MODE: MODE_NOTIFY_ONLY,
    }
    base.update(options)
    return MockConfigEntry(
        domain=DOMAIN,
        title="Watering Stuff",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        version=6,
        minor_version=1,
        options=base,
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "warm_season_turf",
                    CONF_SOIL_TYPE: "clay_loam",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_PRECIPITATION_RATE: 1.5,
                    CONF_SOAK_MIN: 0,
                    CONF_VALVE_ENTITY: "switch.test1",
                },
                "subentry_type": "zone",
                "title": "Test1",
                "unique_id": "test1",
            }
        ],
    )


def _freeze_saturday(monkeypatch: pytest.MonkeyPatch) -> None:
    def frozen_now(tz=None):
        if tz is None:
            return SATURDAY_EVENING
        return SATURDAY_EVENING.astimezone(tz)

    monkeypatch.setattr(dt_util, "now", frozen_now)


async def _load(hass: HomeAssistant, entry: MockConfigEntry):
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    hass.states.async_set(
        "weather.home",
        "clear-night",
        {
            "temperature": 70,
            "temperature_unit": "°F",
            "humidity": 40,
            "wind_speed": 3,
            "wind_speed_unit": "mph",
            "precipitation_unit": "in",
        },
    )
    hass.states.async_set("switch.test1", "off")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "set_bucket",
        {"zone": "Test1", "deficit_mm": 20},
        blocking=True,
    )
    await hass.async_block_till_done()
    return entry


def _sensor(hass: HomeAssistant, entry: MockConfigEntry, unique_id: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    return state


async def test_live_schedule_and_next_run_share_the_morning(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The schedule state, its table, and the next-run sensor all say Sunday.

    The dashboard card prints that next-run timestamp and this schedule state.
    """
    _freeze_saturday(monkeypatch)
    entry = await _load(hass, _live_entry())
    zone_id = next(iter(entry.subentries))
    schedule = _sensor(hass, entry, f"{entry.entry_id}_watering_schedule")
    next_run = _sensor(hass, entry, f"{entry.entry_id}_{zone_id}_next_run")
    assert "next 2026-10-25 Test1" in schedule.state
    assert "| 2026-10-25 | Test1 |" in schedule.attributes["markdown"]
    assert "| 2026-10-24 | Test1 |" not in schedule.attributes["markdown"]
    parsed = dt_util.parse_datetime(next_run.state)
    assert parsed is not None
    assert parsed.astimezone(CHICAGO).date().isoformat() == "2026-10-25"


async def test_live_allowed_day_names_the_morning(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saturday is allowed, but this cycle opens Sunday, so the note says sun."""
    _freeze_saturday(monkeypatch)
    entry = await _load(hass, _live_entry(**{CONF_ALLOWED_WEEKDAYS: ["sat"]}))
    schedule = _sensor(hass, entry, f"{entry.entry_id}_watering_schedule")
    row = schedule.attributes["days"][0]
    assert row["date"] == "2026-10-25"
    assert row["zones"][0]["reason"] == "Not an allowed watering day (sun)."
    assert entry.state is not None
