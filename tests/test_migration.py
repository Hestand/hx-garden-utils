"""Smart Water entries become Sprinklecast without new entity IDs."""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.setup import async_setup_component
import probatio
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_NOTIFY_TARGET,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    LEGACY_DOMAIN,
)
from custom_components.sprinklecast.legacy import (
    ISSUE_FOLDER,
    ISSUE_LOADED,
    async_import_smart_water,
    clean_options,
    plan_notifications_enabled,
    remove_legacy_folder,
)
from custom_components.sprinklecast.store import RUN_HISTORY_LIMIT, SmartWaterStore, remember_run

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_ZONES = (
    ("bed", "Bed"),
    ("front", "Front Yard"),
    ("left_front", "Left Yard Front"),
    ("left", "Left Side"),
    ("back", "Backyard"),
    ("right", "Right Side"),
)


def _zone(zone_id: str, title: str) -> dict:
    return {
        "data": {
            CONF_PLANT_TYPE: "bermuda",
            CONF_SOIL_TYPE: "loam",
            CONF_SPRINKLER_TYPE: "spray",
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_PRECIPITATION_RATE: 1.5,
            CONF_VALVE_ENTITY: f"switch.{zone_id}",
        },
        "subentry_type": "zone",
        "title": title,
        "unique_id": zone_id,
        "subentry_id": zone_id,
    }


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
    for zone_id, _title in _ZONES:
        hass.states.async_set(f"switch.{zone_id}", "off")


def test_retired_options_follow_the_mode_and_the_notify_target() -> None:
    """Off stores automatic off. A notify target turns plan notices on."""
    off, force_off = clean_options(
        {
            "mode": "off",
            "notify_target": "notify.mobile_app_phone",
            "recent_rain_mm": 2.5,
            "recent_rain_hours": 12,
            "elevation_m": 219,
        }
    )
    assert force_off is True
    assert "mode" not in off
    assert "recent_rain_mm" not in off
    assert "recent_rain_hours" not in off
    assert off["send_plan_notifications"] is True
    assert off["elevation_m"] == 219

    kept, leave_switch = clean_options({"mode": "notify_only", "dynamic_start": False})
    assert leave_switch is False
    assert kept["send_plan_notifications"] is False
    assert plan_notifications_enabled({"notify_target": "mobile_app_phone"}) is True
    assert plan_notifications_enabled({"send_plan_notifications": False, "notify_target": "x"}) is False

    auto, auto_off = clean_options({"mode": "auto"})
    assert auto_off is False
    assert auto["send_plan_notifications"] is False


def test_run_history_keeps_the_latest_runs() -> None:
    state: dict = {}
    for index in range(RUN_HISTORY_LIMIT + 5):
        remember_run(state, {"at": f"t{index}", "result": "ok"})
    assert len(state["run_history"]) == RUN_HISTORY_LIMIT
    assert state["run_history"][0]["at"] == "t5"
    assert state["run_history"][-1]["at"] == f"t{RUN_HISTORY_LIMIT + 4}"


async def test_version_10_drops_mode_and_stores_automatic_off(
    hass: HomeAssistant,
) -> None:
    """A Sprinklecast entry at version 9 picks up the option cleanup."""
    _weather(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        version=9,
        minor_version=1,
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            "mode": "off",
            CONF_NOTIFY_TARGET: "notify.phone",
            "recent_rain_mm": 2.5,
            "recent_rain_hours": 12,
            "dynamic_start": False,
            CONF_ELEVATION_M: 219.0,
        },
        subentries_data=[_zone("bed", "Bed")],
    )
    entry.add_to_hass(hass)
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}").async_save(
        {"automatic": True, "zones": {"bed": {"deficit_mm": 3.0}}}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 10
    assert "mode" not in entry.options
    assert "recent_rain_mm" not in entry.options
    assert entry.options["send_plan_notifications"] is True
    assert entry.options["dynamic_start"] is False
    store = SmartWaterStore(hass, entry.entry_id)
    await store.async_load()
    assert store.automatic is False
    assert store.zone("bed")["deficit_mm"] == 3.0
    registry = er.async_get(hass)
    unique_ids = {
        item.unique_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert f"{entry.entry_id}_mode" not in unique_ids
    assert f"{entry.entry_id}_watering_calendar" in unique_ids


async def test_smart_water_import_keeps_entity_ids_and_zone_state(
    hass: HomeAssistant,
) -> None:
    """The live Water Test hub moves, including six zones and a renamed entity."""
    _weather(hass)
    old = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Water Test",
        unique_id="water-test",
        version=9,
        minor_version=1,
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            "mode": "off",
            CONF_NOTIFY_TARGET: "notify.mobile_app_phone",
            "recent_rain_mm": 2.5,
            "recent_rain_hours": 12,
            "dynamic_start": False,
            CONF_ELEVATION_M: 219.0,
        },
        subentries_data=[_zone(zone_id, title) for zone_id, title in _ZONES],
    )
    old.add_to_hass(hass)
    devices = dr.async_get(hass)
    hub = devices.async_get_or_create(
        config_entry_id=old.entry_id,
        identifiers={(LEGACY_DOMAIN, old.entry_id)},
        name="Water Test",
        manufacturer="Smart Water",
    )
    front = devices.async_get_or_create(
        config_entry_id=old.entry_id,
        config_subentry_id="front",
        identifiers={(LEGACY_DOMAIN, f"{old.entry_id}_front")},
        name="Front Yard",
        manufacturer="Smart Water",
        via_device_id=hub.id,
    )
    entities = er.async_get(hass)
    plan = entities.async_get_or_create(
        "sensor",
        LEGACY_DOMAIN,
        f"{old.entry_id}_tonight_plan",
        suggested_object_id="sprinklers_water_test_plan_today",
        config_entry=old,
        device_id=hub.id,
    )
    mode = entities.async_get_or_create(
        "sensor",
        LEGACY_DOMAIN,
        f"{old.entry_id}_mode",
        suggested_object_id="sprinklers_water_test_mode",
        config_entry=old,
        device_id=hub.id,
    )
    soil = entities.async_get_or_create(
        "sensor",
        LEGACY_DOMAIN,
        f"{old.entry_id}_front_soil_water",
        suggested_object_id="front_yard_soil_water",
        config_entry=old,
        config_subentry_id="front",
        device_id=front.id,
    )
    await Store(hass, 1, f"{LEGACY_DOMAIN}.{old.entry_id}").async_save(
        {
            "automatic": True,
            "zones": {
                "bed": {
                    "deficit_mm": 4.2,
                    "last_run": {
                        "at": "2026-10-17T05:00:00-05:00",
                        "minutes": 5,
                        "net_mm": 1.2,
                        "result": "ok",
                    },
                },
                "front": {"deficit_mm": 1.0},
            },
            "weather": {"date": "2026-10-19", "rain_mm": 0.0},
        }
    )

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(LEGACY_DOMAIN) == []
    migrated = hass.config_entries.async_entries(DOMAIN)
    assert len(migrated) == 1
    new = migrated[0]
    assert new.title == "Water Test"
    assert new.domain == DOMAIN
    assert new.version == 10
    assert new.unique_id == "water-test"
    assert set(new.subentries) == {zone_id for zone_id, _title in _ZONES}
    assert new.subentries["front"].title == "Front Yard"
    assert "mode" not in new.options
    assert "recent_rain_mm" not in new.options
    assert new.options["send_plan_notifications"] is True
    assert new.options["dynamic_start"] is False

    store = SmartWaterStore(hass, new.entry_id)
    await store.async_load()
    assert store.automatic is False
    assert store.zone("bed")["deficit_mm"] == 4.2
    assert store.zone("bed")["last_run"]["minutes"] == 5
    assert await Store(hass, 1, f"{LEGACY_DOMAIN}.{old.entry_id}").async_load() is None

    assert entities.async_get(plan.entity_id) is not None
    moved_plan = entities.async_get(plan.entity_id)
    assert moved_plan is not None
    assert moved_plan.entity_id == "sensor.sprinklers_water_test_plan_today"
    assert moved_plan.platform == DOMAIN
    assert moved_plan.unique_id == f"{new.entry_id}_tonight_plan"
    assert moved_plan.config_entry_id == new.entry_id
    moved_soil = entities.async_get(soil.entity_id)
    assert moved_soil is not None
    assert moved_soil.entity_id == "sensor.front_yard_soil_water"
    assert moved_soil.unique_id == f"{new.entry_id}_front_soil_water"
    assert moved_soil.config_subentry_id == "front"
    assert entities.async_get(mode.entity_id) is None
    assert not any(
        item.unique_id.endswith("_mode")
        for item in er.async_entries_for_config_entry(entities, new.entry_id)
    )
    calendar = next(
        item
        for item in er.async_entries_for_config_entry(entities, new.entry_id)
        if item.unique_id == f"{new.entry_id}_watering_calendar"
    )
    assert calendar.entity_id == "calendar.water_test_watering"

    moved_hub = devices.async_get(hub.id)
    assert moved_hub is not None
    assert moved_hub.config_entry_id == new.entry_id
    assert (DOMAIN, new.entry_id) in moved_hub.identifiers
    assert moved_hub.manufacturer == "Sprinklecast"
    moved_front = devices.async_get(front.id)
    assert moved_front is not None
    assert (DOMAIN, f"{new.entry_id}_front") in moved_front.identifiers
    assert moved_front.config_subentry_id == "front"
    assert moved_front.via_device_id == hub.id

    assert hass.services.has_service(DOMAIN, "calculate_plan")
    assert hass.services.has_service(LEGACY_DOMAIN, "calculate_plan")

    calendar_state = hass.states.get(calendar.entity_id)
    assert calendar_state is not None
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": calendar.entity_id,
            "start_date_time": "2026-10-01T00:00:00-05:00",
            "end_date_time": "2026-11-01T00:00:00-05:00",
        },
        blocking=True,
        return_response=True,
    )
    events = response[calendar.entity_id]["events"]
    assert any(event["summary"] == "Bed" for event in events)


async def test_import_waits_while_smart_water_is_still_loaded(
    hass: HomeAssistant,
) -> None:
    """A loaded old component owns the entities, so the copy waits for a restart."""
    old = MockConfigEntry(domain=LEGACY_DOMAIN, title="Water Test", version=9)
    old.add_to_hass(hass)
    hass.config.components.add(LEGACY_DOMAIN)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert hass.config_entries.async_entries(LEGACY_DOMAIN) == [old]
    assert hass.config_entries.async_entries(DOMAIN) == []
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LOADED)
    assert issue is not None
    assert issue.is_fixable is True


def _storage_file(hass: HomeAssistant, key: str, data: dict) -> Path:
    path = Path(hass.config.path(".storage", key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": 1, "minor_version": 1, "key": key, "data": data}
        ),
        encoding="utf-8",
    )
    return path


async def _stale_storage(hass: HomeAssistant) -> None:
    """List .storage before the legacy file exists, which is the live miss."""
    manager = Store(hass, 1, f"{DOMAIN}.probe")._manager
    await manager.async_initialize()


async def test_import_keeps_the_switch_and_buckets_when_the_cache_misses_the_file(
    hass: HomeAssistant,
) -> None:
    """Notify only and Auto keep the switch. The bucket and history are copied."""
    _weather(hass)
    old = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Water Test",
        version=9,
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={"mode": "notify_only", "dynamic_start": False, CONF_ELEVATION_M: 219.0},
        subentries_data=[_zone("front", "Front Yard"), _zone("bed", "Bed")],
    )
    old.add_to_hass(hass)
    await _stale_storage(hass)
    key = f"{LEGACY_DOMAIN}.{old.entry_id}"
    history = [{"date": "2026-10-18", "full_pct": 41.0}]
    runs = [{"at": "2026-10-17T05:00:00-05:00", "minutes": 8, "result": "ok"}]
    _storage_file(
        hass,
        key,
        {
            "automatic": True,
            "zones": {
                "front": {
                    "deficit_mm": 18.5,
                    "bucket_history": history,
                    "run_history": runs,
                },
                "bed": {"deficit_mm": 4.25, "bucket_history": [], "run_history": []},
            },
        },
    )
    manager = Store(hass, 1, f"{DOMAIN}.probe")._manager
    assert key not in (manager._files or set())

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(LEGACY_DOMAIN) == []
    new = hass.config_entries.async_entries(DOMAIN)[0]
    store = SmartWaterStore(hass, new.entry_id)
    await store.async_load()
    assert store.automatic is True
    assert store.zone("front")["deficit_mm"] == 18.5
    assert store.zone("bed")["deficit_mm"] == 4.25
    assert store.zone("front")["bucket_history"] == history
    assert store.zone("front")["run_history"] == runs
    assert not Path(hass.config.path(".storage", key)).is_file()


async def test_import_leaves_an_unreadable_store_in_place(hass: HomeAssistant) -> None:
    """A file that cannot be read is not deleted, and the old hub stays."""
    old = MockConfigEntry(domain=LEGACY_DOMAIN, title="Water Test", version=9)
    old.add_to_hass(hass)
    path = Path(hass.config.path(".storage", f"{LEGACY_DOMAIN}.{old.entry_id}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{", encoding="utf-8")

    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(LEGACY_DOMAIN) == [old]
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == "{"


async def test_user_flow_imports_smart_water_without_yaml(hass: HomeAssistant) -> None:
    """Add integration offers the import when a Smart Water hub is still there."""
    _weather(hass)
    old = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Water Test",
        version=9,
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={"mode": "auto"},
        subentries_data=[_zone("front", "Front Yard")],
    )
    old.add_to_hass(hass)
    await Store(hass, 1, f"{LEGACY_DOMAIN}.{old.entry_id}").async_save(
        {"automatic": True, "zones": {"front": {"deficit_mm": 9.0}}}
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.MENU
    assert list(result["menu_options"]) == ["live", "simulation", "import_legacy"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_legacy"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "imported"
    assert hass.config_entries.async_entries(LEGACY_DOMAIN) == []
    new = hass.config_entries.async_entries(DOMAIN)[0]
    assert new.title == "Water Test"
    store = SmartWaterStore(hass, new.entry_id)
    await store.async_load()
    assert store.automatic is True
    assert store.zone("front")["deficit_mm"] == 9.0


async def test_user_flow_removes_a_loaded_smart_water_folder(hass: HomeAssistant) -> None:
    """A loaded old component is not copied until the folder is gone and HA restarts."""
    old = MockConfigEntry(domain=LEGACY_DOMAIN, title="Water Test", version=9)
    old.add_to_hass(hass)
    hass.config.components.add(LEGACY_DOMAIN)
    folder = Path(hass.config.path("custom_components", LEGACY_DOMAIN))
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{}", encoding="utf-8")

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "import_legacy"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "import_legacy"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "restart_to_import"
    assert not folder.exists()
    assert hass.config_entries.async_entries(LEGACY_DOMAIN) == [old]
    assert hass.config_entries.async_entries(DOMAIN) == []


def test_empty_yaml_key_is_accepted() -> None:
    """``sprinklecast:`` is valid and does not reject the rest of the config."""
    from custom_components.sprinklecast import CONFIG_SCHEMA

    assert CONFIG_SCHEMA({DOMAIN: None, "http": {}})[DOMAIN] == {}
    assert CONFIG_SCHEMA({DOMAIN: {}, "frontend": {}})[DOMAIN] == {}
    assert "http" in CONFIG_SCHEMA({"http": {}})
    with pytest.raises(probatio.Invalid):
        CONFIG_SCHEMA({DOMAIN: {"mode": "off"}})


async def test_yaml_key_starts_the_integration(hass: HomeAssistant) -> None:
    """The empty key the 0.12.0 workaround used still loads, and can be removed later."""
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: None})
    await hass.async_block_till_done()
    assert DOMAIN in hass.config.components


def test_remove_legacy_folder_deletes_only_smart_water(hass: HomeAssistant) -> None:
    """The repair must not follow a symlink into Sprinklecast."""
    root = Path(hass.config.path("custom_components"))
    sprinkle = root / DOMAIN
    sprinkle.mkdir(parents=True)
    (sprinkle / "manifest.json").write_text("{}", encoding="utf-8")
    legacy = root / LEGACY_DOMAIN
    legacy.symlink_to(sprinkle, target_is_directory=True)
    assert remove_legacy_folder(hass) is False
    assert legacy.is_symlink()
    assert (sprinkle / "manifest.json").is_file()

    legacy.unlink()
    legacy.mkdir()
    (legacy / "manifest.json").write_text("{}", encoding="utf-8")
    assert remove_legacy_folder(hass) is True
    assert not legacy.exists()
    assert (sprinkle / "manifest.json").is_file()


async def test_repair_deletes_the_leftover_folder(hass: HomeAssistant) -> None:
    """The fix flow removes the folder and asks for a restart when it is loaded."""
    assert await async_setup_component(hass, "repairs", {})
    folder = Path(hass.config.path("custom_components", LEGACY_DOMAIN))
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    await async_import_smart_water(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_FOLDER)
    assert issue is not None
    assert issue.is_fixable is True

    manager = repairs_flow_manager(hass)
    assert manager is not None
    result = await manager.async_init(DOMAIN, data={"issue_id": ISSUE_FOLDER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert not folder.exists()

    folder.mkdir()
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    hass.config.components.add(LEGACY_DOMAIN)
    await async_import_smart_water(hass)
    loaded = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LOADED)
    assert loaded is not None
    assert loaded.is_fixable is True
    result = await manager.async_init(DOMAIN, data={"issue_id": ISSUE_LOADED})
    result = await manager.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "restart_required"
    assert not folder.exists()
    assert ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_LOADED) is not None
