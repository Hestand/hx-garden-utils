"""Zone number writes that arrive together all have to persist."""

from __future__ import annotations

import asyncio

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from custom_components.sprinklecast.store import SmartWaterStore
from custom_components.sprinklecast.units import depth_to_inches, inches_to_depth

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_ZONES = ("bed", "front", "left", "back", "side", "right")


def _zone(title: str, zone_id: str) -> dict:
    return {
        "data": {
            CONF_PLANT_TYPE: "warm_season_turf",
            CONF_SOIL_TYPE: "clay_loam",
            CONF_SLOPE_PCT: 6,
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_ROOT_DEPTH_IN: 6,
            CONF_SPRINKLER_TYPE: "spray",
            CONF_PRECIPITATION_RATE: 1.5,
            CONF_VALVE_ENTITY: f"switch.{zone_id}_valve",
        },
        "subentry_type": "zone",
        "title": title,
        "unique_id": zone_id,
        "subentry_id": zone_id,
    }


async def test_six_catch_cup_depths_set_together_all_persist(
    hass: HomeAssistant,
) -> None:
    """Six number.set_value calls in one burst must each keep their depth."""
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
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={CONF_ELEVATION_M: 219.0},
        subentries_data=[
            _zone(zone_id.replace("_", " ").title(), zone_id) for zone_id in _ZONES
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    depths = {zone_id: 0.1 * (index + 1) for index, zone_id in enumerate(_ZONES)}
    entity_ids = {}
    for zone_id in _ZONES:
        entity_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{entry.entry_id}_{zone_id}_catch_cup_depth"
        )
        assert entity_id
        entity_ids[zone_id] = entity_id

    await asyncio.gather(
        *[
            hass.services.async_call(
                "number",
                "set_value",
                {ATTR_ENTITY_ID: entity_ids[zone_id], "value": depth},
                blocking=True,
            )
            for zone_id, depth in depths.items()
        ]
    )
    await hass.async_block_till_done()

    unit = hass.config.units.accumulated_precipitation_unit
    assert entry.runtime_data is coordinator
    saved: dict[str, float] = {}
    for zone_id, depth in depths.items():
        raw_in = depth_to_inches(depth, unit)
        depth_in = round(raw_in, 4)
        saved[zone_id] = depth_in
        number = hass.states.get(entity_ids[zone_id])
        assert number is not None
        assert number.state not in {"unknown", "unavailable"}
        assert float(number.state) == pytest.approx(round(inches_to_depth(depth_in, unit), 4))
        state = coordinator.store.zone(zone_id)
        assert state["catch_cup"]["depth_in"] == pytest.approx(depth_in)
        assert state["measured_precipitation_rate_in_hr"] == pytest.approx(
            round(raw_in / 15 * 60, 4)
        )
        assert entry.subentries[zone_id].data[CONF_PRECIPITATION_RATE] == pytest.approx(1.5)
    assert len(set(saved.values())) == 6

    reloaded = SmartWaterStore(hass, entry.entry_id)
    await reloaded.async_load()
    for zone_id, depth_in in saved.items():
        assert reloaded.zones[zone_id]["catch_cup"]["depth_in"] == pytest.approx(depth_in)
