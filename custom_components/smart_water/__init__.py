"""Smart Water custom integration.

v0.1 plans irrigation and does not apply it. There is no call to
``hydrawise.start_watering``, no valve service, and no switch turn-on.
See ``safety.py`` for the guard that stays in place even if dry-run is cleared.
"""

from __future__ import annotations

from .const import DOMAIN, PLATFORMS

__all__ = ["DOMAIN"]


async def async_setup(hass, config) -> bool:
    """Set up the domain. Hubs are config entries, so there is nothing to do."""
    return True


async def async_setup_entry(hass, entry) -> bool:
    """Set up one hub from a config entry."""
    from .coordinator import SmartWaterCoordinator
    from .services import async_setup_services
    from .store import SmartWaterStore

    store = SmartWaterStore(hass, entry.entry_id)
    await store.async_load()
    coordinator = SmartWaterCoordinator(hass, entry, store)
    entry.runtime_data = coordinator
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_track_plan_time()
    # Reloads when options or zones change. Do not also use OptionsFlowWithReload
    # or async_update_reload_and_abort; those raise if a listener is registered.
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    async_setup_services(hass)
    return True


async def async_unload_entry(hass, entry) -> bool:
    """Unload a hub and drop services when it was the last one."""
    from homeassistant.config_entries import ConfigEntryState

    from .services import async_unload_services

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
