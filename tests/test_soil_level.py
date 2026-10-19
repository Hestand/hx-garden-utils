"""A zone's soil water level can be set, and the read-only sensor follows it."""

from __future__ import annotations

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import UnitOfPrecipitationDepth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_DEPLETION,
    CONF_ELEVATION_M,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from custom_components.sprinklecast.store import SmartWaterStore
from custom_components.sprinklecast.units import inches_to_mm

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _zone(title: str, valve: str) -> dict:
    zone_id = title.casefold()
    return {
        "data": {
            CONF_PLANT_TYPE: "warm_season_turf",
            CONF_SOIL_TYPE: "clay_loam",
            CONF_SLOPE_PCT: 6,
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_ROOT_DEPTH_IN: 6,
            CONF_DEPLETION: 0.5,
            CONF_PRECIPITATION_RATE: 1.5,
            CONF_VALVE_ENTITY: valve,
        },
        "subentry_type": "zone",
        "title": title,
        "unique_id": zone_id,
        "subentry_id": zone_id,
    }


async def _setup(hass: HomeAssistant, *, hubs: int = 1) -> list[MockConfigEntry]:
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
    entries = []
    for index in range(hubs):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Garden" if index == 0 else "Other",
            data={CONF_WEATHER_ENTITY: "weather.home"},
            options={CONF_ELEVATION_M: 219.0, CONF_PLAN_HOUR: 23},
            subentries_data=[
                _zone("Front", "switch.front_valve"),
                _zone("Back", "switch.back_valve"),
            ],
        )
        entry.add_to_hass(hass)
        entries.append(entry)
    await Store(hass, 1, f"{DOMAIN}.{entries[0].entry_id}").async_save(
        {"zones": {"front": {"deficit_mm": 0.0, "learn_factor": 1.2}}}
    )
    for entry in entries:
        if entry.state is ConfigEntryState.NOT_LOADED:
            assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entries


def _entity(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def test_setting_soil_water_updates_the_sensor_plan_and_store(
    hass: HomeAssistant,
) -> None:
    """20% full writes 80% of TAW, including the learned factor, and rebuilds the plan."""
    entry = (await _setup(hass))[0]
    assert entry.state is ConfigEntryState.LOADED
    front = next(
        subentry.subentry_id
        for subentry in entry.subentries.values()
        if subentry.title == "Front"
    )
    back = next(
        subentry.subentry_id
        for subentry in entry.subentries.values()
        if subentry.title == "Back"
    )
    number_id = _entity(hass, "number", f"{entry.entry_id}_{front}_soil_water_level")
    sensor_id = _entity(hass, "sensor", f"{entry.entry_id}_{front}_soil_water")
    assert entry.runtime_data.data.zones[front].full_pct == pytest.approx(100, abs=0.2)
    assert entry.runtime_data.data.zones[front].scheduled is False

    await hass.services.async_call(
        NUMBER_DOMAIN,
        "set_value",
        {"entity_id": number_id, "value": 20},
        blocking=True,
    )
    zone = entry.runtime_data.data.zones[front]
    assert zone.full_pct == pytest.approx(20, abs=0.2)
    assert zone.deficit_mm == pytest.approx(zone.taw_mm * 0.8, rel=0.01)
    assert zone.learn_factor == pytest.approx(1.2)
    assert float(hass.states.get(sensor_id).state) == pytest.approx(zone.full_pct, abs=0.2)
    assert float(hass.states.get(number_id).state) == pytest.approx(zone.full_pct, abs=0.2)
    assert zone.scheduled is True
    assert zone.next_run is not None

    stored = entry.runtime_data.store.zone(front)
    assert stored["bucket_history"][-1]["set"] is True
    assert stored["bucket_history"][-1]["full_pct"] == pytest.approx(20, abs=0.2)
    assert stored["bucket_adjustments"][-1]["kind"] == "set"
    assert stored["bucket_adjustments"][-1]["full_pct"] == pytest.approx(20, abs=0.2)
    deficit_sensor = _entity(hass, "sensor", f"{entry.entry_id}_{front}_deficit")
    history = hass.states.get(deficit_sensor).attributes["history"]
    assert history[-1]["set"] is True
    assert hass.states.get(deficit_sensor).attributes["adjustments"][-1]["kind"] == "set"

    await entry.runtime_data.async_set_adjustment(front, 100)
    assert entry.runtime_data.store.zone(front)["bucket_history"][-1]["set"] is True
    assert entry.runtime_data.data.zones[front].full_pct == pytest.approx(20, abs=0.2)

    calendar_id = _entity(hass, "calendar", f"{entry.entry_id}_watering_calendar")
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar_id,
            "start_date_time": "2026-10-01T00:00:00-05:00",
            "end_date_time": "2027-10-01T00:00:00-05:00",
        },
        blocking=True,
        return_response=True,
    )
    events = response[calendar_id]["events"]
    assert any(event["summary"] == "Front" for event in events)

    await hass.services.async_call(
        DOMAIN,
        "set_soil_water_level",
        {"zone": "Back", "deficit_in": 0.5},
        blocking=True,
    )
    back_zone = entry.runtime_data.data.zones[back]
    assert back_zone.deficit_mm == pytest.approx(inches_to_mm(0.5), abs=0.05)
    back_sensor = _entity(hass, "sensor", f"{entry.entry_id}_{back}_soil_water")
    back_number = _entity(hass, "number", f"{entry.entry_id}_{back}_soil_water_level")
    assert float(hass.states.get(back_sensor).state) == pytest.approx(
        back_zone.full_pct, abs=0.2
    )
    assert float(hass.states.get(back_number).state) == pytest.approx(
        back_zone.full_pct, abs=0.2
    )

    await hass.services.async_call(
        DOMAIN,
        "set_soil_water_level",
        {"entity_id": back_sensor, "percent": 25},
        blocking=True,
    )
    assert entry.runtime_data.data.zones[back].full_pct == pytest.approx(25, abs=0.2)
    assert entry.runtime_data.data.zones[front].full_pct == pytest.approx(20, abs=0.2)

    await hass.services.async_call(
        DOMAIN,
        "set_soil_water_level",
        {"percent": 60},
        blocking=True,
    )
    assert entry.runtime_data.data.zones[front].full_pct == pytest.approx(60, abs=0.2)
    assert entry.runtime_data.data.zones[back].full_pct == pytest.approx(60, abs=0.2)

    reloaded = SmartWaterStore(hass, entry.entry_id)
    await reloaded.async_load()
    assert reloaded.zone(front)["deficit_mm"] == pytest.approx(
        entry.runtime_data.data.zones[front].deficit_mm, abs=0.05
    )
    assert reloaded.zone(front)["bucket_adjustments"][-1]["kind"] == "set"
    assert reloaded.zone(back)["bucket_history"][-1]["set"] is True


async def test_soil_water_service_rejects_a_mixed_or_ambiguous_target(
    hass: HomeAssistant,
) -> None:
    """Percent and deficit are alternatives, and two hubs need a name."""
    entry = (await _setup(hass, hubs=2))[0]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_soil_water_level",
            {"zone": "Front", "percent": 40, "deficit_mm": 5},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "set_soil_water_level",
            {"percent": 40},
            blocking=True,
        )
    await hass.services.async_call(
        DOMAIN,
        "set_soil_water_level",
        {"hub": "Garden", "zone": ["Front", "Back"], "percent": 80},
        blocking=True,
    )
    for zone in entry.runtime_data.data.zones.values():
        assert zone.full_pct == pytest.approx(80, abs=0.2)
    other = next(
        item
        for item in hass.config_entries.async_entries(DOMAIN)
        if item.title == "Other"
    )
    for zone in other.runtime_data.data.zones.values():
        assert zone.full_pct == pytest.approx(100, abs=0.2)

    hass.config.units = US_CUSTOMARY_SYSTEM
    assert (
        hass.config.units.accumulated_precipitation_unit
        == UnitOfPrecipitationDepth.INCHES
    )
    await hass.services.async_call(
        DOMAIN,
        "set_soil_water_level",
        {"hub": "Other", "zone": "Front", "deficit": 0.5},
        blocking=True,
    )
    other_front = other.runtime_data.data.zones["front"]
    assert other_front.deficit_mm == pytest.approx(inches_to_mm(0.5), abs=0.05)
