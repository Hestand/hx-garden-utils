"""Load a hub under Home Assistant and confirm services do not actuate."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, ServiceRegistry
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
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
    CONF_SPRINKLER_TYPE,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    MODE_AUTO,
)
from custom_components.sprinklecast.store import SmartWaterStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _patch_valve(monkeypatch: pytest.MonkeyPatch, hass: HomeAssistant) -> list[str]:
    """Record switch calls for the zone valve and set its state. Other calls pass through."""
    calls: list[str] = []
    original = ServiceRegistry.async_call

    async def fake(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        data = service_data or {}
        entity = data.get("entity_id")
        if entity == "switch.front_valve" and domain == "switch":
            calls.append(service)
            hass.states.async_set(entity, "on" if service == "turn_on" else "off")
            return None
        return await original(
            self,
            domain,
            service,
            service_data,
            blocking,
            context,
            target,
            return_response,
        )

    monkeypatch.setattr(ServiceRegistry, "async_call", fake)
    return calls


async def _instant_sleep(_seconds: float) -> None:
    return None


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
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
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
    assert snapshot.automatic is False
    assert "automatic watering is off" in snapshot.block_reason
    assert snapshot.round_minutes is True

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    unique_ids = {item.unique_id for item in entities}
    assert any(item.endswith("_rain_today") for item in unique_ids)
    assert any(item.endswith("_schedule") for item in unique_ids)
    zone_id = next(iter(entry.subentries))
    assert f"{entry.entry_id}_{zone_id}_zone_plan" in unique_ids
    assert f"{entry.entry_id}_{zone_id}_soil_water" in unique_ids
    assert f"{entry.entry_id}_{zone_id}_deficit" in unique_ids
    assert f"{entry.entry_id}_et0" in unique_ids
    by_uid = {item.unique_id: item for item in entities}
    assert by_uid[f"{entry.entry_id}_et0"].entity_category is EntityCategory.DIAGNOSTIC
    assert by_uid[f"{entry.entry_id}_{zone_id}_raw"].entity_category is EntityCategory.DIAGNOSTIC
    assert by_uid[f"{entry.entry_id}_{zone_id}_soil_water"].entity_category is None
    assert by_uid[f"{entry.entry_id}_{zone_id}_last_run"].entity_category is None
    assert by_uid[f"{entry.entry_id}_water_use"].entity_category is None
    assert f"{entry.entry_id}_{zone_id}_flow" not in unique_ids
    assert f"{entry.entry_id}_{zone_id}_moisture" not in unique_ids
    assert f"{entry.entry_id}_{zone_id}_learned_gpm" not in unique_ids
    assert f"{entry.entry_id}_{zone_id}_last_run_gpm" not in unique_ids
    assert f"{entry.entry_id}_{zone_id}_adjustment" in unique_ids
    assert f"{entry.entry_id}_{zone_id}_soil_water_level" in unique_ids
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
    zone = entry.runtime_data.data.zones[zone_id]
    assert zone.adjustment_pct == 50
    assert zone.runtime_min == 16
    assert zone.scheduled is True
    calls = _patch_valve(monkeypatch, hass)
    entry.runtime_data.executor._sleep = _instant_sleep

    await hass.services.async_call(
        DOMAIN,
        "run_now",
        {"zone": "Front"},
        blocking=True,
    )
    await hass.async_block_till_done()
    task = entry.runtime_data.executor._task
    if task is not None:
        await task
    await hass.async_block_till_done()

    zone = entry.runtime_data.data.zones[zone_id]
    assert zone.valve_entity == "switch.front_valve"
    assert zone.last_run is not None
    assert zone.last_run["result"] == "ok"
    assert calls[0] == "turn_on"
    assert calls[-1] == "turn_off"
    assert hass.states.get("switch.front_valve").state == "off"

    plan_entity = next(
        item for item in entities if item.unique_id.endswith("_zone_plan")
    )
    plan_state = hass.states.get(plan_entity.entity_id)
    assert plan_state is not None
    assert plan_state.state == "idle"
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
    assert reloaded.zone(zone_id)["deficit_mm"] == pytest.approx(9.84, abs=0.05)
    assert reloaded.zone(zone_id)["adjustment_pct"] == 50
    assert reloaded.zone(zone_id)["last_run_now"]
    assert reloaded.weather["date"]

    rain = next(item for item in entities if item.unique_id.endswith("_rain_today"))
    assert hass.states.get(rain.entity_id).attributes["source"] in {
        "none",
        "forecast",
        "sensor",
    }


def _loaded_garden(hass: HomeAssistant, **entry_kwargs: Any) -> MockConfigEntry:
    extra_options = dict(entry_kwargs.pop("options", {}))
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
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_DRY_RUN: False,
            CONF_MODE: MODE_AUTO,
            CONF_SUNRISE_BUFFER_MIN: 30,
            CONF_PLAN_HOUR: 23,
            **extra_options,
        },
        **entry_kwargs,
    )
    entry.add_to_hass(hass)
    return entry


async def test_v1_entry_migrates_without_changing_stored_overrides(
    hass: HomeAssistant,
) -> None:
    """Version 3 keeps the numbers a v0.2 form already saved, including efficiency 1."""
    entry = _loaded_garden(
        hass,
        version=1,
        minor_version=1,
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
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 10
    assert entry.minor_version == 1
    zone = next(iter(entry.subentries.values()))
    assert zone.data[CONF_EFFICIENCY] == 1.0
    assert zone.data[CONF_PRECIPITATION_RATE] == 1.5
    assert zone.data[CONF_ROOT_DEPTH_IN] == 6


async def test_minimal_zone_plans_from_presets(hass: HomeAssistant) -> None:
    """A zone with only the quick-setup fields uses spray, loam, and St. Augustine."""
    entry = _loaded_garden(
        hass,
        version=2,
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "st_augustine",
                    CONF_SOIL_TYPE: "loam",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_VALVE_ENTITY: "switch.front_valve",
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
            }
        ],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN,
        "set_bucket",
        {"zone": "Front", "deficit_mm": 20},
        blocking=True,
    )
    await hass.async_block_till_done()
    zone_id = next(iter(entry.subentries))
    zone = entry.runtime_data.data.zones[zone_id]
    # 20 mm at spray 1.25 in/hr and efficiency 0.60 is 63 whole minutes.
    # The nightly valve-on cap is 60, so the schedule keeps 60 and carries the rest.
    assert zone.runtime_min == 60
    assert sum(zone.cycles) <= 60
    assert zone.scheduled is True
    assert zone.precipitation_rate_in_hr == pytest.approx(1.25)
    assert zone.max_cycle_min == 24
    assert zone.soak_min == 30
    assert hass.states.get("switch.front_valve").state == "off"


async def test_v4_custom_days_survive_the_v5_bump(hass: HomeAssistant) -> None:
    """Version 5 must not run the schedule migration over days the user already chose."""
    from custom_components.sprinklecast.const import CONF_ALLOWED_WEEKDAYS

    entry = _loaded_garden(
        hass,
        version=4,
        minor_version=1,
        options={CONF_ALLOWED_WEEKDAYS: ["mon", "thu"]},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 10
    assert entry.options[CONF_ALLOWED_WEEKDAYS] == ["mon", "thu"]
    assert entry.options["start_time"] == "05:00:00"
    assert entry.options["finish_time"] == "09:00:00"
    assert entry.options["earliest_start"] == "04:00:00"
    assert entry.options["dynamic_start"] is False
    assert "sunrise_buffer_min" not in entry.options


async def test_v5_hub_cap_becomes_a_per_zone_default(hass: HomeAssistant) -> None:
    """An old all-zones cap becomes the per-zone default. The hub total stays off."""
    from custom_components.sprinklecast.const import (
        CONF_ALLOWED_WEEKDAYS,
        CONF_HUB_NIGHTLY_CAP_MIN,
        CONF_MAX_RUN_MIN,
        CONF_ZONE_MAX_RUN_MIN,
    )

    entry = _loaded_garden(
        hass,
        version=5,
        minor_version=1,
        options={
            CONF_ALLOWED_WEEKDAYS: ["mon", "thu"],
            CONF_MAX_RUN_MIN: 45,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 10
    assert entry.options[CONF_ZONE_MAX_RUN_MIN] == 45
    assert CONF_MAX_RUN_MIN not in entry.options
    assert CONF_HUB_NIGHTLY_CAP_MIN not in entry.options
    assert entry.options[CONF_ALLOWED_WEEKDAYS] == ["mon", "thu"]


async def test_v2_entry_migrates_without_rewriting_zones(hass: HomeAssistant) -> None:
    """Version 3 is a version bump. A 0.3 zone keeps the numbers it stored."""
    entry = _loaded_garden(
        hass,
        version=2,
        minor_version=1,
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "st_augustine",
                    CONF_SOIL_TYPE: "loam",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_EFFICIENCY: 1.0,
                    CONF_PRECIPITATION_RATE: 1.5,
                    CONF_VALVE_ENTITY: "switch.front_valve",
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
            }
        ],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 10
    zone = next(iter(entry.subentries.values()))
    assert zone.data[CONF_EFFICIENCY] == 1.0
    assert zone.data[CONF_PRECIPITATION_RATE] == 1.5


async def test_simulation_service_returns_a_week_and_does_not_actuate(
    hass: HomeAssistant,
) -> None:
    """The sensor, the button, and the service share one in-memory week."""
    from custom_components.sprinklecast.const import (
        CONF_AREA_SQFT,
        CONF_BUCKET,
        CONF_LATITUDE,
        CONF_LONGITUDE,
        CONF_SCENARIO,
        CONF_SIMULATION,
    )

    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    hass.states.async_set("switch.front_valve", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Play yard",
        version=3,
        data={CONF_SIMULATION: True},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_LATITUDE: 31.5493,
            CONF_LONGITUDE: -97.1467,
            CONF_DRY_RUN: False,
            CONF_MODE: MODE_AUTO,
            CONF_SUNRISE_BUFFER_MIN: 30,
            CONF_PLAN_HOUR: 23,
            CONF_SCENARIO: "hot_dry",
            CONF_BUCKET: "full",
        },
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "st_augustine",
                    CONF_SOIL_TYPE: "clay_loam",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_AREA_SQFT: 1000,
                    CONF_VALVE_ENTITY: "simulation.front_lawn",
                },
                "subentry_type": "zone",
                "title": "Front lawn",
                "unique_id": "front_lawn",
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    sensor_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_simulation"
    )
    button_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_simulate"
    )
    assert sensor_id is not None
    assert button_id is not None
    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state != "Not run"
    assert state.attributes["would_execute"] is False
    assert "Front lawn" in state.attributes["markdown"]
    assert hass.states.get("switch.front_valve").state == "off"
    assert hass.states.get("simulation.front_lawn") is None

    response = await hass.services.async_call(
        DOMAIN,
        "simulate",
        {
            "hub": "Play yard",
            "days": "- high_f: 100\n  low_f: 75\n  rain_in: 0\n",
            "bucket": "raw",
            "start_date": "2026-07-13",
        },
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    assert response["scenario_name"] == "Custom week"
    assert response["would_execute"] is False
    assert response["days"][0]["zones"][0]["waters"] is True
    assert "markdown" in response
    assert hass.states.get(sensor_id).attributes["scenario_name"] == "Custom week"
    assert hass.states.get("switch.front_valve").state == "off"

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": button_id},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get(sensor_id).attributes["scenario"] == "hot_dry"
    assert hass.states.get("switch.front_valve").state == "off"


async def test_live_hub_simulation_does_not_change_the_bucket(
    hass: HomeAssistant,
) -> None:
    """A real yard can be simulated in memory. The stored deficit stays put."""
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
    zone_id = next(iter(entry.subentries))
    before = entry.runtime_data.store.zone(zone_id)["deficit_mm"]
    response = await hass.services.async_call(
        DOMAIN,
        "simulate",
        {"scenario": "mild_spring", "bucket": "half", "start_date": "2026-04-06"},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    assert response["would_execute"] is False
    assert entry.runtime_data.store.zone(zone_id)["deficit_mm"] == before
    assert hass.states.get("switch.front_valve").state == "off"
