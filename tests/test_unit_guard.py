"""Missing and unknown units are rejected, ignored, and repaired."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers import entity_registry as er

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_HUMIDITY_SENSOR,
    CONF_MOISTURE_SENSOR,
    CONF_PLANT_TYPE,
    CONF_RAIN_RATE_MIN,
    CONF_RAIN_SENSOR,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    SUBENTRY_ZONE,
)
from custom_components.sprinklecast.coordinator import _is_wet

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _weather(**extra: object) -> dict[str, object]:
    attributes: dict[str, object] = {
        "temperature": 20,
        "temperature_unit": "°C",
        "humidity": 60,
        "wind_speed": 2,
        "wind_speed_unit": "m/s",
        "precipitation_unit": "mm",
    }
    attributes.update(extra)
    return attributes


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_TEMPERATURE_SENSOR: "sensor.temp",
            CONF_HUMIDITY_SENSOR: "sensor.humidity",
        },
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "warm_season_turf",
                    CONF_SOIL_TYPE: "loam",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_VALVE_ENTITY: "switch.front",
                    CONF_MOISTURE_SENSOR: "sensor.soil",
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
            }
        ],
    )


async def _load(hass: HomeAssistant) -> MockConfigEntry:
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    hass.states.async_set("switch.front", "off")
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _issue(hass: HomeAssistant, entry_id: str, key: str):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"unit_{entry_id}_{key}")


async def test_unknown_units_are_ignored_and_the_repair_clears(
    hass: HomeAssistant,
) -> None:
    """A bad unit does not become Celsius, percent, or a moisture fraction."""
    hass.states.async_set("weather.home", "sunny", _weather())
    hass.states.async_set("sensor.temp", "32")
    hass.states.async_set("sensor.humidity", "0.45")
    hass.states.async_set("sensor.soil", "0.40")
    entry = await _load(hass)
    zone_id = next(iter(entry.subentries))

    temp = _issue(hass, entry.entry_id, "temperature_sensor")
    assert temp is not None
    assert temp.translation_placeholders["entity"] == "sensor.temp"
    assert temp.translation_placeholders["unit"] == "missing"
    assert "°C" in temp.translation_placeholders["accepted"]
    assert "°F" in temp.translation_placeholders["accepted"]
    assert entry.runtime_data.store.weather["t_max_c"] is None

    humidity = _issue(hass, entry.entry_id, "humidity_sensor")
    assert humidity is not None
    assert humidity.translation_placeholders["unit"] == "missing"
    assert entry.runtime_data.data  # snapshot exists
    observation = entry.runtime_data._last_observation
    assert observation.inputs is not None
    assert observation.inputs.rh_mean_pct == pytest.approx(60)

    moisture = _issue(hass, entry.entry_id, f"moisture_{zone_id}")
    assert moisture is not None
    assert moisture.translation_placeholders["entity"] == "sensor.soil"
    assert "fraction" in moisture.translation_placeholders["accepted"]
    assert entry.runtime_data.store.zone(zone_id).get("moisture_pct") is None

    hass.states.async_set("sensor.temp", "32", {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.humidity", "45", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.soil", "0.40", {"unit_of_measurement": "fraction"})
    await entry.runtime_data._async_update_data()

    assert _issue(hass, entry.entry_id, "temperature_sensor") is None
    assert _issue(hass, entry.entry_id, "humidity_sensor") is None
    assert _issue(hass, entry.entry_id, f"moisture_{zone_id}") is None
    assert entry.runtime_data.store.weather["t_max_c"] == pytest.approx(0.0)
    assert entry.runtime_data.store.zone(zone_id)["moisture_pct"] == pytest.approx(40)

    hass.states.async_set("weather.home", "sunny", _weather(precipitation_unit="cm"))
    await entry.runtime_data._async_update_data()
    precip = _issue(hass, entry.entry_id, "weather_precipitation_unit")
    assert precip is not None
    assert precip.translation_placeholders["entity"] == "weather.home"
    assert precip.translation_placeholders["unit"] == "cm"
    assert "mm" in precip.translation_placeholders["accepted"]

    hass.states.async_set("weather.home", "sunny", _weather())
    await entry.runtime_data._async_update_data()
    assert _issue(hass, entry.entry_id, "weather_precipitation_unit") is None


async def test_config_flow_rejects_a_missing_or_unknown_unit(hass: HomeAssistant) -> None:
    """The form names the entity and the accepted units instead of saving it."""
    hass.states.async_set("sensor.temp", "70")
    hass.states.async_set("weather.home", "sunny", _weather())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "live"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {CONF_TEMPERATURE_SENSOR: "sensor.temp"},
            "morning": {},
            "location": {},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "bad_unit"
    detail = result["description_placeholders"]["detail"]
    assert "sensor.temp" in detail
    assert "missing" in detail
    assert "°C" in detail
    assert "°F" in detail

    hass.states.async_set("sensor.temp", "70", {"unit_of_measurement": "°F"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {CONF_TEMPERATURE_SENSOR: "sensor.temp"},
            "morning": {},
            "location": {},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_count"

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "live"}
    )
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            "temperature": 20,
            "temperature_unit": "°C",
            "wind_speed_unit": "m/s",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {},
            "morning": {},
            "location": {},
        },
    )
    assert result["errors"]["base"] == "bad_unit"
    assert "precipitation" in result["description_placeholders"]["detail"].casefold()
    assert "mm" in result["description_placeholders"]["detail"]


async def test_options_flow_rejects_a_sensor_without_a_unit(hass: HomeAssistant) -> None:
    """Options uses the same unit check as the first setup form."""
    hass.states.async_set("weather.home", "sunny", _weather())
    hass.states.async_set("sensor.temp", "21")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={CONF_ELEVATION_M: 219.0},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sensors": {CONF_TEMPERATURE_SENSOR: "sensor.temp"},
            "morning": {},
            "location": {},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "bad_unit"
    assert "sensor.temp" in result["description_placeholders"]["detail"]
    assert "°C" in result["description_placeholders"]["detail"]


def test_on_off_or_rate_means_raining(hass: HomeAssistant) -> None:
    """On means raining. A rate counts only above the threshold, in its own unit."""
    hass.states.async_set("binary_sensor.rain", "on")
    assert _is_wet(hass, "binary_sensor.rain", 5) is True
    hass.states.async_set("binary_sensor.rain", "off")
    assert _is_wet(hass, "binary_sensor.rain") is False
    hass.states.async_set("binary_sensor.rain", "unavailable")
    assert _is_wet(hass, "binary_sensor.rain") is False
    hass.states.async_set("switch.rain", "on")
    assert _is_wet(hass, "switch.rain") is True
    hass.states.async_set("input_boolean.rain", "on")
    assert _is_wet(hass, "input_boolean.rain") is True

    hass.states.async_set("sensor.rain_rate", "0", {"unit_of_measurement": "mm/h"})
    assert _is_wet(hass, "sensor.rain_rate", 0) is False
    hass.states.async_set("sensor.rain_rate", "0.2", {"unit_of_measurement": "mm/h"})
    assert _is_wet(hass, "sensor.rain_rate", 0) is True
    assert _is_wet(hass, "sensor.rain_rate", 0.2) is False
    assert _is_wet(hass, "sensor.rain_rate", 0.1) is True
    hass.states.async_set("sensor.rain_rate", "0.04", {"unit_of_measurement": "in/hr"})
    assert _is_wet(hass, "sensor.rain_rate", 0.01) is True
    assert _is_wet(hass, "sensor.rain_rate", 0.04) is False
    hass.states.async_set("sensor.rain_rate", "5", {"unit_of_measurement": "mm"})
    assert _is_wet(hass, "sensor.rain_rate", 0) is False
    hass.states.async_set("sensor.rain_rate", "5")
    assert _is_wet(hass, "sensor.rain_rate", 0) is False

    er.async_get(hass).async_get_or_create(
        "sensor",
        "test",
        "rain_rate_reg",
        suggested_object_id="rain_rate_reg",
        unit_of_measurement="inches/h",
    )
    hass.states.async_set("sensor.rain_rate_reg", "0.2")
    assert _is_wet(hass, "sensor.rain_rate_reg", 0.1) is True


async def test_numeric_rain_without_a_rate_unit_is_ignored_and_repaired(
    hass: HomeAssistant,
) -> None:
    """A rate sensor with no recognized unit does not skip, and the repair clears."""
    hass.states.async_set("weather.home", "sunny", _weather())
    hass.states.async_set("switch.front", "off")
    hass.states.async_set("binary_sensor.rain", "off")
    hass.states.async_set("sensor.zone_rain", "4")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_RAIN_SENSOR: "binary_sensor.rain",
        },
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "warm_season_turf",
                    CONF_SOIL_TYPE: "loam",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_VALVE_ENTITY: "switch.front",
                    CONF_RAIN_SENSOR: "sensor.zone_rain",
                    CONF_RAIN_RATE_MIN: 0.05,
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
            }
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    zone_id = next(iter(entry.subentries))

    assert _issue(hass, entry.entry_id, "rain_sensor") is None
    zone_issue = _issue(hass, entry.entry_id, f"rain_{zone_id}")
    assert zone_issue is not None
    assert zone_issue.translation_placeholders["entity"] == "sensor.zone_rain"
    assert zone_issue.translation_placeholders["unit"] == "missing"
    assert "in/h" in zone_issue.translation_placeholders["accepted"]
    assert "mm/h" in zone_issue.translation_placeholders["accepted"]
    assert entry.runtime_data.live_skip(zone_id, True) is None

    hass.states.async_set("binary_sensor.rain", "on")
    assert "rain" in (entry.runtime_data.live_skip(zone_id, True) or "")
    hass.states.async_set("binary_sensor.rain", "off")

    hass.states.async_set(
        "sensor.zone_rain", "0.02", {"unit_of_measurement": "in/h"}
    )
    await entry.runtime_data._async_update_data()
    assert _issue(hass, entry.entry_id, f"rain_{zone_id}") is None
    assert entry.runtime_data.live_skip(zone_id, True) is None

    hass.states.async_set(
        "sensor.zone_rain", "0.2", {"unit_of_measurement": "in/h"}
    )
    assert "rain" in (entry.runtime_data.live_skip(zone_id, True) or "")

    hass.states.async_set("sensor.zone_rain", "unavailable")
    await entry.runtime_data._async_update_data()
    assert _issue(hass, entry.entry_id, f"rain_{zone_id}") is None
    assert entry.runtime_data.live_skip(zone_id, True) is None

    hass.states.async_set("sensor.zone_rain", "1.5", {"unit_of_measurement": "mm"})
    await entry.runtime_data._async_update_data()
    reopened = _issue(hass, entry.entry_id, f"rain_{zone_id}")
    assert reopened is not None
    assert reopened.translation_placeholders["unit"] == "mm"
    assert entry.runtime_data.live_skip(zone_id, True) is None

    hass.states.async_set("sensor.hub_rain", "1.0")
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_RAIN_SENSOR: "sensor.hub_rain",
            CONF_RAIN_RATE_MIN: 0,
        },
    )
    await entry.runtime_data._async_update_data()
    hub_issue = _issue(hass, entry.entry_id, "rain_sensor")
    assert hub_issue is not None
    assert hub_issue.translation_placeholders["entity"] == "sensor.hub_rain"
    assert hub_issue.translation_placeholders["unit"] == "missing"
    assert entry.runtime_data.live_skip(zone_id, True) is None

    hass.states.async_set(
        "sensor.hub_rain", "0.3", {"unit_of_measurement": "mm/h"}
    )
    await entry.runtime_data._async_update_data()
    assert _issue(hass, entry.entry_id, "rain_sensor") is None
    assert "rain" in (entry.runtime_data.live_skip(zone_id, True) or "")


async def test_config_flow_rejects_a_rain_rate_without_a_unit(
    hass: HomeAssistant,
) -> None:
    """A numeric rain sensor needs a rate unit. An on/off sensor does not."""
    hass.states.async_set("weather.home", "sunny", _weather())
    hass.states.async_set("sensor.rain_rate", "1.2")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "live"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {},
            "morning": {},
            "location": {CONF_RAIN_SENSOR: "sensor.rain_rate"},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "bad_unit"
    detail = result["description_placeholders"]["detail"]
    assert "sensor.rain_rate" in detail
    assert "missing" in detail
    assert "in/h" in detail
    assert "mm/h" in detail

    hass.states.async_set("sensor.rain_rate", "1.2", {"unit_of_measurement": "mm"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {},
            "morning": {},
            "location": {CONF_RAIN_SENSOR: "sensor.rain_rate"},
        },
    )
    assert result["errors"]["base"] == "bad_unit"
    assert "mm" in result["description_placeholders"]["detail"]

    hass.states.async_set(
        "sensor.rain_rate", "1.2", {"unit_of_measurement": "mm/hr"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {},
            "morning": {},
            "location": {
                CONF_RAIN_SENSOR: "sensor.rain_rate",
                CONF_RAIN_RATE_MIN: 0.2,
            },
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "zone_count"

    hass.states.async_set("binary_sensor.rain", "off")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "live"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {},
            "morning": {},
            "location": {CONF_RAIN_SENSOR: "binary_sensor.missing"},
        },
    )
    assert result["errors"]["base"] == "bad_unit"
    assert "binary_sensor.missing" in result["description_placeholders"]["detail"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Garden",
            CONF_WEATHER_ENTITY: "weather.home",
            "sensors": {},
            "morning": {},
            "location": {CONF_RAIN_SENSOR: "binary_sensor.rain"},
        },
    )
    assert result["step_id"] == "zone_count"


async def test_zone_flow_rejects_a_rain_rate_without_a_unit(hass: HomeAssistant) -> None:
    """Each zone uses the same rain-sensor check as the hub."""
    hass.states.async_set("sensor.zone_rain", "2")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={CONF_ELEVATION_M: 219.0},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_ZONE),
        context={"source": SOURCE_USER},
    )
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
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "plant_overrides": {},
            "hardware_overrides": {},
            "measurement_overrides": {CONF_RAIN_SENSOR: "sensor.zone_rain"},
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "bad_unit"
    assert "sensor.zone_rain" in result["description_placeholders"]["detail"]
    assert "in/h" in result["description_placeholders"]["detail"]

    hass.states.async_set(
        "sensor.zone_rain", "0.1", {"unit_of_measurement": "inches/hour"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "plant_overrides": {},
            "hardware_overrides": {},
            "measurement_overrides": {
                CONF_RAIN_SENSOR: "sensor.zone_rain",
                CONF_RAIN_RATE_MIN: 0.05,
            },
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RAIN_SENSOR] == "sensor.zone_rain"
    assert result["data"][CONF_RAIN_RATE_MIN] == 0.05


async def test_options_flow_rejects_a_rain_rate_without_a_unit(
    hass: HomeAssistant,
) -> None:
    """Hub options reject a numeric rain sensor the same way setup does."""
    hass.states.async_set("weather.home", "sunny", _weather())
    hass.states.async_set("switch.rain", "off")
    hass.states.async_set("sensor.rain_rate", "0.4", {"unit_of_measurement": "mm/d"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={CONF_ELEVATION_M: 219.0},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sensors": {},
            "morning": {},
            "location": {CONF_RAIN_SENSOR: "sensor.rain_rate"},
        },
    )
    assert result["errors"]["base"] == "bad_unit"
    assert "sensor.rain_rate" in result["description_placeholders"]["detail"]
    assert "mm/h" in result["description_placeholders"]["detail"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sensors": {},
            "morning": {},
            "location": {CONF_RAIN_SENSOR: "switch.rain"},
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_RAIN_SENSOR] == "switch.rain"
