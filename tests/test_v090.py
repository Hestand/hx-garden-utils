"""Hub flow meter, conditional sensors, and the version 8 migration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_FLOW_KIND,
    CONF_FLOW_LEAK_RATIO,
    CONF_FLOW_LOW_RATIO,
    CONF_FLOW_SCOPE,
    CONF_FLOW_SENSOR,
    CONF_MODE,
    CONF_MOISTURE_KIND,
    CONF_MOISTURE_MODE,
    CONF_MOISTURE_SENSOR,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    EVENT_FLOW_ALERT,
    FLOW_SCOPE_IRRIGATION,
    FLOW_SCOPE_WHOLE,
    MODE_NOTIFY_ONLY,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _zone(index: int, **extra: object) -> dict:
    data = {
        CONF_PLANT_TYPE: "bermuda",
        CONF_SOIL_TYPE: "sand",
        CONF_SPRINKLER_TYPE: "rotor",
        CONF_SUN_EXPOSURE: "full_sun",
        CONF_PRECIPITATION_RATE: 0.5,
        CONF_VALVE_ENTITY: f"switch.zone_{index}",
        CONF_FLOW_LOW_RATIO: 0.4,
        CONF_FLOW_LEAK_RATIO: 1.8,
    }
    data.update(extra)
    return {
        "data": data,
        "subentry_type": "zone",
        "title": f"Zone {index + 1}",
        "unique_id": f"zone_{index + 1}",
    }


def _weather(hass: HomeAssistant) -> None:
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


async def test_six_zones_move_the_first_flow_meter_onto_the_hub(
    hass: HomeAssistant,
) -> None:
    """The live hub keeps its zones. The first real flow sensor becomes the hub meter."""
    _weather(hass)
    zones = [_zone(index) for index in range(6)]
    zones[0]["data"][CONF_FLOW_SENSOR] = ""
    zones[3]["data"][CONF_FLOW_SENSOR] = "sensor.main_flow"
    zones[3]["data"][CONF_FLOW_KIND] = "rate"
    zones[5]["data"][CONF_FLOW_SENSOR] = "sensor.later_flow"
    zones[5]["data"][CONF_FLOW_KIND] = "total"
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        version=7,
        minor_version=1,
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_MODE: MODE_NOTIFY_ONLY,
            CONF_PLAN_HOUR: 23,
        },
        subentries_data=zones,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 10
    assert entry.options["dynamic_start"] is False
    assert entry.options[CONF_FLOW_SENSOR] == "sensor.main_flow"
    assert entry.options[CONF_FLOW_KIND] == "rate"
    assert entry.options[CONF_FLOW_SCOPE] == FLOW_SCOPE_IRRIGATION
    for subentry in entry.subentries.values():
        assert CONF_FLOW_SENSOR not in subentry.data
        assert CONF_FLOW_KIND not in subentry.data
        assert subentry.data[CONF_PLANT_TYPE] == "bermuda"
        assert subentry.data[CONF_FLOW_LOW_RATIO] == 0.4
        assert subentry.data[CONF_FLOW_LEAK_RATIO] == 1.8
    assert len(list(entry.subentries)) == 6


async def test_moisture_and_flow_entities_follow_the_configured_sensors(
    hass: HomeAssistant,
) -> None:
    """No sensor means no diagnostic entity, and clearing one removes the registry row."""
    _weather(hass)
    hass.states.async_set("sensor.soil", "42", {"unit_of_measurement": "%"})
    hass.states.async_set("switch.zone_0", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_MODE: MODE_NOTIFY_ONLY,
            CONF_PLAN_HOUR: 23,
            CONF_FLOW_SENSOR: "sensor.main_flow",
            CONF_FLOW_KIND: "total",
            CONF_FLOW_SCOPE: FLOW_SCOPE_WHOLE,
        },
        subentries_data=[
            _zone(
                0,
                **{
                    CONF_MOISTURE_SENSOR: "sensor.soil",
                    CONF_MOISTURE_MODE: "off",
                    CONF_MOISTURE_KIND: "relative",
                },
            )
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    zone_id = next(iter(entry.subentries))
    registry = er.async_get(hass)
    moisture_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_moisture"
    )
    flow_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_flow_problem"
    )
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_flow"
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_learned_gpm"
        )
        is None
    )
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_flow_trend"
        )
        is None
    )
    last_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_last_run_gpm"
    )
    baseline_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_baseline_flow"
    )
    assert moisture_id and flow_id and last_id and baseline_id
    problem = hass.states.get(flow_id)
    assert problem is not None
    assert problem.state == "off"
    assert problem.attributes["device_class"] == "problem"
    assert problem.attributes["reason"] == "No baseline yet"
    moisture = hass.states.get(moisture_id)
    assert moisture is not None
    assert float(moisture.state) == pytest.approx(42)
    assert moisture.attributes["unit_of_measurement"] == "%"
    assert moisture.attributes["water_needed_mm"] is not None

    subentry = entry.subentries[zone_id]
    cleared = dict(subentry.data)
    cleared.pop(CONF_MOISTURE_SENSOR)
    hass.config_entries.async_update_subentry(entry, subentry, data=cleared)
    options = dict(entry.options)
    options.pop(CONF_FLOW_SENSOR)
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_moisture"
        )
        is None
    )
    for suffix in (
        "flow",
        "learned_gpm",
        "last_run_gpm",
        "baseline_flow",
        "flow_vs_baseline",
        "flow_trend",
    ):
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_{suffix}"
            )
            is None
        )
    assert (
        registry.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{entry.entry_id}_{zone_id}_flow_problem"
        )
        is None
    )


async def test_whole_home_meter_skips_idle_flow_and_credits_the_running_zone(
    hass: HomeAssistant,
) -> None:
    """House use is ignored. Gallons during a run belong to that zone only."""
    _weather(hass)
    hass.states.async_set("sensor.main_flow", "100", {"unit_of_measurement": "gal"})
    events: list = []
    hass.bus.async_listen(EVENT_FLOW_ALERT, lambda event: events.append(event))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_MODE: MODE_NOTIFY_ONLY,
            CONF_PLAN_HOUR: 23,
            CONF_FLOW_SENSOR: "sensor.main_flow",
            CONF_FLOW_KIND: "total",
            CONF_FLOW_SCOPE: FLOW_SCOPE_WHOLE,
        },
        subentries_data=[_zone(0), _zone(1)],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert events == []
    assert entry.runtime_data.store.flow_idle_alert_date is None

    coordinator = entry.runtime_data
    second = list(entry.subentries)[1]
    first = list(entry.subentries)[0]
    coordinator.executor.current_zone_id = second
    await coordinator._async_update_data()
    hass.states.async_set("sensor.main_flow", "105", {"unit_of_measurement": "gal"})
    snapshot = await coordinator._async_update_data()
    assert snapshot.zones[second].flow_delivered_gal == pytest.approx(5)
    assert snapshot.zones[first].flow_delivered_gal == pytest.approx(0)
    assert events == []


async def test_irrigation_meter_alerts_when_flow_moves_and_nothing_is_running(
    hass: HomeAssistant,
) -> None:
    _weather(hass)
    hass.states.async_set("sensor.main_flow", "3", {"unit_of_measurement": "gal/min"})
    events: list = []
    hass.bus.async_listen(EVENT_FLOW_ALERT, lambda event: events.append(event))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_MODE: MODE_NOTIFY_ONLY,
            CONF_PLAN_HOUR: 23,
            CONF_FLOW_SENSOR: "sensor.main_flow",
            CONF_FLOW_KIND: "rate",
            CONF_FLOW_SCOPE: FLOW_SCOPE_IRRIGATION,
        },
        subentries_data=[_zone(0)],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert any(event.data.get("kind") == "main_leak" for event in events)
    assert entry.runtime_data.store.flow_locked is False
