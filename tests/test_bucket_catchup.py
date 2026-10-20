"""A hand-set soil level does not skip the day, and a missed step is caught up once."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
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

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CHICAGO = ZoneInfo("America/Chicago")
LOCKED_ET0_MM = 5.0


class _Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment


def _freeze(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    def frozen_now(tz=None):
        if tz is None:
            return clock.moment
        return clock.moment.astimezone(tz)

    monkeypatch.setattr(dt_util, "now", frozen_now)


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


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Sprinklers",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={CONF_ELEVATION_M: 219.0, CONF_PLAN_HOUR: 23},
        subentries_data=[
            _zone("Front", "switch.front_valve"),
            _zone("Back", "switch.back_valve"),
        ],
    )


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
    hass.states.async_set("switch.front_valve", "off")
    hass.states.async_set("switch.back_valve", "off")


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _entity(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


def _lock(entry: MockConfigEntry, day: str, et0_mm: float = LOCKED_ET0_MM) -> None:
    """Pin a finished day's water loss so catch-up does not recompute it."""
    climate = entry.runtime_data.store.climate_day(day)
    climate["locked"] = True
    climate["et0_mm"] = et0_mm


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def _restart(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_manual_set_then_rollover_reduces_the_level(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand set is the level at that moment. The next day still takes the full loss."""
    clock = _Clock(datetime(2026, 10, 19, 15, 0, tzinfo=CHICAGO))
    _freeze(monkeypatch, clock)
    _weather(hass)
    entry = await _setup(hass)
    front = "front"
    number_id = _entity(hass, "number", f"{entry.entry_id}_{front}_soil_water_level")
    sensor_id = _entity(hass, "sensor", f"{entry.entry_id}_{front}_soil_water")

    await hass.services.async_call(
        NUMBER_DOMAIN,
        "set_value",
        {"entity_id": number_id, "value": 75},
        blocking=True,
    )
    stored = entry.runtime_data.store.zone(front)
    assert stored.get("balance_date") is None
    assert entry.runtime_data.data.zones[front].full_pct == pytest.approx(75, abs=0.2)

    _lock(entry, "2026-10-19")
    clock.moment = datetime(2026, 10, 20, 8, 0, tzinfo=CHICAGO)
    await _refresh(hass, entry)

    zone = entry.runtime_data.data.zones[front]
    assert zone.full_pct < 74
    assert stored["balance_date"] == "2026-10-19"
    deficit = stored["deficit_mm"]
    full = zone.full_pct

    await _refresh(hass, entry)
    assert stored["deficit_mm"] == pytest.approx(deficit)
    assert entry.runtime_data.data.zones[front].full_pct == pytest.approx(full)

    await _restart(hass, entry)
    assert entry.runtime_data.store.zone(front)["deficit_mm"] == pytest.approx(deficit)
    assert entry.runtime_data.store.zone(front)["balance_date"] == "2026-10-19"
    assert float(hass.states.get(sensor_id).state) == pytest.approx(full, abs=1)
    assert float(hass.states.get(number_id).state) == pytest.approx(
        float(hass.states.get(sensor_id).state), abs=1
    )
    sensor = hass.states.get(sensor_id)
    assert sensor.attributes["device_class"] == "moisture"
    assert sensor.attributes["unit_of_measurement"] == "%"
    assert "Soil moisture" in sensor.name


async def test_restart_over_the_plan_hour_catches_up_once(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refresh before the plan hour does not apply the day. The next morning does, once."""
    clock = _Clock(datetime(2026, 10, 19, 22, 0, tzinfo=CHICAGO))
    _freeze(monkeypatch, clock)
    _weather(hass)
    entry = await _setup(hass)
    front = entry.runtime_data.store.zone("front")
    assert front.get("balance_date") is None
    assert entry.runtime_data.data.zones["front"].full_pct == pytest.approx(100, abs=0.2)

    _lock(entry, "2026-10-19")
    clock.moment = datetime(2026, 10, 20, 8, 0, tzinfo=CHICAGO)
    await _refresh(hass, entry)
    assert front["balance_date"] == "2026-10-19"
    deficit = front["deficit_mm"]
    assert deficit > 0

    await _refresh(hass, entry)
    await _restart(hass, entry)
    assert entry.runtime_data.store.zone("front")["deficit_mm"] == pytest.approx(deficit)
    assert entry.runtime_data.store.zone("front")["balance_date"] == "2026-10-19"


async def test_manual_set_does_not_block_a_later_day(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting the level on one day still lets that day and the next day move the bucket."""
    clock = _Clock(datetime(2026, 10, 19, 15, 0, tzinfo=CHICAGO))
    _freeze(monkeypatch, clock)
    _weather(hass)
    entry = await _setup(hass)
    stored = entry.runtime_data.store.zone("front")
    stored["balance_date"] = "2026-10-18"
    number_id = _entity(hass, "number", f"{entry.entry_id}_front_soil_water_level")
    await hass.services.async_call(
        NUMBER_DOMAIN,
        "set_value",
        {"entity_id": number_id, "value": 75},
        blocking=True,
    )
    assert stored["balance_date"] == "2026-10-18"
    assert entry.runtime_data.data.zones["front"].full_pct == pytest.approx(75, abs=0.2)

    _lock(entry, "2026-10-19")
    clock.moment = datetime(2026, 10, 20, 8, 0, tzinfo=CHICAGO)
    await _refresh(hass, entry)
    after_missed = stored["deficit_mm"]
    assert stored["balance_date"] == "2026-10-19"
    assert entry.runtime_data.data.zones["front"].full_pct < 74

    clock.moment = datetime(2026, 10, 20, 23, 0, tzinfo=CHICAGO)
    await _refresh(hass, entry)
    assert stored["balance_date"] == "2026-10-20"
    assert stored["deficit_mm"] > after_missed + 0.2
    held = stored["deficit_mm"]
    await _refresh(hass, entry)
    assert stored["deficit_mm"] == pytest.approx(held)


async def test_upgrade_applies_the_day_a_hand_set_stamped(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0.14.6 wrote the balance date on a hand set. The next start still applies that day."""
    clock = _Clock(datetime(2026, 10, 20, 8, 0, tzinfo=CHICAGO))
    _freeze(monkeypatch, clock)
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    # Seed through the store the setup will load. The first refresh is the upgrade.
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_save(
        {
            "zones": {
                "front": {
                    "deficit_mm": 6.0,
                    "balance_date": "2026-10-19",
                    "bucket_history": [
                        {"date": "2026-10-19", "full_pct": 75.0, "set": True}
                    ],
                },
                "back": {"deficit_mm": 1.0, "balance_date": "2026-10-18"},
            },
            "climate_days": [
                {
                    "date": "2026-10-19",
                    "locked": True,
                    "et0_mm": LOCKED_ET0_MM,
                    "t_max_c": 30.0,
                    "t_min_c": 18.0,
                }
            ],
        }
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    front = entry.runtime_data.store.zone("front")
    back = entry.runtime_data.store.zone("back")
    assert front["balance_rewound"] is True
    assert front["balance_date"] == "2026-10-19"
    assert front["deficit_mm"] > 6.0
    assert back["balance_date"] == "2026-10-19"
    assert back["deficit_mm"] > 1.0
    front_deficit = front["deficit_mm"]
    back_deficit = back["deficit_mm"]

    await _refresh(hass, entry)
    assert front["deficit_mm"] == pytest.approx(front_deficit)
    assert back["deficit_mm"] == pytest.approx(back_deficit)


async def test_average_soil_moisture_skips_disabled_zones(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock(datetime(2026, 10, 19, 15, 0, tzinfo=CHICAGO))
    _freeze(monkeypatch, clock)
    _weather(hass)
    entry = await _setup(hass)
    average_id = _entity(hass, "sensor", f"{entry.entry_id}_average_soil_moisture")
    assert float(hass.states.get(average_id).state) == pytest.approx(100, abs=0.2)
    state = hass.states.get(average_id)
    assert state.attributes["device_class"] == "moisture"
    assert state.attributes["unit_of_measurement"] == "%"

    number_id = _entity(hass, "number", f"{entry.entry_id}_front_soil_water_level")
    await hass.services.async_call(
        NUMBER_DOMAIN,
        "set_value",
        {"entity_id": number_id, "value": 50},
        blocking=True,
    )
    assert float(hass.states.get(average_id).state) == pytest.approx(75, abs=0.6)

    await entry.runtime_data.async_set_zone_enabled("back", False)
    await hass.async_block_till_done()
    assert float(hass.states.get(average_id).state) == pytest.approx(50, abs=0.6)
