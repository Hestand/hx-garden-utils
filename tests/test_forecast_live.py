"""A live hub must finish its first refresh when the forecast is in °F or °C.

v0.7.0 called ``temperature_f(value, unit)``. That helper takes Celsius only,
so the first coordinator refresh raised TypeError and Home Assistant left the
hub in setup_retry. These tests load a hub and run that refresh.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_MODE,
    CONF_PLANT_TYPE,
    CONF_PRESSURE_SENSOR,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    DOMAIN,
    MODE_NOTIFY_ONLY,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry(unit: str) -> MockConfigEntry:
    options = {
        CONF_ELEVATION_M: 219.0,
        CONF_MODE: MODE_NOTIFY_ONLY,
    }
    if unit == "°F":
        options[CONF_WIND_SENSOR] = "sensor.wind"
        options[CONF_PRESSURE_SENSOR] = "sensor.pressure"
    return MockConfigEntry(
        domain=DOMAIN,
        title="Watering Stuff",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options=options,
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "warm_season_turf",
                    CONF_SOIL_TYPE: "clay_loam",
                    CONF_SPRINKLER_TYPE: "spray",
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_VALVE_ENTITY: "switch.front_valve",
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
            }
        ],
    )


def _install_forecast(hass: HomeAssistant, hourly: dict, daily: list[dict]) -> None:
    """Serve weather.get_forecasts the way a weather entity does."""

    async def get_forecasts(call: ServiceCall) -> dict:
        kind = call.data["type"]
        entity_id = call.data["entity_id"]
        if isinstance(entity_id, list):
            entity_id = entity_id[0]
        rows = [hourly] if kind == "hourly" else daily
        return {entity_id: {"forecast": rows}}

    hass.services.async_register(
        "weather",
        "get_forecasts",
        get_forecasts,
        supports_response=SupportsResponse.ONLY,
    )


async def _load(hass: HomeAssistant, entry: MockConfigEntry):
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    hass.states.async_set("switch.front_valve", "off")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry.runtime_data._last_observation


async def test_fahrenheit_forecast_survives_the_first_refresh(
    hass: HomeAssistant,
) -> None:
    """31°F stays 31°F. Treating it as Celsius would report about 87.8°F."""
    now = dt_util.now()
    hourly_at = (now + timedelta(hours=3)).isoformat()
    today = now.replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
    tomorrow = (now + timedelta(days=1)).replace(
        hour=12, minute=0, second=0, microsecond=0
    ).isoformat()
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            "temperature": 70,
            "temperature_unit": "°F",
            "humidity": 40,
            "wind_speed": 8,
            "wind_speed_unit": "mph",
            "precipitation_unit": "in",
        },
    )
    hass.states.async_set(
        "sensor.wind", "10", {"unit_of_measurement": "mph"}
    )
    hass.states.async_set(
        "sensor.pressure", "29.92", {"unit_of_measurement": "inHg"}
    )
    _install_forecast(
        hass,
        {
            "datetime": hourly_at,
            "temperature": 31,
            "wind_speed": 15,
            "precipitation": 0.2,
            "precipitation_probability": 70,
        },
        [
            {"datetime": today, "temperature": 70, "templow": 55, "precipitation": 0},
            {
                "datetime": tomorrow,
                "temperature": 48,
                "templow": 28,
                "precipitation": 0.4,
                "precipitation_probability": 80,
            },
        ],
    )
    observation = await _load(hass, _entry("°F"))
    lows = [low for _stamp, low in observation.forecast_lows]
    assert 31.0 in lows
    assert 28.0 in lows
    assert not any(abs(low - 87.8) < 0.2 for low in lows)
    winds = [speed for _stamp, speed in observation.hourly_wind]
    assert winds == pytest.approx([15.0])
    assert observation.wind_m_s == pytest.approx(10 * 0.44704)
    hourly_mm = [item[1] for item in observation.hourly_precip]
    hourly_chance = [item[2] for item in observation.hourly_precip]
    assert hourly_mm == pytest.approx([0.2 * 25.4])
    assert hourly_chance == [70.0]
    daily_mm = [item[1] for item in observation.daily_precip]
    daily_chance = [item[2] for item in observation.daily_precip]
    assert 0.4 * 25.4 == pytest.approx(daily_mm[-1])
    assert daily_chance[-1] == 80.0
    assert observation.inputs is not None
    assert observation.inputs.pressure_kpa == pytest.approx(29.92 * 3.386389, rel=1e-4)


async def test_celsius_forecast_is_converted_before_the_freeze_check(
    hass: HomeAssistant,
) -> None:
    """0°C is 32°F and -2°C is 28.4°F. Leaving the numbers raw would skip neither."""
    now = dt_util.now()
    hourly_at = (now + timedelta(hours=2)).isoformat()
    today = now.replace(hour=15, minute=0, second=0, microsecond=0).isoformat()
    tomorrow = (now + timedelta(days=1)).replace(
        hour=6, minute=0, second=0, microsecond=0
    ).isoformat()
    hass.states.async_set(
        "weather.home",
        "cloudy",
        {
            "temperature": 8,
            "temperature_unit": "°C",
            "humidity": 70,
            "wind_speed": 3,
            "wind_speed_unit": "m/s",
            "precipitation_unit": "mm",
        },
    )
    _install_forecast(
        hass,
        {
            "datetime": hourly_at,
            "temperature": 0,
            "wind_speed": 5,
            "precipitation": 2,
            "precipitation_probability": 40,
        },
        [
            {"datetime": today, "temperature": 8, "templow": 4, "precipitation": 0},
            {
                "datetime": tomorrow,
                "temperature": 3,
                "templow": -2,
                "precipitation": 10,
                "precipitation_probability": 90,
            },
        ],
    )
    observation = await _load(hass, _entry("°C"))
    lows = [low for _stamp, low in observation.forecast_lows]
    assert pytest.approx(32.0) in lows
    assert pytest.approx(28.4) in lows
    assert 0 not in lows
    assert -2 not in lows
    winds = [speed for _stamp, speed in observation.hourly_wind]
    assert winds == pytest.approx([5 / 0.44704])
    assert observation.wind_m_s == pytest.approx(3.0)
    hourly = observation.hourly_precip[0]
    assert hourly[1] == pytest.approx(2.0)
    assert hourly[2] == 40.0
    assert observation.daily_precip[-1][1] == pytest.approx(10.0)
    assert observation.daily_precip[-1][2] == 90.0
