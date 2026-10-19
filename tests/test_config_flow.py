"""Config-flow forms must serialize the way the config HTTP API does.

Home Assistant 2026.10 turns a probatio.Invalid raised while building a step
into a plain ``400: Bad Request``. The hub, options, and zone forms are
checked by starting each flow and running the same serializer as
``homeassistant.helpers.data_entry_flow``.
"""

from __future__ import annotations

import json
from typing import Any

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.data_entry_flow import _BaseFlowManagerView
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_AREA_SQFT,
    CONF_BUCKET,
    CONF_DEPLETION,
    CONF_DRY_RUN,
    CONF_EFFICIENCY,
    CONF_ELEVATION_M,
    CONF_FLOW_KIND,
    CONF_FLOW_LOW_RATIO,
    CONF_FLOW_SCOPE,
    CONF_FLOW_SENSOR,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MODE,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRIORITY,
    CONF_ROOT_DEPTH_IN,
    CONF_SCENARIO,
    CONF_SIMULATION,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    MODE_NOTIFY_ONLY,
    SUBENTRY_ZONE,
)
from custom_components.sprinklecast.presets import plant_kc

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _check_steps(fields: list[dict[str, Any]]) -> None:
    for field in fields:
        if field.get("type") == "expandable":
            assert isinstance(field.get("schema"), list) and field["schema"]
            _check_steps(field["schema"])
            continue
        assert "selector" in field, field
        number = field["selector"].get("number")
        if number and "step" in number:
            step = number["step"]
            assert step == "any" or float(step) >= 0.001, field


def _serialize(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize a form with the config-flow HTTP view's serializer."""
    assert result["type"] is FlowResultType.FORM
    prepared = _BaseFlowManagerView._prepare_result_json(None, result)  # type: ignore[arg-type]
    fields = prepared["data_schema"]
    direct = probatio.to_field_list(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    assert fields == direct
    json.dumps(fields)
    assert isinstance(fields, list) and fields
    _check_steps(fields)
    return fields


def _field(fields: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for field in fields:
        if field["name"] == name:
            return field
        if field.get("type") == "expandable":
            try:
                return _field(field["schema"], name)
            except StopIteration:
                continue
    raise StopIteration(name)


def _hub_entry(**kwargs: Any) -> MockConfigEntry:
    options = {
        CONF_ELEVATION_M: 219.0,
        CONF_DRY_RUN: False,
        CONF_MODE: MODE_NOTIFY_ONLY,
        CONF_SUNRISE_BUFFER_MIN: 30,
        CONF_PLAN_HOUR: 23,
    }
    options.update(kwargs.pop("options", {}))
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options=options,
        **kwargs,
    )


def _sections() -> dict[str, dict[str, Any]]:
    return {"sensors": {}, "morning": {}, "location": {}}


async def _finish_with_no_zones(
    hass: HomeAssistant, result: dict[str, Any]
) -> dict[str, Any]:
    """Submit zero zones so a hub form ends in CREATE_ENTRY."""
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_count"
    _serialize(result)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"zones": 0},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result.get("next_flow") is None
    assert not result["result"].subentries
    return result


async def _open_live(hass: HomeAssistant) -> dict[str, Any]:
    """Start the user menu and open the live hub form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    assert list(result["menu_options"]) == ["live", "simulation"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "live"},
    )


async def test_user_flow_forms_serialize(hass: HomeAssistant) -> None:
    """The live hub form holds the name, weather, and two collapsed sections."""
    result = await _open_live(hass)
    fields = _serialize(result)
    assert result["step_id"] == "live"
    assert "text" in _field(fields, "name")["selector"]
    assert _field(fields, CONF_WEATHER_ENTITY)["selector"]["entity"]["domain"] == [
        "weather"
    ]
    assert _field(fields, "sensors")["type"] == "expandable"
    assert _field(fields, "sensors")["expanded"] is False
    assert _field(fields, "location")["expanded"] is False
    assert _field(fields, "morning")["expanded"] is True
    assert "boolean" in _field(fields, "dynamic_start")["selector"]
    assert "time" in _field(fields, "earliest_start")["selector"]
    assert "time" in _field(fields, "finish_time")["selector"]
    with pytest.raises(StopIteration):
        _field(fields, "start_time")
    assert _field(fields, CONF_LATITUDE)["selector"]["number"]["step"] == "any"
    assert _field(fields, CONF_LONGITUDE)["selector"]["number"]["step"] == "any"
    assert _field(fields, "allowed_weekdays")["selector"]["select"]["options"] == [
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ]
    freeze = _field(fields, "freeze_skip_f")
    assert freeze["selector"]["number"]["unit_of_measurement"] == "°F"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Garden", **_sections()},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "need_weather"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            **_sections(),
        },
    )
    result = await _finish_with_no_zones(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Garden"
    assert result["result"].data == {CONF_WEATHER_ENTITY: "weather.home"}
    assert result["result"].options[CONF_ELEVATION_M] == 219
    assert "mode" not in result["result"].options
    assert "recent_rain_mm" not in result["result"].options
    assert result["result"].options["send_plan_notifications"] is True
    assert CONF_TEMPERATURE_SENSOR not in result["result"].options
    assert result["result"].version == 10
    assert result["result"].options["dynamic_start"] is True
    assert result["result"].options["start_time"] == "05:00:00"
    assert result["result"].options["earliest_start"] == "04:00:00"


async def test_user_flow_http_post_is_ok(hass: HomeAssistant, hass_client) -> None:
    """POST /api/config/config_entries/flow must not answer 400: Bad Request."""
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()
    response = await client.post(
        "/api/config/config_entries/flow",
        json={"handler": DOMAIN},
    )
    text = await response.text()
    assert response.status == 200, text
    body = json.loads(text)
    assert body["type"] == "menu"
    assert body["step_id"] == "user"
    assert body["menu_options"] == ["live", "simulation"]
    response = await client.post(
        f"/api/config/config_entries/flow/{body['flow_id']}",
        json={"next_step_id": "live"},
    )
    text = await response.text()
    assert response.status == 200, text
    body = json.loads(text)
    assert body["type"] == "form"
    assert body["step_id"] == "live"
    latitude = _field(body["data_schema"], CONF_LATITUDE)
    assert latitude["selector"]["number"]["step"] == "any"


async def test_temperature_sensor_can_replace_weather(hass: HomeAssistant) -> None:
    """A hub with only a temperature sensor is enough."""
    result = await _open_live(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Sensors only",
            "sensors": {CONF_TEMPERATURE_SENSOR: "sensor.tempest_air_temperature"},
            "morning": {},
            "location": {},
        },
    )
    result = await _finish_with_no_zones(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_WEATHER_ENTITY not in result["result"].data
    assert (
        result["result"].options[CONF_TEMPERATURE_SENSOR]
        == "sensor.tempest_air_temperature"
    )


async def test_tempest_entities_are_suggested(hass: HomeAssistant) -> None:
    """A Tempest name is prefilled. An indoor thermometer is not."""
    hass.states.async_set("weather.tempest", "sunny", {"friendly_name": "Tempest"})
    hass.states.async_set("weather.other", "sunny", {"friendly_name": "Other"})
    hass.states.async_set(
        "sensor.tempest_air_temperature",
        "30",
        {
            "device_class": "temperature",
            "unit_of_measurement": "°C",
            "friendly_name": "Air Temperature",
        },
    )
    hass.states.async_set(
        "sensor.kitchen_temperature",
        "22",
        {
            "device_class": "temperature",
            "unit_of_measurement": "°C",
            "friendly_name": "Kitchen",
        },
    )
    result = await _open_live(hass)
    fields = _serialize(result)
    assert _field(fields, CONF_WEATHER_ENTITY)["description"]["suggested_value"] == (
        "weather.tempest"
    )
    assert _field(fields, "sensors")["expanded"] is True
    assert _field(fields, CONF_TEMPERATURE_SENSOR)["description"]["suggested_value"] == (
        "sensor.tempest_air_temperature"
    )


async def test_options_flow_forms_serialize(hass: HomeAssistant) -> None:
    """Hub options are one form with the same two sections."""
    entry = _hub_entry(options={"dynamic_start": False, "start_time": "06:15:00"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = _serialize(result)
    assert result["step_id"] == "init"
    assert _field(fields, "dynamic_start")["description"]["suggested_value"] is False
    assert _field(fields, "start_time")["description"]["suggested_value"] == "06:15:00"
    assert _field(fields, CONF_LATITUDE)["selector"]["number"]["step"] == "any"
    assert _field(fields, CONF_LONGITUDE)["selector"]["number"]["step"] == "any"
    assert _field(fields, "allowed_weekdays")["selector"]["select"]["multiple"] is True
    assert _field(fields, "location")["type"] == "expandable"
    assert _field(fields, "morning")["expanded"] is True
    assert "time" in _field(fields, "start_time")["selector"]
    assert "time" in _field(fields, "earliest_start")["selector"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _sections(),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ELEVATION_M] == 219
    assert "mode" not in result["data"]
    assert result["data"]["send_plan_notifications"] is True


async def test_zone_quick_setup_leaves_presets_blank(hass: HomeAssistant) -> None:
    """The short zone form stores the dropdowns. Empty advanced fields stay absent."""
    entry = _hub_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ZONE),
        context={"source": SOURCE_USER},
    )
    fields = _serialize(result)
    assert result["step_id"] == "user"
    assert "text" in _field(fields, "name")["selector"]
    plants = _field(fields, CONF_PLANT_TYPE)["selector"]["select"]["options"]
    assert plants[:4] == ["st_augustine", "bermuda", "zoysia", "buffalo"]
    assert _field(fields, CONF_VALVE_ENTITY)["selector"]["entity"]["domain"] == [
        "switch",
        "valve",
        "input_boolean",
    ]
    assert _field(fields, "sprinkler_type")["selector"]["select"]["options"] == [
        "spray",
        "rotor",
        "mp_rotator",
        "drip",
        "bubbler",
    ]
    assert all(field["name"] != CONF_SLOPE_PCT for field in fields)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Front lawn",
            CONF_VALVE_ENTITY: "switch.front_valve",
            CONF_PLANT_TYPE: "st_augustine",
            CONF_SOIL_TYPE: "loam",
            CONF_SPRINKLER_TYPE: "spray",
            CONF_SUN_EXPOSURE: "full_sun",
        },
    )
    assert result["step_id"] == "advanced"
    fields = _serialize(result)
    assert _field(fields, "plant_overrides")["expanded"] is False
    assert _field(fields, "hardware_overrides")["expanded"] is False
    assert (
        _field(fields, "precipitation_rate_in_hr")["selector"]["number"][
            "unit_of_measurement"
        ]
        == "in/h"
    )
    assert "description" not in _field(fields, CONF_ROOT_DEPTH_IN)
    assert "description" not in _field(fields, CONF_EFFICIENCY)
    month = dt_util.now().month
    assert result["description_placeholders"]["root_depth"] == "6"
    assert result["description_placeholders"]["awc"] == "0.155"
    assert result["description_placeholders"]["precip"] == "1.25"
    assert result["description_placeholders"]["efficiency"] == "0.6"
    assert result["description_placeholders"]["kc"] == f"{plant_kc('st_augustine', month):.2f}"
    assert _field(fields, "moisture_mode")["selector"]["select"]["options"] == [
        "off",
        "correct",
        "override",
    ]
    assert _field(fields, "moisture_weight")["selector"]["number"]["step"] == 0.05
    assert all(field["name"] != CONF_FLOW_SENSOR for field in fields)
    assert all(field["name"] != CONF_FLOW_KIND for field in fields)
    assert _field(fields, CONF_FLOW_LOW_RATIO)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "plant_overrides": {},
            "hardware_overrides": {},
            "measurement_overrides": {},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_PLANT_TYPE] == "st_augustine"
    assert data[CONF_SOIL_TYPE] == "loam"
    assert data[CONF_SPRINKLER_TYPE] == "spray"
    assert data[CONF_VALVE_ENTITY] == "switch.front_valve"
    assert data[CONF_PRIORITY] == 10
    for absent in (
        CONF_ROOT_DEPTH_IN,
        CONF_DEPLETION,
        CONF_EFFICIENCY,
        CONF_PRECIPITATION_RATE,
        CONF_SLOPE_PCT,
        "kc_override",
        "awc_override",
        "intake_in_hr",
    ):
        assert absent not in data


async def test_bubbler_requires_a_rate(hass: HomeAssistant) -> None:
    """Bubbler has no published precipitation rate, so the advanced step asks."""
    entry = _hub_entry()
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ZONE),
        context={"source": SOURCE_USER},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Tree",
            CONF_VALVE_ENTITY: "valve.tree",
            CONF_PLANT_TYPE: "tree",
            CONF_SOIL_TYPE: "clay",
            CONF_SPRINKLER_TYPE: "bubbler",
            CONF_SUN_EXPOSURE: "part_sun",
        },
    )
    assert result["description_placeholders"]["precip"] == "none published"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "plant_overrides": {},
            "hardware_overrides": {},
            "measurement_overrides": {},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "precipitation_rate"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "plant_overrides": {},
            "hardware_overrides": {CONF_PRECIPITATION_RATE: 1.0},
            "measurement_overrides": {},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PRECIPITATION_RATE] == 1.0
    assert CONF_EFFICIENCY not in result["data"]


async def test_reconfigure_suggests_stored_overrides_only(hass: HomeAssistant) -> None:
    """Saving again must keep a stored efficiency. Unset fields stay unset."""
    entry = _hub_entry(
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "cool_season_turf",
                    CONF_SOIL_TYPE: "loam",
                    CONF_SLOPE_PCT: 2,
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_ROOT_DEPTH_IN: 6,
                    CONF_DEPLETION: 0.4,
                    CONF_EFFICIENCY: 1.0,
                    CONF_PRIORITY: 10,
                    CONF_VALVE_ENTITY: "switch.lawn",
                },
                "subentry_type": SUBENTRY_ZONE,
                "title": "Lawn",
                "unique_id": "lawn",
            }
        ]
    )
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    fields = _serialize(result)
    assert result["step_id"] == "reconfigure"
    assert _field(fields, CONF_WEATHER_ENTITY)["selector"]["entity"]["domain"] == [
        "weather"
    ]
    assert _field(fields, CONF_WEATHER_ENTITY)["optional"] is True

    subentry_id = next(iter(entry.subentries))
    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    fields = _serialize(result)
    assert result["step_id"] == "user"
    assert _field(fields, CONF_VALVE_ENTITY)["description"]["suggested_value"] == (
        "switch.lawn"
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Lawn",
            CONF_VALVE_ENTITY: "switch.lawn",
            CONF_PLANT_TYPE: "cool_season_turf",
            CONF_SOIL_TYPE: "loam",
            CONF_SPRINKLER_TYPE: "spray",
            CONF_SUN_EXPOSURE: "full_sun",
        },
    )
    fields = _serialize(result)
    assert _field(fields, CONF_EFFICIENCY)["description"]["suggested_value"] == 1.0
    assert _field(fields, CONF_ROOT_DEPTH_IN)["description"]["suggested_value"] == 6
    assert _field(fields, CONF_SLOPE_PCT)["description"]["suggested_value"] == 2
    assert "description" not in _field(fields, CONF_PRECIPITATION_RATE)

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "plant_overrides": {CONF_ROOT_DEPTH_IN: 6, CONF_DEPLETION: 0.4},
            "hardware_overrides": {CONF_EFFICIENCY: 1.0, CONF_SLOPE_PCT: 2},
            "measurement_overrides": {},
        },
    )
    assert result["type"] is FlowResultType.ABORT
    saved = entry.subentries[subentry_id].data
    assert saved[CONF_EFFICIENCY] == 1.0
    assert saved[CONF_ROOT_DEPTH_IN] == 6
    assert CONF_PRECIPITATION_RATE not in saved


async def test_simulation_hub_uses_dropdowns_and_a_virtual_valve(
    hass: HomeAssistant,
) -> None:
    """A simulation hub needs no weather entity and no real on/off entity."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "simulation"},
    )
    fields = _serialize(result)
    assert result["step_id"] == "simulation"
    assert all(field["name"] != CONF_WEATHER_ENTITY for field in fields)
    assert _field(fields, CONF_SCENARIO)["selector"]["select"]["options"][0] == "hot_dry"
    assert _field(fields, CONF_BUCKET)["selector"]["select"]["options"] == [
        "full",
        "half",
        "raw",
    ]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Play yard",
            CONF_SCENARIO: "hot_dry",
            CONF_BUCKET: "full",
            "morning": {},
            "location": {},
        },
    )
    result = await _finish_with_no_zones(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.version == 10
    assert entry.data == {CONF_SIMULATION: True}
    assert entry.options[CONF_SCENARIO] == "hot_dry"
    assert entry.options[CONF_BUCKET] == "full"
    assert CONF_WEATHER_ENTITY not in entry.data

    zone = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ZONE),
        context={"source": SOURCE_USER},
    )
    fields = _serialize(zone)
    assert all(field["name"] != CONF_VALVE_ENTITY for field in fields)
    assert _field(fields, CONF_AREA_SQFT)["optional"] is True
    assert _field(fields, CONF_SLOPE_PCT)["optional"] is True
    zone = await hass.config_entries.subentries.async_configure(
        zone["flow_id"],
        {
            "name": "Front lawn",
            CONF_PLANT_TYPE: "st_augustine",
            CONF_SOIL_TYPE: "clay_loam",
            CONF_SPRINKLER_TYPE: "spray",
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_AREA_SQFT: 1000,
        },
    )
    assert zone["step_id"] == "advanced"
    zone = await hass.config_entries.subentries.async_configure(
        zone["flow_id"],
        {
            "plant_overrides": {},
            "hardware_overrides": {},
            "measurement_overrides": {},
        },
    )
    assert zone["type"] is FlowResultType.CREATE_ENTRY
    assert zone["data"][CONF_VALVE_ENTITY] == "simulation.front_lawn"
    assert zone["data"][CONF_AREA_SQFT] == 1000
    assert CONF_SLOPE_PCT not in zone["data"]
    assert CONF_EFFICIENCY not in zone["data"]


def _quick_zone(name: str, valve: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "name": name,
        CONF_VALVE_ENTITY: valve,
        CONF_PLANT_TYPE: "warm_season_turf",
        CONF_SOIL_TYPE: "clay_loam",
        CONF_SPRINKLER_TYPE: "spray",
        CONF_SUN_EXPOSURE: "full_sun",
    }
    data.update(overrides)
    return data


async def test_hub_flow_adds_zones_and_keeps_later_picks(
    hass: HomeAssistant,
) -> None:
    """Later zones start from the previous zone, and the submitted picks are saved."""
    result = await _open_live(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Watering Stuff", CONF_WEATHER_ENTITY: "weather.home", **_sections()},
    )
    assert result["step_id"] == "zone_count"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"zones": 2},
    )
    assert result["step_id"] == "zone"
    fields = _serialize(result)
    assert all(field["name"] != "same_as_previous" for field in fields)
    assert _field(fields, CONF_VALVE_ENTITY)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _quick_zone(
            "Front",
            "switch.front",
            **{
                CONF_PLANT_TYPE: "shrub",
                CONF_SOIL_TYPE: "clay_loam",
                CONF_SPRINKLER_TYPE: "spray",
                CONF_SUN_EXPOSURE: "part_sun",
            },
        ),
    )
    assert result["step_id"] == "zone"
    assert result["last_step"] is True
    fields = _serialize(result)
    assert all(field["name"] != "same_as_previous" for field in fields)
    assert _field(fields, CONF_PLANT_TYPE)["default"] == "shrub"
    assert _field(fields, CONF_SOIL_TYPE)["default"] == "clay_loam"
    assert _field(fields, CONF_SPRINKLER_TYPE)["default"] == "spray"
    assert _field(fields, CONF_SUN_EXPOSURE)["default"] == "part_sun"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _quick_zone(
            "Back",
            "switch.back",
            **{
                CONF_PLANT_TYPE: "bermuda",
                CONF_SOIL_TYPE: "sand",
                CONF_SPRINKLER_TYPE: "rotor",
                CONF_SUN_EXPOSURE: "full_sun",
            },
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.version == 10
    zones = {zone.title: zone for zone in entry.subentries.values()}
    assert set(zones) == {"Front", "Back"}
    assert zones["Front"].data[CONF_VALVE_ENTITY] == "switch.front"
    assert zones["Front"].data[CONF_PLANT_TYPE] == "shrub"
    assert zones["Front"].data[CONF_SUN_EXPOSURE] == "part_sun"
    assert zones["Back"].data[CONF_VALVE_ENTITY] == "switch.back"
    assert zones["Back"].data[CONF_PLANT_TYPE] == "bermuda"
    assert zones["Back"].data[CONF_SOIL_TYPE] == "sand"
    assert zones["Back"].data[CONF_SPRINKLER_TYPE] == "rotor"
    assert zones["Back"].data[CONF_SUN_EXPOSURE] == "full_sun"
    assert "same_as_previous" not in zones["Back"].data
    assert CONF_EFFICIENCY not in zones["Front"].data


async def test_duplicate_zone_name_is_rejected(hass: HomeAssistant) -> None:
    """A second zone cannot reuse the first zone's name."""
    result = await _open_live(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Garden", CONF_WEATHER_ENTITY: "weather.home", **_sections()},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"zones": 2}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _quick_zone("Front", "switch.front"),
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _quick_zone(
            "Front",
            "switch.back",
        ),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["name"] == "name_exists"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _quick_zone(
            "Back",
            "switch.back",
            **{CONF_PLANT_TYPE: "st_augustine", CONF_SOIL_TYPE: "sand"},
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    zones = {zone.title: zone for zone in result["result"].subentries.values()}
    assert zones["Back"].data[CONF_PLANT_TYPE] == "st_augustine"
    assert zones["Back"].data[CONF_SOIL_TYPE] == "sand"
    assert zones["Back"].data[CONF_SPRINKLER_TYPE] == "spray"


async def test_simulation_setup_zone_uses_a_virtual_valve(hass: HomeAssistant) -> None:
    """A simulation zone added during setup has no on/off picker and skips Advanced."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"next_step_id": "simulation"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Play yard",
            CONF_SCENARIO: "hot_dry",
            CONF_BUCKET: "full",
            "morning": {},
            "location": {},
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"zones": 1},
    )
    fields = _serialize(result)
    assert result["step_id"] == "zone"
    assert result["last_step"] is True
    assert all(field["name"] != CONF_VALVE_ENTITY for field in fields)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Front lawn",
            CONF_PLANT_TYPE: "st_augustine",
            CONF_SOIL_TYPE: "clay_loam",
            CONF_SPRINKLER_TYPE: "spray",
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_AREA_SQFT: 800,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    zone = next(iter(result["result"].subentries.values()))
    assert zone.data[CONF_VALVE_ENTITY] == "simulation.front_lawn"
    assert zone.data[CONF_AREA_SQFT] == 800
    assert CONF_EFFICIENCY not in zone.data


async def test_flow_meter_is_on_the_hub_and_requires_a_choice(
    hass: HomeAssistant,
) -> None:
    """The hub form asks for one meter and which kind of meter it is."""
    result = await _open_live(hass)
    fields = _serialize(result)
    assert _field(fields, "flow_meter")["expanded"] is True
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            **_sections(),
            "flow_meter": {
                CONF_FLOW_SENSOR: "sensor.main_flow",
                CONF_FLOW_KIND: "total",
            },
        },
    )
    assert result["errors"]["base"] == "flow_scope"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            **_sections(),
            "flow_meter": {
                CONF_FLOW_SENSOR: "sensor.main_flow",
                CONF_FLOW_KIND: "total",
                CONF_FLOW_SCOPE: "whole_home",
            },
        },
    )
    result = await _finish_with_no_zones(hass, result)
    options = result["result"].options
    assert options[CONF_FLOW_SENSOR] == "sensor.main_flow"
    assert options[CONF_FLOW_KIND] == "total"
    assert options[CONF_FLOW_SCOPE] == "whole_home"
    assert "flow_idle_gpm" not in options


async def test_irrigation_meter_shows_idle_settings_and_whole_home_hides_them(
    hass: HomeAssistant,
) -> None:
    """Idle-flow settings appear only after an irrigation-only meter is saved."""
    irrigation = _hub_entry(
        options={
            CONF_FLOW_SENSOR: "sensor.main_flow",
            CONF_FLOW_KIND: "total",
            CONF_FLOW_SCOPE: "irrigation",
        }
    )
    irrigation.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(irrigation.entry_id)
    assert _field(_serialize(result), "flow_idle_gpm")

    whole = _hub_entry(
        options={
            CONF_FLOW_SENSOR: "sensor.main_flow",
            CONF_FLOW_KIND: "total",
            CONF_FLOW_SCOPE: "whole_home",
        }
    )
    whole.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(whole.entry_id)
    with pytest.raises(StopIteration):
        _field(_serialize(result), "flow_idle_gpm")
