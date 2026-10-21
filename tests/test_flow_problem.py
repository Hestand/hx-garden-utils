"""Flow problem stays off without a baseline and keeps its result across a reload."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_FLOW_KIND,
    CONF_FLOW_SENSOR,
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


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_FLOW_SENSOR: "sensor.main_flow",
            CONF_FLOW_KIND: "rate",
        },
        subentries_data=[
            _zone("Bed", "valve.bed", "bed"),
            _zone("Front", "valve.front", "front"),
            _zone("Side", "valve.side", "side"),
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


def _run(gpm: float, at: str) -> dict:
    return {"at": at, "gpm": gpm, "minutes": 10}


async def test_flow_problem_uses_the_baseline_and_survives_reload(
    hass: HomeAssistant,
) -> None:
    """On only against a saved baseline. A learned-only high run stays off."""
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_bed_flow",
        suggested_object_id="bed_flow_check",
        config_entry=entry,
        original_name="Flow check",
    )
    for suffix, name in (
        ("learned_gpm", "Learned flow rate"),
        ("flow_trend", "Flow trend"),
    ):
        registry.async_get_or_create(
            "sensor",
            DOMAIN,
            f"{entry.entry_id}_bed_{suffix}",
            suggested_object_id=f"bed_{suffix}",
            config_entry=entry,
            original_name=name,
        )
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    high = [_run(12.0, f"2026-10-1{index}T12:00:00+00:00") for index in range(5)]
    await store.async_save(
        {
            "zones": {
                "bed": {
                    "deficit_mm": 4.0,
                    "learned_gpm": 10.0,
                    "last_run_gpm": 20.0,
                    "gpm_samples": [10.0, 10.0, 10.0],
                    "flow_alert": "high_flow",
                    "flow_history": [_run(20.0, "2026-10-20T12:00:00+00:00")] * 5,
                },
                "front": {
                    "deficit_mm": 4.0,
                    "baseline_gpm": 10.0,
                    "baseline_source": "catch_cup",
                    "last_run_gpm": 20.0,
                    "flow_history": [],
                },
                "side": {
                    "deficit_mm": 4.0,
                    "baseline_gpm": 10.0,
                    "baseline_source": "flow_test",
                    "last_run_gpm": 11.0,
                    "flow_history": high,
                },
            }
        }
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    bed = _binary(hass, entry.entry_id, "bed")
    front = _binary(hass, entry.entry_id, "front")
    side = _binary(hass, entry.entry_id, "side")
    assert bed.state == "off"
    assert bed.attributes["reason"] == "No baseline yet"
    assert bed.attributes["last_run_gpm"] == pytest.approx(20.0)
    assert bed.attributes["baseline_gpm"] is None
    assert front.state == "on"
    assert front.attributes["reason"] == "Last run is above the baseline"
    assert front.attributes["baseline_gpm"] == pytest.approx(10.0)
    assert front.attributes["percent_difference"] == pytest.approx(100.0)
    assert front.attributes["high_pct"] == pytest.approx(30.0)
    assert front.attributes["low_pct"] == pytest.approx(25.0)
    assert side.state == "on"
    assert side.attributes["reason"] == "Recent runs are above the baseline"
    assert side.attributes["percent_difference"] == pytest.approx(10.0)
    assert side.attributes["trend_status"] == "high_trend"
    assert side.attributes["trend_pct"] == pytest.approx(20.0)
    assert side.attributes["trend"] == (
        "Baseline is set at 10.00 gal/min. Recent runs are above it."
    )
    baseline = _sensor(hass, entry.entry_id, "bed", "baseline_flow")
    assert float(baseline.state) == pytest.approx(10.0)
    assert baseline.attributes["source"] == "learned"
    front_base = _sensor(hass, entry.entry_id, "front", "baseline_flow")
    assert float(front_base.state) == pytest.approx(10.0)
    assert front_base.attributes["source"] == "catch_cup"
    for suffix in ("flow", "learned_gpm", "flow_trend"):
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_bed_{suffix}"
            )
            is None
        )
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"flow_check_replaced_{entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_key == "flow_check_replaced"
    removed = ir.async_get(hass).async_get_issue(
        DOMAIN, f"flow_diagnostics_removed_{entry.entry_id}"
    )
    assert removed is not None
    assert removed.translation_key == "flow_diagnostics_removed"

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert _binary(hass, entry.entry_id, "bed").state == "off"
    assert _binary(hass, entry.entry_id, "front").state == "on"
    assert _binary(hass, entry.entry_id, "side").state == "on"
    assert (
        ir.async_get(hass)
        .async_get_issue(DOMAIN, f"flow_check_replaced_{entry.entry_id}")
        is not None
    )


async def test_flow_problem_does_not_open_a_repair_without_the_old_sensor(
    hass: HomeAssistant,
) -> None:
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"flow_check_replaced_{entry.entry_id}"
        )
        is None
    )
    assert (
        ir.async_get(hass).async_get_issue(
            DOMAIN, f"flow_diagnostics_removed_{entry.entry_id}"
        )
        is None
    )
    assert _binary(hass, entry.entry_id, "bed").state == "off"


def _binary(hass: HomeAssistant, entry_id: str, zone_id: str):
    return _entity(hass, "binary_sensor", entry_id, zone_id, "flow_problem")


def _sensor(hass: HomeAssistant, entry_id: str, zone_id: str, suffix: str):
    return _entity(hass, "sensor", entry_id, zone_id, suffix)


def _entity(hass: HomeAssistant, domain: str, entry_id: str, zone_id: str, suffix: str):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        domain, DOMAIN, f"{entry_id}_{zone_id}_{suffix}"
    )
    assert entity_id
    state = hass.states.get(entity_id)
    assert state is not None
    return state
