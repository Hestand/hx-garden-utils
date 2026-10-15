"""Smart Water custom integration.

v0.5 plans the week and, when the Automatic watering switch is on, runs
each zone's stored on/off entity one at a time. The executor uses
switch, valve, and input_boolean services. It does not call Hydrawise.
"""

from __future__ import annotations

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event

from .const import DOMAIN, PLATFORMS
from .schedule import migrate_options

__all__ = ["DOMAIN"]


async def async_migrate_entry(hass, entry) -> bool:
    """Move schedule options to allowed days. Zone numbers stay as stored.

    Version 4 rewrites hub options only. A retired odd- or even-address
    preset becomes its weekday set and a 10:00–19:00 blackout. The dry-run
    option is removed. Automatic watering stays off in the store.
    """
    if entry.version > 4:
        return False
    if entry.version < 4:
        hass.config_entries.async_update_entry(
            entry,
            options=migrate_options(dict(entry.options)),
            version=4,
            minor_version=1,
        )
    return True


async def async_setup(hass, config) -> bool:
    """Set up the domain. Hubs are config entries, so there is nothing to do."""
    return True


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
    executor.max_run_min_fn = coordinator.max_run_minutes
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
