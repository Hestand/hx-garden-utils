"""Config-flow forms must serialize the way the config HTTP API does.

Home Assistant 2026.10 turns a probatio.Invalid raised while building a step
into a plain ``400: Bad Request``. The user, options, and zone forms are
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
import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_water.const import (
    CONF_DEPLETION,
    CONF_DRY_RUN,
    CONF_EFFICIENCY,
    CONF_ELEVATION_M,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MODE,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRIORITY,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    MODE_NOTIFY_ONLY,
    SUBENTRY_ZONE,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _serialize(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Serialize a form with the config-flow HTTP view's serializer."""
    assert result["type"] is FlowResultType.FORM
    prepared = _BaseFlowManagerView._prepare_result_json(None, result)  # type: ignore[arg-type]
    fields = prepared["data_schema"]
    # The view used to call voluptuous_serialize.convert(..., custom_serializer=cv.custom_serializer).
    # 2026.10 renders that through probatio.to_field_list with the same hook.
    direct = probatio.to_field_list(
        result["data_schema"], custom_serializer=cv.custom_serializer
    )
    assert fields == direct
    json.dumps(fields)
    assert isinstance(fields, list) and fields
    for field in fields:
        assert "name" in field
        assert "selector" in field, field
    return fields


def _field(fields: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next(field for field in fields if field["name"] == name)


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


async def test_user_flow_forms_serialize(hass: HomeAssistant) -> None:
    """The UI's first POST must return a serializable user form, then the later steps."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    fields = _serialize(result)
    assert result["step_id"] == "user"
    assert _field(fields, CONF_LATITUDE)["selector"]["number"]["step"] == "any"
    assert _field(fields, CONF_LONGITUDE)["selector"]["number"]["step"] == "any"
    assert "text" in _field(fields, "name")["selector"]
    assert _field(fields, CONF_WEATHER_ENTITY)["selector"]["entity"]["domain"] == [
        "weather"
    ]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            CONF_ELEVATION_M: 219,
        },
    )
    assert result["step_id"] == "behavior"
    fields = _serialize(result)
    assert "boolean" in _field(fields, CONF_DRY_RUN)["selector"]
    assert _field(fields, CONF_MODE)["selector"]["select"]["options"] == [
        "auto",
        "notify_only",
        "off",
    ]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DRY_RUN: False,
            CONF_MODE: MODE_NOTIFY_ONLY,
            CONF_SUNRISE_BUFFER_MIN: 30,
            CONF_PLAN_HOUR: 23,
        },
    )
    assert result["step_id"] == "sensors"
    fields = _serialize(result)
    assert _field(fields, "temperature_sensor")["selector"]["entity"]["domain"] == [
        "sensor"
    ]


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
    assert body["type"] == "form"
    assert body["step_id"] == "user"
    latitude = _field(body["data_schema"], CONF_LATITUDE)
    assert latitude["selector"]["number"]["step"] == "any"


async def test_options_flow_forms_serialize(hass: HomeAssistant) -> None:
    """Hub options, including the sensor step, must serialize."""
    entry = _hub_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    fields = _serialize(result)
    assert result["step_id"] == "init"
    assert _field(fields, CONF_LATITUDE)["selector"]["number"]["step"] == "any"
    assert _field(fields, CONF_LONGITUDE)["selector"]["number"]["step"] == "any"
    assert "boolean" in _field(fields, CONF_DRY_RUN)["selector"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ELEVATION_M: 219,
            CONF_DRY_RUN: False,
            CONF_MODE: MODE_NOTIFY_ONLY,
            CONF_SUNRISE_BUFFER_MIN: 30,
            CONF_PLAN_HOUR: 23,
        },
    )
    assert result["step_id"] == "sensors"
    _serialize(result)


async def test_zone_subentry_flow_forms_serialize(hass: HomeAssistant) -> None:
    """Adding a zone is a subentry flow. Both of its steps must serialize."""
    entry = _hub_entry()
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ZONE),
        context={"source": SOURCE_USER},
    )
    fields = _serialize(result)
    assert result["step_id"] == "user"
    assert "text" in _field(fields, "name")["selector"]
    assert _field(fields, CONF_PLANT_TYPE)["selector"]["select"]["options"]
    assert _field(fields, CONF_SLOPE_PCT)["selector"]["number"]["unit_of_measurement"] == "%"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Front lawn",
            CONF_PLANT_TYPE: "cool_season_turf",
            CONF_SOIL_TYPE: "clay_loam",
            CONF_SLOPE_PCT: 6,
            CONF_SUN_EXPOSURE: "full_sun",
        },
    )
    assert result["step_id"] == "hydraulics"
    fields = _serialize(result)
    assert (
        _field(fields, "precipitation_rate_in_hr")["selector"]["number"][
            "unit_of_measurement"
        ]
        == "in/h"
    )
    assert _field(fields, "valve_entity")["selector"]["entity"]["domain"] == ["valve"]


async def test_reconfigure_forms_serialize(hass: HomeAssistant) -> None:
    """Hub and zone reconfigure forms use the same selectors and must serialize."""
    entry = _hub_entry(
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "cool_season_turf",
                    CONF_SOIL_TYPE: "loam",
                    CONF_SLOPE_PCT: 2,
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_ROOT_DEPTH_IN: 6,
                    CONF_DEPLETION: 0.4,
                    CONF_EFFICIENCY: 1.0,
                    CONF_PRIORITY: 10,
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

    subentry_id = next(iter(entry.subentries))
    result = await entry.start_subentry_reconfigure_flow(hass, subentry_id)
    fields = _serialize(result)
    assert result["step_id"] == "user"
    assert _field(fields, CONF_PLANT_TYPE)["selector"]["select"]["options"]
