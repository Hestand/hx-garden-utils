"""Smart Water custom integration.

v0.8 waters in the morning: start at 05:00, finish by 09:00, and start no
earlier than 04:00. When the Automatic watering switch is on, it runs each
zone's stored on/off entity one at a time. The executor uses switch, valve,
and input_boolean services. It does not call Hydrawise.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event

from .const import (
    CONF_EARLIEST_HOUR,
    CONF_EARLIEST_START,
    CONF_FINISH_TIME,
    CONF_MAX_RUN_MIN,
    CONF_START_TIME,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_ZONE_MAX_RUN_MIN,
    DEFAULT_EARLIEST_START,
    DEFAULT_FINISH_TIME,
    DEFAULT_START_TIME,
    DOMAIN,
    PLATFORMS,
)
from .schedule import migrate_options

__all__ = ["DOMAIN"]

_LOGGER = logging.getLogger(__name__)
_FRONTEND_KEY = f"{DOMAIN}_frontend"


def _migrate_run_cap(options: dict) -> dict:
    """Move the old all-zones cap onto the per-zone default.

    The optional hub nightly total stays unset. A stored 60 becomes the
    per-zone default of 60. A custom total becomes that per-zone default too.
    """
    updated = dict(options)
    old = updated.pop(CONF_MAX_RUN_MIN, None)
    if old not in (None, "") and CONF_ZONE_MAX_RUN_MIN not in updated:
        updated[CONF_ZONE_MAX_RUN_MIN] = old
    return updated


def _migrate_morning_window(options: dict) -> dict:
    """Replace the sunrise deadline with the morning window.

    Existing hubs have not turned automatic watering on, so the new
    defaults replace a stored sunrise buffer and earliest hour.
    """
    updated = dict(options)
    updated.pop(CONF_SUNRISE_BUFFER_MIN, None)
    updated.pop(CONF_EARLIEST_HOUR, None)
    updated[CONF_START_TIME] = DEFAULT_START_TIME
    updated[CONF_FINISH_TIME] = DEFAULT_FINISH_TIME
    updated[CONF_EARLIEST_START] = DEFAULT_EARLIEST_START
    return updated


async def async_migrate_entry(hass, entry) -> bool:
    """Move schedule options to allowed days. Zone numbers stay as stored.

    Version 4 rewrites hub options only. A retired odd- or even-address
    preset becomes its weekday set and a 10:00–19:00 blackout. The dry-run
    option is removed. Automatic watering stays off in the store.

    Version 5 adds flow, budget, and report options. It does not call
    migrate_options again, so a hub that already chose its days keeps them.

    Version 6 moves the old hub valve cap onto the per-zone default and
    leaves the hub nightly total off. It does not call migrate_options.

    Version 7 replaces the sunrise deadline with a 05:00 start, a 09:00
    finish, and a 04:00 earliest start. It does not call migrate_options.
    """
    if entry.version > 7:
        return False
    if entry.version < 4:
        hass.config_entries.async_update_entry(
            entry,
            options=migrate_options(dict(entry.options)),
            version=4,
            minor_version=1,
        )
    if entry.version < 5:
        hass.config_entries.async_update_entry(entry, version=5, minor_version=1)
    if entry.version < 6:
        hass.config_entries.async_update_entry(
            entry,
            options=_migrate_run_cap(dict(entry.options)),
            version=6,
            minor_version=1,
        )
    if entry.version < 7:
        hass.config_entries.async_update_entry(
            entry,
            options=_migrate_morning_window(dict(entry.options)),
            version=7,
            minor_version=1,
        )
    return True


async def async_setup(hass, config) -> bool:
    """Register the Lovelace card when the frontend is already loaded."""
    await async_register_card(hass)
    return True


async def async_register_card(hass) -> None:
    """Serve the card and add it as an extra module.

    Tests and a core that has not loaded the frontend skip this. The card
    can still be added by hand as a JavaScript module at
    ``/smart_water_static/smart-water-card.js``.
    """
    if hass.data.get(_FRONTEND_KEY):
        return
    if "frontend" not in hass.config.components:
        return
    try:
        from homeassistant.components.frontend import add_extra_js_url
        from homeassistant.components.http import StaticPathConfig
    except ImportError:
        return
    frontend = Path(__file__).parent / "frontend"
    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    url_path="/smart_water_static",
                    path=str(frontend),
                    cache_headers=False,
                )
            ]
        )
        add_extra_js_url(hass, "/smart_water_static/smart-water-card.js")
    except (RuntimeError, ValueError) as err:
        _LOGGER.debug("Smart Water card was not registered: %s", err)
        return
    hass.data[_FRONTEND_KEY] = True


async def async_setup_entry(hass, entry) -> bool:
    """Set up one hub from a config entry."""
    from .coordinator import SmartWaterCoordinator
    from .executor import WateringExecutor
    from .services import async_setup_services
    from .store import SmartWaterStore

    store = SmartWaterStore(hass, entry.entry_id)
    await store.async_load()
    coordinator = SmartWaterCoordinator(hass, entry, store)
    executor = WateringExecutor(hass, store)
    coordinator.executor = executor
    executor.skip_checker = coordinator.live_skip
    executor.rain_since = coordinator.rain_since_mark
    executor.on_cycle_done = coordinator.async_credit_cycle
    executor.on_status = coordinator.poke_status
    executor.hub_cap_fn = coordinator.hub_nightly_cap
    entry.runtime_data = coordinator
    # A restart must not leave a zone running. This happens before entities exist.
    await executor.async_quiesce()

    async def _stop(_event: Event) -> None:
        await executor.stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _stop))
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_track_plan_time()
    # Reloads when options or zones change. Do not also use OptionsFlowWithReload
    # or async_update_reload_and_abort; those raise if a listener is registered.
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    async_setup_services(hass)
    return True


async def async_unload_entry(hass, entry) -> bool:
    """Turn zones off, unload a hub, and drop services when it was the last one."""
    from homeassistant.config_entries import ConfigEntryState

    from .services import async_unload_services

    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None and coordinator.executor is not None:
        await coordinator.executor.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False
    others = [
        candidate
        for candidate in hass.config_entries.async_entries(DOMAIN)
        if candidate.entry_id != entry.entry_id
        and candidate.state is ConfigEntryState.LOADED
    ]
    if not others:
        async_unload_services(hass)
    return True


async def async_update_listener(hass, entry) -> None:
    """Reload after an options or subentry change."""
    hass.config_entries.async_schedule_reload(entry.entry_id)
