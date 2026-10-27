"""Water next chance arms one morning without waiting for the watering point."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import DOMAIN
from sprinklecast.planner import build_plan
from sprinklecast.week_plan import project_week
from tests.test_planner import _request, _zone
from tests.test_week_plan import _freeze_saturday, _live_entry, _load, _sensor

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CHICAGO = ZoneInfo("America/Chicago")


def _dry(**overrides):
    base = dict(
        name="Lawn",
        deficit_mm=2.0,
        raw_mm=20.0,
        taw_mm=40.0,
        etc_mm=0.2,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soak_override_min=0,
        max_cycle_override_min=60,
        min_interval_days=None,
    )
    base.update(overrides)
    return _zone(**base)


def _morning(zone, **overrides):
    start = datetime(2026, 10, 20, 5, 0, tzinfo=CHICAGO)
    base = dict(
        start_at=start,
        earliest_start=datetime(2026, 10, 20, 4, 0, tzinfo=CHICAGO),
        finish_by=datetime(2026, 10, 20, 9, 0, tzinfo=CHICAGO),
        allowed_weekdays=("tue", "thu", "sun"),
        plan_hour=23,
    )
    base.update(overrides)
    return build_plan(_request(zone, **base))


def test_refill_runs_before_the_watering_point() -> None:
    waiting = _morning(_dry())
    assert waiting.zones[0].scheduled is False
    armed = _morning(_dry(next_chance="refill"))
    assert armed.zones[0].scheduled is True
    assert "refill the estimated need" in armed.zones[0].reason
    assert armed.zones[0].net_mm == pytest.approx(2.0, abs=0.2)


def test_fill_completely_targets_the_whole_bucket() -> None:
    plan = _morning(_dry(next_chance="fill"))
    assert plan.zones[0].scheduled is True
    assert "fill the root zone completely" in plan.zones[0].reason
    assert plan.zones[0].net_mm == pytest.approx(40.0, abs=1.0)


def test_rain_keeps_the_chance_from_running() -> None:
    plan = _morning(_dry(next_chance="refill", currently_raining=True))
    assert plan.zones[0].scheduled is False
    assert "raining" in plan.zones[0].reason


def test_a_cap_is_reported_when_the_fill_does_not_fit() -> None:
    plan = _morning(
        _dry(
            next_chance="fill",
            max_run_min=5,
            precipitation_rate_in_hr=0.5,
        )
    )
    assert plan.zones[0].scheduled is True
    assert plan.zones[0].carried_min >= 0.5
    assert "cap" in plan.zones[0].reason


def test_the_arm_is_only_the_next_chance() -> None:
    zone = _dry(next_chance="refill")
    result = project_week(
        (zone,),
        now=datetime(2026, 10, 19, 18, 0, tzinfo=CHICAGO),
        timezone="America/Chicago",
        forecast_precip_mm=0.0,
        forecast_skip_mm=None,
        hub_rain_wet=False,
        mode="notify_only",
        automatic=False,
        allowed_weekdays=("tue", "thu", "sun"),
        blackout_start_hour=None,
        blackout_end_hour=None,
        whole_minutes=True,
        max_daily_runtime_min=None,
        areas={zone.zone_id: 1000.0},
        days=8,
        next_chance_amount="refill",
    )
    watered = [
        day["date"]
        for day in result["days"]
        if day["zones"][0]["scheduled"]
    ]
    assert watered == ["2026-10-20"]


async def test_the_button_service_and_cancel_show_on_the_schedule(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Arming survives the coordinator save and clears from the cancel service."""
    _freeze_saturday(monkeypatch)
    entry = await _load(hass, _live_entry())
    zone_id = next(iter(entry.subentries))
    await hass.services.async_call(
        DOMAIN,
        "set_bucket",
        {"zone": "Test1", "deficit_mm": 1},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        "water_next_chance",
        {"amount": "Fill completely"},
        blocking=True,
    )
    await hass.async_block_till_done()
    schedule = _sensor(hass, entry, f"{entry.entry_id}_watering_schedule")
    nxt = _sensor(hass, entry, f"{entry.entry_id}_{zone_id}_next_run")
    assert schedule.attributes["water_next_chance"] == "Fill completely"
    assert nxt.attributes["water_next_chance"] == "Fill completely"
    assert entry.runtime_data.store.next_chance["amount"] == "fill"
    await hass.services.async_call(DOMAIN, "cancel_water_next_chance", {}, blocking=True)
    await hass.async_block_till_done()
    schedule = _sensor(hass, entry, f"{entry.entry_id}_watering_schedule")
    assert schedule.attributes["water_next_chance"] == "off"
    assert entry.runtime_data.store.next_chance is None


async def test_root_entities_exist(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_saturday(monkeypatch)
    entry = await _load(hass, _live_entry())
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    assert registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_water_next_chance"
    )
    assert registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_cancel_water_next_chance"
    )
    assert registry.async_get_entity_id(
        "select", DOMAIN, f"{entry.entry_id}_water_next_chance_amount"
    )
