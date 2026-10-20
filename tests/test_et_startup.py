"""A restart must not lock today's water loss from sensors that have not loaded."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_HUMIDITY_SENSOR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRESSURE_SENSOR,
    CONF_SOAK_MIN,
    CONF_SOIL_TYPE,
    CONF_SOLAR_SENSOR,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    DOMAIN,
)
from custom_components.sprinklecast.coordinator import UNIT_STARTUP_GRACE

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CHICAGO = ZoneInfo("America/Chicago")
EVENING = datetime(2026, 10, 24, 22, 0, tzinfo=CHICAGO)


def _freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    def frozen_now(tz=None):
        if tz is None:
            return EVENING
        return EVENING.astimezone(tz)

    monkeypatch.setattr(dt_util, "now", frozen_now)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Sprinklers",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_TEMPERATURE_SENSOR: "sensor.temp",
            CONF_HUMIDITY_SENSOR: "sensor.humidity",
            CONF_WIND_SENSOR: "sensor.wind",
            CONF_PRESSURE_SENSOR: "sensor.pressure",
            CONF_SOLAR_SENSOR: "sensor.solar",
        },
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "warm_season_turf",
                    CONF_SOIL_TYPE: "clay_loam",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_PRECIPITATION_RATE: 1.5,
                    CONF_SOAK_MIN: 0,
                    CONF_VALVE_ENTITY: "switch.front",
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
            }
        ],
    )


def _climate(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            "temperature": 78,
            "temperature_unit": "°F",
            "humidity": 45,
            "wind_speed": 6,
            "wind_speed_unit": "mph",
            "precipitation_unit": "in",
        },
    )
    hass.states.async_set("sensor.temp", "78", {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.humidity", "55", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.wind", "8", {"unit_of_measurement": "mph"})
    hass.states.async_set("sensor.pressure", "29.9", {"unit_of_measurement": "inHg"})
    hass.states.async_set("sensor.solar", "640", {"unit_of_measurement": "W/m²"})
    hass.states.async_set("switch.front", "off")


def _hide_climate(hass: HomeAssistant) -> None:
    for entity_id in (
        "sensor.temp",
        "sensor.humidity",
        "sensor.wind",
        "sensor.pressure",
        "sensor.solar",
    ):
        hass.states.async_set(entity_id, "unavailable")


def _snapshot(entry: MockConfigEntry) -> dict[str, object]:
    coordinator = entry.runtime_data
    zone_id = next(iter(entry.subentries))
    zone = coordinator.data.zones[zone_id]
    past = [
        item
        for item in coordinator.store.et0_history
        if isinstance(item, dict) and item.get("date") != coordinator.store.et0_date
    ]
    later = coordinator._et_factors(
        coordinator._last_observation,
        EVENING.date(),
        coordinator.data.et0_mm,
    )
    return {
        "method": coordinator.data.et0_method,
        "et0": coordinator.data.et0_mm,
        "detail": coordinator.data.et0_detail,
        "p": zone.p,
        "raw": zone.raw_mm,
        "next": None if zone.next_run is None else zone.next_run.isoformat(),
        "past": past,
        "later": later[10],
    }


async def test_restart_waits_for_sensors_and_keeps_the_same_plan(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sensors that appear after startup must not leave a Hargreaves plan behind."""
    _freeze(monkeypatch)
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    _climate(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Front", "deficit_mm": 12}, blocking=True
    )
    coordinator = entry.runtime_data
    today = coordinator.store.et0_date
    past = [
        {"date": "2026-10-21", "mm": 4.0},
        {"date": "2026-10-22", "mm": 4.5},
        {"date": "2026-10-23", "mm": 5.0},
    ]
    today_row = [
        item
        for item in coordinator.store.et0_history
        if isinstance(item, dict) and item.get("date") == today
    ]
    coordinator.store.et0_history = past + today_row
    await coordinator.async_request_refresh()
    await hass.async_block_till_done()

    first = _snapshot(entry)
    assert first["method"] == "penman_monteith"
    assert "Hargreaves" not in str(first["detail"])
    assert first["next"] is not None
    assert [item["date"] for item in first["past"]] == [
        "2026-10-21",
        "2026-10-22",
        "2026-10-23",
    ]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _hide_climate(hass)
    hass.set_state(CoreState.not_running)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    held = _snapshot(entry)
    assert held["method"] == "penman_monteith"
    assert held["et0"] == first["et0"]
    assert held["p"] == first["p"]
    assert held["raw"] == first["raw"]
    assert held["next"] == first["next"]
    assert held["past"] == first["past"]
    assert held["later"] == first["later"]

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + UNIT_STARTUP_GRACE)
    await hass.async_block_till_done()
    still = _snapshot(entry)
    assert still["method"] == "penman_monteith"
    assert still["past"] == first["past"]
    assert still["next"] == first["next"]
    assert still["later"] == first["later"]

    _climate(hass)
    await hass.async_block_till_done()
    again = _snapshot(entry)
    assert again["method"] == "penman_monteith"
    assert again["et0"] == pytest.approx(first["et0"])
    assert again["p"] == pytest.approx(first["p"])
    assert again["raw"] == pytest.approx(first["raw"])
    assert again["next"] == first["next"]
    assert again["past"] == first["past"]
    assert again["later"] == pytest.approx(first["later"])


async def test_fallback_detail_names_the_configured_sensor(hass: HomeAssistant) -> None:
    """A real state with no usable humidity or wind says which sensor that was."""
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            "temperature": 78,
            "temperature_unit": "°F",
            "precipitation_unit": "in",
        },
    )
    hass.states.async_set("sensor.temp", "78", {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.humidity", "55")
    hass.states.async_set("sensor.wind", "8")
    hass.states.async_set("sensor.pressure", "29.9", {"unit_of_measurement": "inHg"})
    hass.states.async_set("sensor.solar", "640", {"unit_of_measurement": "W/m²"})
    hass.states.async_set("switch.front", "off")
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    detail = entry.runtime_data.data.et0_detail
    assert entry.runtime_data.data.et0_method == "hargreaves"
    assert "sensor.humidity" in detail
    assert "sensor.wind" in detail
    assert "were missing" in detail
