"""Load a hub under Home Assistant and confirm services do not actuate."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_water.const import (
    CONF_DEPLETION,
    CONF_DRY_RUN,
    CONF_EFFICIENCY,
    CONF_ELEVATION_M,
    CONF_MODE,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRIORITY,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    MODE_AUTO,
)
from custom_components.smart_water.store import SmartWaterStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_DRY_RUN: False,
            CONF_MODE: MODE_AUTO,
            CONF_SUNRISE_BUFFER_MIN: 30,
            CONF_PLAN_HOUR: 23,
        },
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "warm_season_turf",
                    CONF_SOIL_TYPE: "clay_loam",
                    CONF_SLOPE_PCT: 6,
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_ROOT_DEPTH_IN: 6,
                    CONF_DEPLETION: 0.5,
                    CONF_EFFICIENCY: 1.0,
                    CONF_PRIORITY: 1,
                    CONF_PRECIPITATION_RATE: 1.5,
                    CONF_VALVE_ENTITY: "switch.front_valve",
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
            }
        ],
    )


async def test_setup_exposes_plan_and_services_do_not_move_the_valve(
    hass: HomeAssistant,
) -> None:
    """A loaded hub publishes sensors and leaves the stored on/off entity alone."""
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            "temperature": 30,
            "temperature_unit": "°C",
            "humidity": 45,
            "wind_speed": 2.0,
            "wind_speed_unit": "m/s",
            "precipitation_unit": "mm",
        },
    )
    hass.states.async_set("switch.front_valve", "off")
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    snapshot = entry.runtime_data.data
    assert snapshot.would_execute is False
    assert "will not open valves" in snapshot.block_reason
    assert snapshot.round_minutes is True

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    unique_ids = {item.unique_id for item in entities}
    assert any(item.endswith("_rain_today") for item in unique_ids)
    assert any(item.endswith("_schedule") for item in unique_ids)
    zone_id = next(iter(entry.subentries))
    assert f"{entry.entry_id}_{zone_id}_zone_plan" in unique_ids
    assert f"{entry.entry_id}_{zone_id}_flow" in unique_ids
    assert f"{entry.entry_id}_{zone_id}_moisture" in unique_ids
    assert f"{entry.entry_id}_{zone_id}_adjustment" in unique_ids
    assert f"{entry.entry_id}_{zone_id}_run_now" in unique_ids

    await hass.services.async_call(
        DOMAIN,
        "set_bucket",
        {"zone": "Front", "deficit_mm": 20},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "set_adjustment",
        {"zone": "Front", "percent": 50},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "run_now",
        {"zone": "Front"},
        blocking=True,
    )
    await hass.async_block_till_done()

    zone = entry.runtime_data.data.zones[zone_id]
    assert zone.adjustment_pct == 50
    assert zone.runtime_min == 16
    assert zone.scheduled is True
    assert zone.valve_entity == "switch.front_valve"
    assert zone.last_run_now is not None
    assert "Not executed" in zone.last_run_now
    assert hass.states.get("switch.front_valve").state == "off"

    plan_entity = next(
        item for item in entities if item.unique_id.endswith("_zone_plan")
    )
    plan_state = hass.states.get(plan_entity.entity_id)
    assert plan_state is not None
    assert plan_state.state == "scheduled"
    assert plan_state.attributes["valve_entity"] == "switch.front_valve"

    await hass.services.async_call(
        DOMAIN, "pause_zone", {"zone": "Front", "days": 3}, blocking=True
    )
    paused = entry.runtime_data.data.zones[zone_id]
    assert paused.scheduled is False
    assert "Skipped until" in paused.reason

    stored = entry.runtime_data.store
    await stored.async_save()
    reloaded = SmartWaterStore(hass, entry.entry_id)
    await reloaded.async_load()
    assert reloaded.zone(zone_id)["deficit_mm"] == pytest.approx(20)
    assert reloaded.zone(zone_id)["adjustment_pct"] == 50
    assert reloaded.zone(zone_id)["last_run_now"]
    assert reloaded.weather["date"]

    rain = next(item for item in entities if item.unique_id.endswith("_rain_today"))
    assert hass.states.get(rain.entity_id).attributes["source"] in {
        "none",
        "forecast",
        "sensor",
    }
