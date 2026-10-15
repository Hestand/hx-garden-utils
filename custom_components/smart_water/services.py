"""Services that change the plan or the bucket. None of them open a valve."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .balance import clamp_deficit, root_zone
from .const import (
    CONF_AWC_OVERRIDE,
    CONF_DEPLETION,
    CONF_KC_OVERRIDE,
    CONF_PLANT_TYPE,
    CONF_ROOT_DEPTH_IN,
    CONF_SOIL_TYPE,
    CONF_SUN_EXPOSURE,
    DOMAIN,
    SERVICE_CALCULATE_PLAN,
    SERVICE_MARK_WATERED,
    SERVICE_PAUSE_ZONE,
    SERVICE_RESET_BUCKET,
    SERVICE_RUN_NOW,
    SERVICE_SET_ADJUSTMENT,
    SERVICE_SET_BUCKET,
    SERVICE_SKIP_ZONE,
    SERVICES,
)
from .coordinator import SmartWaterCoordinator
from .presets import resolved_root_depth_in
from .units import inches_to_mm

_LOGGER = logging.getLogger(__name__)


def _coordinators(hass: HomeAssistant) -> list[tuple[Any, SmartWaterCoordinator]]:
    found = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is None or entry.state is not ConfigEntryState.LOADED:
            continue
        found.append((entry, runtime))
    return found


def _hub_matches(entry: Any, hub: str | None) -> bool:
    if not hub:
        return True
    return hub.casefold() in {entry.title.casefold(), entry.entry_id.casefold()}


def _find_zone(
    hass: HomeAssistant, zone_name: str, hub: str | None
) -> tuple[Any, SmartWaterCoordinator, str]:
    matches = []
    for entry, coordinator in _coordinators(hass):
        if not _hub_matches(entry, hub):
            continue
        for subentry in entry.subentries.values():
            if zone_name.casefold() in {
                subentry.title.casefold(),
                subentry.subentry_id.casefold(),
            }:
                matches.append((entry, coordinator, subentry.subentry_id))
    if not matches:
        raise ServiceValidationError(f"No Smart Water zone named {zone_name!r}.")
    if len(matches) > 1:
        raise ServiceValidationError(
            f"More than one zone is named {zone_name!r}. Pass the hub name too."
        )
    return matches[0]


def _depth_mm(data: dict[str, Any], required: bool) -> float | None:
    if data.get("depth_mm") is not None:
        return float(data["depth_mm"])
    if data.get("depth_in") is not None:
        return inches_to_mm(float(data["depth_in"]))
    if data.get("deficit_mm") is not None:
        return float(data["deficit_mm"])
    if data.get("deficit_in") is not None:
        return inches_to_mm(float(data["deficit_in"]))
    if required:
        raise ServiceValidationError("Provide a depth in millimeters or inches.")
    return None


def _taw(entry_data: dict[str, Any]) -> float:
    limits = root_zone(
        soil_type=entry_data[CONF_SOIL_TYPE],
        plant_type=entry_data[CONF_PLANT_TYPE],
        sun_exposure=entry_data[CONF_SUN_EXPOSURE],
        root_depth_in=resolved_root_depth_in(entry_data),
        p_table=entry_data.get(CONF_DEPLETION),
        kc_override=entry_data.get(CONF_KC_OVERRIDE),
        awc_override=entry_data.get(CONF_AWC_OVERRIDE),
        et0_mm=None,
    )
    return limits.taw_mm


def async_setup_services(hass: HomeAssistant) -> None:
    """Register services once, the first time a hub is set up."""
    if hass.services.has_service(DOMAIN, SERVICE_CALCULATE_PLAN):
        return

    async def calculate_plan(call: ServiceCall) -> None:
        """Rebuild the dry-run plan. This does not water."""
        notify = bool(call.data.get("notify", True))
        hub = call.data.get("hub")
        targets = [
            coordinator
            for entry, coordinator in _coordinators(hass)
            if _hub_matches(entry, hub)
        ]
        if not targets:
            raise ServiceValidationError("No Smart Water hub is loaded.")
        for coordinator in targets:
            await coordinator.async_calculate_plan(notify=notify)

    async def reset_bucket(call: ServiceCall) -> None:
        """Return a zone to field capacity (deficit 0)."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        await coordinator.async_reset_bucket(zone_id)

    async def set_bucket(call: ServiceCall) -> None:
        """Set the deficit. Values above TAW are clamped."""
        entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        deficit = _depth_mm(call.data, required=True)
        assert deficit is not None
        taw = _taw(dict(entry.subentries[zone_id].data))
        await coordinator.async_set_bucket(zone_id, clamp_deficit(deficit, taw))

    async def mark_watered(call: ServiceCall) -> None:
        """Credit net irrigation. Omit the depth to refill the bucket."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        await coordinator.async_mark_watered(zone_id, _depth_mm(call.data, required=False))

    async def skip_zone(call: ServiceCall) -> None:
        """Skip a zone through a date. The default is the next local morning."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        until = call.data.get("until")
        if not until:
            until = (dt_util.now().date() + timedelta(days=1)).isoformat()
        await coordinator.async_skip_zone(zone_id, str(until))

    async def pause_zone(call: ServiceCall) -> None:
        """Skip a zone for N local days. Zero clears the pause."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        await coordinator.async_pause_zone(zone_id, int(call.data["days"]))

    async def set_adjustment(call: ServiceCall) -> None:
        """Scale the planned depth. This does not water."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        await coordinator.async_set_adjustment(zone_id, float(call.data["percent"]))

    async def run_now(call: ServiceCall) -> None:
        """Log the planned run. No valve, switch, or controller service is called."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        await coordinator.async_run_now(zone_id)

    number = vol.All(vol.Coerce(float), vol.Range(min=0, max=500))
    days = vol.All(vol.Coerce(int), vol.Range(min=0, max=365))
    percent = vol.All(vol.Coerce(float), vol.Range(min=0, max=300))
    hass.services.async_register(
        DOMAIN,
        SERVICE_CALCULATE_PLAN,
        calculate_plan,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Optional("notify", default=True): bool,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_BUCKET,
        reset_bucket,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BUCKET,
        set_bucket,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Optional("deficit_mm"): number,
                vol.Optional("deficit_in"): number,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_WATERED,
        mark_watered,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Optional("depth_mm"): number,
                vol.Optional("depth_in"): number,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SKIP_ZONE,
        skip_zone,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Optional("until"): str,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE_ZONE,
        pause_zone,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Required("days"): days,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ADJUSTMENT,
        set_adjustment,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Required("percent"): percent,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RUN_NOW,
        run_now,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
            }
        ),
    )
    _LOGGER.debug("Registered Smart Water services")


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when the last hub unloads."""
    for service in SERVICES:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
