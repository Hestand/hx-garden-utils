"""The executor turns mocked on/off entities on and off, one at a time."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, ServiceRegistry
from homeassistant.helpers.storage import Store
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smart_water.const import (
    CONF_ELEVATION_M,
    CONF_MODE,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_MAX_RUN_MIN,
    DOMAIN,
    MODE_AUTO,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


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


def _zone(entity: str, title: str) -> dict[str, Any]:
    return {
        "data": {
            CONF_PLANT_TYPE: "st_augustine",
            CONF_SOIL_TYPE: "loam",
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_SPRINKLER_TYPE: "spray",
            CONF_PRECIPITATION_RATE: 1.5,
            CONF_VALVE_ENTITY: entity,
        },
        "subentry_type": "zone",
        "title": title,
        "unique_id": title.casefold().replace(" ", "_"),
    }


def _entry(**options: Any) -> MockConfigEntry:
    base = {
        CONF_ELEVATION_M: 219.0,
        CONF_MODE: MODE_AUTO,
        CONF_SUNRISE_BUFFER_MIN: 30,
        CONF_PLAN_HOUR: 0,
    }
    base.update(options)
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options=base,
        subentries_data=[_zone("switch.front_valve", "Front"), _zone("switch.back_valve", "Back")],
    )


def _patch(
    monkeypatch: pytest.MonkeyPatch, hass: HomeAssistant, entities: set[str]
) -> list[tuple[str, str]]:
    """Intercept valve calls. ServiceRegistry is slotted, so patch the class."""
    calls: list[tuple[str, str]] = []
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
        if isinstance(entity, list):
            entity = entity[0] if entity else None
        if entity in entities and domain == "switch":
            calls.append((entity, service))
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


async def _instant(_seconds: float) -> None:
    return None


async def _setup(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, entry: MockConfigEntry
) -> list[tuple[str, str]]:
    _weather(hass)
    hass.states.async_set("switch.front_valve", "off")
    hass.states.async_set("switch.back_valve", "off")
    calls = _patch(monkeypatch, hass, {"switch.front_valve", "switch.back_valve"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.executor._sleep = _instant
    return calls


async def test_run_now_orders_on_and_off_and_does_not_overlap(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _entry()
    calls = await _setup(hass, monkeypatch, entry)
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Front", "deficit_mm": 20}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Back", "deficit_mm": 20}, blocking=True
    )
    calls.clear()
    await hass.services.async_call(
        DOMAIN, "run_now", {"zone": "Front"}, blocking=True
    )
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    ons = [call for call in calls if call[1] == "turn_on"]
    offs = [call for call in calls if call[1] == "turn_off"]
    assert ons and len(ons) == len(offs)
    for index, (entity, service) in enumerate(calls):
        if service == "turn_on":
            assert calls[index + 1] == (entity, "turn_off")
    assert all(entity == "switch.front_valve" for entity, _service in calls)
    assert hass.states.get("switch.front_valve").state == "off"
    assert hass.states.get("switch.back_valve").state == "off"
    assert entry.runtime_data.store.automatic is False


async def test_startup_turns_off_a_zone_left_on(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _weather(hass)
    hass.states.async_set("switch.front_valve", "on")
    entry = _entry()
    entry.add_to_hass(hass)
    store = Store(hass, 1, f"smart_water.{entry.entry_id}")
    await store.async_save({"watering_entity": "switch.front_valve", "zones": {}})
    calls = _patch(monkeypatch, hass, {"switch.front_valve", "switch.back_valve"})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert ("switch.front_valve", "turn_off") in calls
    assert hass.states.get("switch.front_valve").state == "off"
    assert entry.runtime_data.store.watering_entity is None


async def test_runtime_cap_stops_the_run(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _entry(**{CONF_MAX_RUN_MIN: 5})
    calls = await _setup(hass, monkeypatch, entry)
    slept: list[tuple[float, str | None]] = []

    async def record(seconds: float) -> None:
        state = hass.states.get("switch.front_valve")
        slept.append((seconds, None if state is None else state.state))

    entry.runtime_data.executor._sleep = record
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Front", "deficit_mm": 30}, blocking=True
    )
    calls.clear()
    slept.clear()
    await hass.services.async_call(DOMAIN, "run_now", {"zone": "Front"}, blocking=True)
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    armed = False
    for entity, service in calls:
        assert entity == "switch.front_valve"
        if service == "turn_on":
            armed = True
        elif service == "turn_off":
            armed = False
    # Soak sleeps happen after turn_off. Only time spent with the valve on counts.
    on_seconds = sum(seconds for seconds, state in slept if state == "on")
    assert on_seconds <= 5 * 60 + 1
    assert on_seconds > 0
    assert not armed
    assert hass.states.get("switch.front_valve").state == "off"


async def test_master_switch_blocks_the_night_and_run_now_does_not(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = _entry()
    calls = await _setup(hass, monkeypatch, entry)
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Front", "deficit_mm": 20}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "calculate_plan", {"notify": False}, blocking=True
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.store.automatic is False
    assert not any(service == "turn_on" for _entity, service in calls)

    calls.clear()
    await hass.services.async_call(DOMAIN, "run_now", {"zone": "Front"}, blocking=True)
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    assert any(service == "turn_on" for _entity, service in calls)
    assert hass.states.get("switch.front_valve").state == "off"
