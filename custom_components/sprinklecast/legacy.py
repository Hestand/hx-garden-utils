"""Import a Smart Water install into Sprinklecast.

Home Assistant cannot change a config entry's domain. HACS installs only
one folder from ``custom_components``, and ``smart_water`` sorts ahead of
``sprinklecast``, so this repository ships Sprinklecast only. On startup,
any leftover Smart Water config entry is copied: data, options, zone
subentries, the ``.storage`` file, devices, and entity registry rows. Entity
IDs stay the same. The old entry is then removed.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from types import MappingProxyType

from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntry,
    ConfigEntryDisabler,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util.json import json_loads

from .const import (
    CONF_MODE,
    CONF_NOTIFY_TARGET,
    CONF_RECENT_RAIN_HOURS,
    CONF_RECENT_RAIN_MM,
    CONF_SEND_PLAN_NOTIFICATIONS,
    DOMAIN,
    LEGACY_DOMAIN,
    MODE_OFF,
    NAME,
)
from .store import STORAGE_VERSION

_LOGGER = logging.getLogger(__name__)

ISSUE_FOLDER = "remove_smart_water_folder"
ISSUE_LOADED = "smart_water_still_loaded"
ISSUE_FAILED = "smart_water_import_failed"


def plan_notifications_enabled(options: dict) -> bool:
    """Evening plan notices. On when the option says so, or when a target is set."""
    if CONF_SEND_PLAN_NOTIFICATIONS in options:
        return bool(options.get(CONF_SEND_PLAN_NOTIFICATIONS))
    return bool(str(options.get(CONF_NOTIFY_TARGET) or "").strip())


def clean_options(options: dict) -> tuple[dict, bool]:
    """Drop mode and recent rain. Return options and whether automatic must be off.

    Mode ``off`` stores automatic watering off. ``notify_only`` and ``auto``
    leave the stored switch alone. Plan notifications are on when a notify
    target is already set.
    """
    updated = dict(options)
    mode = str(updated.pop(CONF_MODE, "") or "")
    updated.pop(CONF_RECENT_RAIN_HOURS, None)
    updated.pop(CONF_RECENT_RAIN_MM, None)
    if CONF_SEND_PLAN_NOTIFICATIONS not in updated:
        updated[CONF_SEND_PLAN_NOTIFICATIONS] = bool(
            str(updated.get(CONF_NOTIFY_TARGET) or "").strip()
        )
    return updated, mode == MODE_OFF


def rewrite_unique_id(unique_id: str, old_id: str, new_id: str) -> str:
    """Swap the config-entry prefix and keep the rest of the id."""
    if unique_id == old_id or unique_id.startswith(f"{old_id}_"):
        return new_id + unique_id[len(old_id) :]
    return unique_id


def is_mode_entity(unique_id: str, entry_id: str) -> bool:
    """The retired Mode sensor. Its entity id is not kept."""
    return unique_id == f"{entry_id}_mode"


def legacy_folder(hass: HomeAssistant) -> Path:
    """The old integration directory in the Home Assistant config folder."""
    return Path(hass.config.path("custom_components", LEGACY_DOMAIN))


async def store_automatic_off(hass: HomeAssistant, entry_id: str) -> None:
    """Store automatic watering off when a migrated hub's mode was off."""
    from .store import SmartWaterStore

    raw = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
    loaded = await raw.async_load()
    if not loaded or not loaded.get("automatic"):
        return
    store = SmartWaterStore(hass, entry_id)
    await store.async_load()
    store.automatic = False
    await store.async_save()


def drop_mode_entity(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the Mode sensor from either domain."""
    registry = er.async_get(hass)
    for platform in (DOMAIN, LEGACY_DOMAIN):
        entity_id = registry.async_get_entity_id("sensor", platform, f"{entry_id}_mode")
        if entity_id is not None:
            registry.async_remove(entity_id)


async def apply_version_10(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop mode and recent rain on a Sprinklecast entry."""
    options, force_off = clean_options(dict(entry.options))
    hass.config_entries.async_update_entry(
        entry, options=options, version=10, minor_version=1
    )
    if force_off:
        await store_automatic_off(hass, entry.entry_id)
    drop_mode_entity(hass, entry.entry_id)


def _issue(hass: HomeAssistant, key: str, *, fixable: bool = False) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        key,
        is_fixable=fixable,
        severity=ir.IssueSeverity.WARNING,
        translation_key=key,
    )


async def async_import_smart_water(hass: HomeAssistant) -> None:
    """Copy leftover Smart Water hubs, then ask the user to delete the old folder."""
    lock: asyncio.Lock = hass.data.setdefault(f"{DOMAIN}_import_lock", asyncio.Lock())
    async with lock:
        await _async_import_locked(hass)


async def _async_import_locked(hass: HomeAssistant) -> None:
    if LEGACY_DOMAIN in hass.config.components:
        _issue(hass, ISSUE_LOADED, fixable=True)
        _LOGGER.warning(
            "Smart Water is still loaded. Delete config/custom_components/smart_water "
            "and restart so Sprinklecast can keep your hub, zones, and entity IDs."
        )
        return
    ir.async_delete_issue(hass, DOMAIN, ISSUE_LOADED)
    failed = False
    for old in list(hass.config_entries.async_entries(LEGACY_DOMAIN)):
        if not await _import_one(hass, old):
            failed = True
    if failed:
        _issue(hass, ISSUE_FAILED)
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_FAILED)
    if legacy_folder(hass).exists():
        _issue(hass, ISSUE_FOLDER, fixable=True)
        _LOGGER.warning(
            "Delete config/custom_components/smart_water and restart. "
            "Sprinklecast is the integration now."
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_FOLDER)


def remove_legacy_folder(hass: HomeAssistant) -> bool:
    """Delete ``config/custom_components/smart_water`` and nothing else.

    A symlink is unlinked. The directory is removed only when its name is
    ``smart_water`` inside ``custom_components``.
    """
    path = legacy_folder(hass)
    if not path.exists() and not path.is_symlink():
        return False
    if path.name != LEGACY_DOMAIN:
        return False
    parent = path.parent
    if parent.name != "custom_components":
        return False
    sprinklecast = Path(hass.config.path("custom_components", DOMAIN)).resolve()
    if path.is_symlink():
        if path.resolve() == sprinklecast:
            _LOGGER.error(
                "Refusing to delete %s because it points at Sprinklecast", path
            )
            return False
        path.unlink()
        return True
    if not path.is_dir():
        return False
    if path.resolve() == sprinklecast:
        _LOGGER.error("Refusing to delete the Sprinklecast folder")
        return False
    shutil.rmtree(path)
    return True


async def _import_one(hass: HomeAssistant, old: ConfigEntry) -> bool:
    """Create one Sprinklecast hub from a Smart Water config entry."""
    options, force_off = clean_options(dict(old.options))
    subentries = [
        {
            "data": dict(subentry.data),
            "subentry_type": subentry.subentry_type,
            "title": subentry.title,
            "unique_id": subentry.unique_id,
            "subentry_id": subentry.subentry_id,
        }
        for subentry in old.subentries.values()
    ]
    new = ConfigEntry(
        data=dict(old.data),
        disabled_by=ConfigEntryDisabler.USER,
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options=options,
        pref_disable_new_entities=old.pref_disable_new_entities,
        pref_disable_polling=old.pref_disable_polling,
        source=SOURCE_IMPORT,
        subentries_data=subentries,
        title=old.title,
        unique_id=old.unique_id,
        version=10,
    )
    await hass.config_entries.async_add(new)
    try:
        await _move_store(hass, old.entry_id, new.entry_id, force_off=force_off)
        # Entities first. Moving a device fires a registry event that deletes
        # every entity still linked to the device's previous config entry.
        _move_entities(hass, old.entry_id, new.entry_id)
        _move_devices(hass, old.entry_id, new.entry_id)
        await hass.config_entries.async_remove(old.entry_id)
    except Exception:
        _LOGGER.exception("Sprinklecast could not import %s", old.title)
        await hass.config_entries.async_remove(new.entry_id)
        return False
    await hass.config_entries.async_set_disabled_by(new.entry_id, None)
    _LOGGER.info("Moved Smart Water hub %s to Sprinklecast", old.title)
    return True


def _storage_path(hass: HomeAssistant, key: str) -> Path:
    return Path(hass.config.path(".storage", key))


async def _read_store(hass: HomeAssistant, key: str) -> dict | None:
    """Load a store, including a file the startup cache thinks is missing.

    After Home Assistant has listed ``.storage``, a key that was not in that
    list is reported as absent and the file is never opened. Read the file
    directly when it is there so a stale listing cannot look like an empty hub.
    """
    path = _storage_path(hass, key)
    if path.is_file():

        def _read() -> dict | None:
            raw = json_loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
                return raw["data"]
            return None

        try:
            return await hass.async_add_executor_job(_read)
        except (OSError, TypeError, ValueError) as err:
            _LOGGER.error("Could not read %s: %s", path, err)
            return None
    store = Store(hass, STORAGE_VERSION, key)
    store._manager.async_invalidate(key)  # noqa: SLF001
    loaded = await store.async_load()
    return loaded if isinstance(loaded, dict) else None


async def _move_store(
    hass: HomeAssistant, old_id: str, new_id: str, *, force_off: bool
) -> None:
    """Copy bucket, history, and the automatic switch. Leave the old file if it fails."""
    old_key = f"{LEGACY_DOMAIN}.{old_id}"
    new_key = f"{DOMAIN}.{new_id}"
    loaded = await _read_store(hass, old_key)
    old_path = _storage_path(hass, old_key)
    if loaded is None and old_path.is_file():
        raise RuntimeError(f"Smart Water storage {old_key} could not be read")
    data = dict(loaded or {})
    # Mode off is the only case that turns the switch off. auto and
    # notify_only keep the stored flag, including when it is on.
    if "automatic" not in data:
        data["automatic"] = False
    if force_off:
        data["automatic"] = False
    zones = data.get("zones") if isinstance(data.get("zones"), dict) else {}
    _LOGGER.info(
        "Copying Smart Water storage %s: automatic=%s, zones=%s",
        old_key,
        data.get("automatic"),
        {
            zone_id: zone.get("deficit_mm")
            for zone_id, zone in zones.items()
            if isinstance(zone, dict)
        },
    )
    new_store = Store(hass, STORAGE_VERSION, new_key)
    await new_store.async_save(data)
    read_back = await _read_store(hass, new_key) or {}
    if bool(read_back.get("automatic")) != bool(data.get("automatic")):
        raise RuntimeError("Sprinklecast storage lost the automatic watering flag")
    copied = read_back.get("zones") if isinstance(read_back.get("zones"), dict) else {}
    for zone_id, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        got = copied.get(zone_id)
        if not isinstance(got, dict) or got.get("deficit_mm") != zone.get("deficit_mm"):
            raise RuntimeError(f"Sprinklecast storage lost the bucket for {zone_id}")
    old_store = Store(hass, STORAGE_VERSION, old_key)
    old_store._manager.async_invalidate(old_key)  # noqa: SLF001
    await old_store.async_remove()

    def _unlink() -> None:
        if old_path.is_file() or old_path.is_symlink():
            old_path.unlink()

    await hass.async_add_executor_job(_unlink)
    if old_path.exists():
        raise RuntimeError(f"Could not delete {old_path}")


def _move_devices(hass: HomeAssistant, old_id: str, new_id: str) -> None:
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, old_id):
        identifiers = set()
        for domain, ident in device.identifiers:
            if domain == LEGACY_DOMAIN:
                identifiers.add((DOMAIN, rewrite_unique_id(ident, old_id, new_id)))
            else:
                identifiers.add((domain, ident))
        registry.async_update_device(
            device.id,
            new_identifiers=identifiers or {(DOMAIN, new_id)},
            new_config_entry_id=new_id,
            new_config_subentry_id=device.config_subentry_id,
            manufacturer=NAME,
        )


def _move_entities(hass: HomeAssistant, old_id: str, new_id: str) -> None:
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, old_id):
        if is_mode_entity(entity.unique_id, old_id):
            registry.async_remove(entity.entity_id)
            continue
        registry.async_update_entity_platform(
            entity.entity_id,
            DOMAIN,
            new_config_entry_id=new_id,
            new_config_subentry_id=entity.config_subentry_id,
            new_unique_id=rewrite_unique_id(entity.unique_id, old_id, new_id),
        )
