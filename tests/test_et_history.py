"""Two restarts with the same recorded history keep ET0, RAW, and next watering."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast import climate_day
from custom_components.sprinklecast.climate_day import HistoryPoint
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

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CHICAGO = ZoneInfo("America/Chicago")
NIGHT = datetime(2026, 10, 19, 23, 30, tzinfo=CHICAGO)
LOCKED_MM = 6.5


def _freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    def frozen_now(tz=None):
        if tz is None:
            return NIGHT
        return NIGHT.astimezone(tz)

    monkeypatch.setattr(dt_util, "now", frozen_now)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Sprinklers",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 212.0,
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


def _point(hour: int, state: str, unit: str) -> HistoryPoint:
    return HistoryPoint(
        at=datetime(2026, 10, 19, hour, 0, tzinfo=CHICAGO),
        state=state,
        unit=unit,
        attributes={"unit_of_measurement": unit},
    )


def _history() -> dict[str, list[HistoryPoint]]:
    """One local day of Tempest-style readings. The live state is not in here."""
    return {
        "sensor.temp": [
            _point(6, "62", "°F"),
            _point(14, "88", "°F"),
            _point(22, "68", "°F"),
        ],
        "sensor.humidity": [
            _point(6, "85", "%"),
            _point(14, "35", "%"),
            _point(22, "70", "%"),
        ],
        "sensor.wind": [
            _point(6, "2", "mph"),
            _point(14, "9", "mph"),
            _point(22, "3", "mph"),
        ],
        "sensor.pressure": [
            _point(6, "29.85", "inHg"),
            _point(14, "29.70", "inHg"),
            _point(22, "29.90", "inHg"),
        ],
        "sensor.solar": [
            _point(6, "0", "W/m²"),
            _point(10, "700", "W/m²"),
            _point(14, "900", "W/m²"),
            _point(18, "50", "W/m²"),
            _point(22, "0", "W/m²"),
        ],
    }


def _live(hass: HomeAssistant, temp: str, humidity: str, wind: str, solar: str) -> None:
    hass.states.async_set(
        "weather.home",
        "clear-night",
        {
            "temperature": 50,
            "temperature_unit": "°F",
            "humidity": 90,
            "wind_speed": 20,
            "wind_speed_unit": "mph",
            "precipitation_unit": "in",
        },
    )
    hass.states.async_set("sensor.temp", temp, {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.humidity", humidity, {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.wind", wind, {"unit_of_measurement": "mph"})
    hass.states.async_set("sensor.pressure", "30.5", {"unit_of_measurement": "inHg"})
    hass.states.async_set("sensor.solar", solar, {"unit_of_measurement": "W/m²"})
    hass.states.async_set("switch.front", "off")


def _install_history(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded = _history()

    async def fake(_hass, entity_ids, _start, _end):
        return {entity_id: list(recorded.get(entity_id) or []) for entity_id in entity_ids}

    monkeypatch.setattr(climate_day, "async_entity_histories", fake)


def _snapshot(entry: MockConfigEntry) -> dict[str, object]:
    coordinator = entry.runtime_data
    zone_id = next(iter(entry.subentries))
    zone = coordinator.data.zones[zone_id]
    locked = coordinator.store.climate_day("2026-10-18")
    return {
        "method": coordinator.data.et0_method,
        "et0": coordinator.data.et0_mm,
        "detail": coordinator.data.et0_detail,
        "p": zone.p,
        "raw": zone.raw_mm,
        "etc": zone.etc_mm,
        "kc": zone.kc,
        "next": None if zone.next_run is None else zone.next_run.isoformat(),
        "later": coordinator._et_factors(
            coordinator._last_observation, NIGHT.date(), LOCKED_MM
        )[10],
        "history": [
            (item.get("date"), item.get("mm"), item.get("locked"))
            for item in coordinator.store.et0_history
            if isinstance(item, dict)
        ],
        "locked_et0": locked.get("et0_mm"),
        "locked_detail": locked.get("detail"),
    }


async def test_two_restarts_with_the_same_history_match(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live night readings differ. The recorded day does not, so the plan does not."""
    _freeze(monkeypatch)
    _install_history(monkeypatch)
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    _live(hass, "40", "99", "1", "0")
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    zone_id = next(iter(entry.subentries))
    coordinator.store.zone(zone_id)["deficit_mm"] = 12.0
    coordinator.store.zone(zone_id)["balance_date"] = "2026-10-19"
    finished = coordinator.store.climate_day("2026-10-18")
    finished["locked"] = True
    finished["et0_mm"] = LOCKED_MM
    finished["t_max_c"] = 30.0
    finished["t_min_c"] = 14.0
    finished["detail"] = "locked-on-purpose"
    coordinator.store.et0_history = [
        {"date": "2026-10-17", "mm": LOCKED_MM, "locked": True},
        {"date": "2026-10-18", "mm": LOCKED_MM, "locked": True},
    ]
    await coordinator.async_request_refresh()
    await hass.async_block_till_done()

    first = _snapshot(entry)
    assert first["method"] == "penman_monteith"
    assert "measured" in str(first["detail"])
    assert "recorded history" in str(first["detail"])
    assert "Instantaneous" not in str(first["detail"])
    assert first["next"] is not None
    assert first["etc"] == pytest.approx(float(first["kc"]) * LOCKED_MM)
    assert first["etc"] != pytest.approx(float(first["kc"]) * float(first["et0"]))
    assert first["later"] == pytest.approx(1.0)
    assert first["locked_et0"] == LOCKED_MM
    assert first["locked_detail"] == "locked-on-purpose"
    assert ("2026-10-19",) not in {(item[0],) for item in first["history"]}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    _live(hass, "100", "10", "40", "1000")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    second = _snapshot(entry)
    assert second["et0"] == first["et0"]
    assert second["method"] == first["method"]
    assert second["detail"] == first["detail"]
    assert second["p"] == first["p"]
    assert second["raw"] == first["raw"]
    assert second["next"] == first["next"]
    assert second["later"] == first["later"]
    assert second["history"] == first["history"]
    assert second["locked_et0"] == LOCKED_MM
    assert second["locked_detail"] == "locked-on-purpose"
