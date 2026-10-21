"""Catch-cup sequence, measured rate, and the permanent flow baseline."""

from __future__ import annotations

import asyncio

from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant, ServiceRegistry
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_FLOW_KIND,
    CONF_FLOW_SENSOR,
    CONF_HUB_NIGHTLY_CAP_MIN,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_RAIN_SENSOR,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_ZONE_MAX_RUN_MIN,
    DOMAIN,
    EVENT_FLOW_ALERT,
)
from custom_components.sprinklecast.presets import sprinkler_efficiency
from custom_components.sprinklecast.store import SmartWaterStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _zone(title: str, valve: str, unique_id: str) -> dict:
    return {
        "data": {
            CONF_PLANT_TYPE: "warm_season_turf",
            CONF_SOIL_TYPE: "clay_loam",
            CONF_SLOPE_PCT: 6,
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_ROOT_DEPTH_IN: 6,
            CONF_SPRINKLER_TYPE: "spray",
            CONF_PRECIPITATION_RATE: 1.5,
            CONF_VALVE_ENTITY: valve,
        },
        "subentry_type": "zone",
        "title": title,
        "unique_id": unique_id,
        "subentry_id": unique_id,
    }


def _entry(*, flow: bool = False, rain: bool = False) -> MockConfigEntry:
    options = {
        CONF_ELEVATION_M: 219.0,
        CONF_ZONE_MAX_RUN_MIN: 5,
        CONF_HUB_NIGHTLY_CAP_MIN: 10,
    }
    if flow:
        options[CONF_FLOW_SENSOR] = "sensor.main_flow"
        options[CONF_FLOW_KIND] = "total"
    if rain:
        options[CONF_RAIN_SENSOR] = "binary_sensor.rain"
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options=options,
        subentries_data=[
            _zone("Front", "switch.front_valve", "front"),
            _zone("Back", "switch.back_valve", "back"),
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


def _patch_valves(monkeypatch: pytest.MonkeyPatch, hass: HomeAssistant) -> list[tuple[str, str]]:
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
        if domain == "switch" and entity in {"switch.front_valve", "switch.back_valve"}:
            calls.append((entity, service))
            hass.states.async_set(entity, "on" if service == SERVICE_TURN_ON else "off")
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


async def _setup(hass: HomeAssistant, entry: MockConfigEntry):
    _weather(hass)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _run(hass: HomeAssistant, entry: MockConfigEntry, **data) -> list[float]:
    slept: list[float] = []

    async def instant(seconds: float) -> None:
        slept.append(seconds)

    entry.runtime_data.executor._pause = instant
    await hass.services.async_call(DOMAIN, "run_catch_cup_test", data, blocking=True)
    task = entry.runtime_data.executor._task
    if task is not None:
        await task
    await hass.async_block_till_done()
    return slept


async def test_catch_cup_runs_each_enabled_zone_for_the_full_minutes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fifteen minutes each, one at a time, ignoring caps and soak.

    The bucket is credited from the zone's current precipitation rate.
    """
    entry = await _setup(hass, _entry())
    calls = _patch_valves(monkeypatch, hass)
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Front", "deficit_mm": 20}, blocking=True
    )
    before = entry.runtime_data.store.zone("front")["deficit_mm"]
    entry.runtime_data.store.zone("back")["enabled"] = False
    slept = await _run(hass, entry, minutes=15)
    assert sum(slept) == pytest.approx(900.0)
    assert calls == [
        ("switch.front_valve", SERVICE_TURN_ON),
        ("switch.front_valve", SERVICE_TURN_OFF),
    ]
    # 15 min at 1.5 in/hr and the spray efficiency. Depth entry replaces this later.
    credited = (15 / 60.0) * 1.5 * sprinkler_efficiency("spray") * 25.4
    assert entry.runtime_data.store.zone("front")["deficit_mm"] == pytest.approx(
        before - credited
    )
    assert hass.states.get("switch.front_valve").state == "off"
    issues = ir.async_get(hass)
    assert issues.async_get_issue(DOMAIN, f"catch_cup_{entry.entry_id}") is None


async def test_two_zones_run_back_to_back_without_a_soak(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = await _setup(hass, _entry())
    calls = _patch_valves(monkeypatch, hass)
    slept = await _run(hass, entry, minutes=10)
    assert sum(slept) == pytest.approx(1200.0)
    assert [item[0] for item in calls] == [
        "switch.front_valve",
        "switch.front_valve",
        "switch.back_valve",
        "switch.back_valve",
    ]


async def test_rain_skips_the_test_and_stop_cancels_it(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = await _setup(hass, _entry(rain=True))
    calls = _patch_valves(monkeypatch, hass)
    hass.states.async_set("binary_sensor.rain", "on")
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "run_catch_cup_test", {}, blocking=True
        )
    assert calls == []

    hass.states.async_set("binary_sensor.rain", "off")

    async def blocked(_seconds: float) -> None:
        await asyncio.Event().wait()

    entry.runtime_data.executor._pause = blocked
    await hass.services.async_call(DOMAIN, "run_catch_cup_test", {"zone": "Front"}, blocking=True)
    for _ in range(10):
        await hass.async_block_till_done()
        if hass.states.get("switch.front_valve").state == "on":
            break
    assert hass.states.get("switch.front_valve").state == "on"
    await hass.services.async_call(DOMAIN, "stop_all", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("switch.front_valve").state == "off"
    assert ("switch.back_valve", SERVICE_TURN_ON) not in calls


async def test_depth_sets_the_rate_and_credits_only_the_change(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = await _setup(hass, _entry())
    _patch_valves(monkeypatch, hass)
    await hass.services.async_call(
        DOMAIN, "set_bucket", {"zone": "Front", "deficit_mm": 20}, blocking=True
    )
    await _run(hass, entry, zone="Front", minutes=15)
    after_run = entry.runtime_data.store.zone("front")["deficit_mm"]
    assert after_run < 20
    await hass.services.async_call(
        DOMAIN,
        "set_catch_cup_result",
        {"zone": "Front", "depth_in": 0.25},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = entry.runtime_data.store.zone("front")
    assert state["catch_cup"]["precipitation_rate_in_hr"] == pytest.approx(1.0)
    assert state["catch_cup"]["minutes"] == 15
    assert state["catch_cup"]["depth_in"] == pytest.approx(0.25)
    assert state["deficit_mm"] == pytest.approx(20 - 0.25 * 25.4)
    # The rate is runtime state. The zone config is not rewritten, so the hub
    # does not reload.
    assert entry.subentries["front"].data[CONF_PRECIPITATION_RATE] == pytest.approx(1.5)
    assert entry.runtime_data.data.zones["front"].precipitation_rate_in_hr == pytest.approx(
        1.0
    )

    await hass.services.async_call(
        DOMAIN,
        "set_catch_cup_result",
        {"zone": "Front", "depth_in": 0.5, "minutes": 15},
        blocking=True,
    )
    await hass.async_block_till_done()
    state = entry.runtime_data.store.zone("front")
    assert state["deficit_mm"] == pytest.approx(20 - 0.5 * 25.4)
    assert state["catch_cup"]["precipitation_rate_in_hr"] == pytest.approx(2.0)

    registry = er.async_get(hass)
    number_id = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_front_catch_cup_depth"
    )
    assert number_id
    number = hass.states.get(number_id)
    assert number is not None
    assert number.attributes["precipitation_rate_in_hr"] == pytest.approx(2.0)
    assert number.attributes["tested"]
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: number_id, "value": number.state},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert entry.runtime_data.store.zone("front")["deficit_mm"] == pytest.approx(20 - 0.5 * 25.4)


async def test_metered_run_saves_baseline_and_alerts_against_it(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The catch-cup gallons per minute is kept, and a later run uses that number."""
    entry = await _setup(hass, _entry(flow=True))
    _patch_valves(monkeypatch, hass)
    hass.states.async_set("sensor.main_flow", "100", {"unit_of_measurement": "gal"})
    events: list = []
    hass.bus.async_listen(EVENT_FLOW_ALERT, lambda event: events.append(event))

    async def one_gpm(seconds: float) -> None:
        state = hass.states.get("sensor.main_flow")
        current = float(state.state)
        hass.states.async_set(
            "sensor.main_flow",
            str(current + seconds / 60.0),
            {"unit_of_measurement": "gal"},
        )

    entry.runtime_data.executor._pause = one_gpm
    await hass.services.async_call(
        DOMAIN, "run_catch_cup_test", {"zone": "Front", "minutes": 15}, blocking=True
    )
    task = entry.runtime_data.executor._task
    if task is not None:
        await task
    await hass.async_block_till_done()

    state = entry.runtime_data.store.zone("front")
    assert state["baseline_gpm"] == pytest.approx(1.0)
    assert state["baseline_source"] == "catch_cup"
    assert state["baseline_gpm_at"]
    assert events == []
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"catch_cup_{entry.entry_id}")
    assert issue is not None

    reloaded = SmartWaterStore(hass, entry.entry_id)
    await reloaded.async_load()
    assert reloaded.zones["front"]["baseline_gpm"] == pytest.approx(1.0)

    registry = er.async_get(hass)
    for suffix in ("baseline_flow", "flow_vs_baseline", "last_run_gpm"):
        assert registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_front_{suffix}"
        )
    for suffix in ("learned_gpm", "flow_trend"):
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_front_{suffix}"
            )
            is None
        )
    baseline = hass.states.get(
        registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_front_baseline_flow")
    )
    assert float(baseline.state) == pytest.approx(1.0)
    assert baseline.attributes["source"] == "catch_cup"
    assert baseline.attributes["date"]

    coordinator = entry.runtime_data
    await coordinator.async_credit_cycle(
        zone_id="front", minutes=10, net_mm=1, gallons=20, result="ok", gpm=2.0
    )
    await hass.async_block_till_done()
    assert any(event.data["kind"] == "high_flow" for event in events)
    assert coordinator.store.zone("front")["baseline_gpm"] == pytest.approx(1.0)

    await hass.services.async_call(
        DOMAIN, "reset_flow_learning", {"zone": "Front"}, blocking=True
    )
    assert entry.runtime_data.store.zone("front")["baseline_gpm"] == pytest.approx(1.0)
    assert entry.runtime_data.store.zone("front")["learned_gpm"] is None
    await hass.services.async_call(
        DOMAIN,
        "reset_flow_learning",
        {"zone": "Front", "clear_baseline": True},
        blocking=True,
    )
    assert entry.runtime_data.store.zone("front")["baseline_gpm"] is None


async def test_trend_alerts_when_the_median_drifts_and_a_single_run_does_not(
    hass: HomeAssistant,
) -> None:
    entry = await _setup(hass, _entry(flow=True))
    events: list = []
    hass.bus.async_listen(EVENT_FLOW_ALERT, lambda event: events.append(event))
    await hass.services.async_call(
        DOMAIN, "set_flow_baseline", {"zone": "Front", "gpm": 10}, blocking=True
    )
    coordinator = entry.runtime_data
    assert coordinator.store.zone("front")["baseline_source"] == "manual"
    assert coordinator.store.zone("front")["flow_history"] == []
    registry = er.async_get(hass)
    problem_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_front_flow_problem"
    )
    problem = hass.states.get(problem_id)
    assert problem is not None
    assert problem.state == "off"
    assert (
        problem.attributes["trend"]
        == "Baseline is set at 10.00 gal/min. Trend needs 5 normal runs (0 so far)."
    )
    assert problem.attributes["trend_status"] == "learning"
    for _ in range(5):
        await coordinator.async_credit_cycle(
            zone_id="front", minutes=10, net_mm=1, gallons=112, result="ok", gpm=11.2
        )
    await hass.async_block_till_done()
    kinds = [event.data["kind"] for event in events]
    assert "high_flow" not in kinds
    assert "low_flow" not in kinds
    assert "high_trend" in kinds
    zone = coordinator.data.zones["front"]
    assert zone.flow_vs_baseline_pct == pytest.approx(12.0)
    assert zone.flow_trend_status == "high_trend"
    assert "Baseline is set" in zone.flow_trend_detail


async def test_a_second_press_does_not_restart_or_cancel(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three presses in a row must leave the first test running."""
    entry = await _setup(hass, _entry())
    calls = _patch_valves(monkeypatch, hass)

    async def blocked(_seconds: float) -> None:
        await asyncio.Event().wait()

    entry.runtime_data.executor._pause = blocked
    await hass.services.async_call(
        DOMAIN, "run_catch_cup_test", {"zone": "Front"}, blocking=True
    )
    for _ in range(10):
        await hass.async_block_till_done()
        if hass.states.get("switch.front_valve").state == "on":
            break
    assert hass.states.get("switch.front_valve").state == "on"
    calls.clear()
    await hass.services.async_call(
        DOMAIN, "run_catch_cup_test", {"zone": "Front"}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "run_catch_cup_test", {"zone": "Back"}, blocking=True
    )
    await hass.async_block_till_done()
    assert calls == []
    assert hass.states.get("switch.front_valve").state == "on"
    await hass.services.async_call(DOMAIN, "stop_all", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("switch.front_valve").state == "off"
