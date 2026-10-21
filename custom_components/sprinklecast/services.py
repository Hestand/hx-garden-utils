"""Services that change the plan, the bucket, or a running cycle.

``run_now`` opens the zone's on/off entity. ``stop_all`` turns it off.
Nothing in this file calls Hydrawise.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import UnitOfPrecipitationDepth
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
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
    LEGACY_DOMAIN,
    SERVICE_CALCULATE_PLAN,
    SERVICE_MARK_WATERED,
    SERVICE_PAUSE_ZONE,
    SERVICE_RESET_BUCKET,
    SERVICE_RUN_NOW,
    SERVICE_SET_ADJUSTMENT,
    SERVICE_SET_BUCKET,
    SERVICE_SET_SOIL_WATER,
    SUBENTRY_ZONE,
    SERVICE_RESET_FLOW,
    SERVICE_RESET_LEARNING,
    SERVICE_SIMULATE,
    SERVICE_SKIP_ZONE,
    SERVICE_LEARN_FLOW,
    SERVICE_RUN_CATCH_CUP,
    SERVICE_SET_CATCH_CUP,
    SERVICE_SET_FLOW_BASELINE,
    SERVICE_START_AUDIT,
    SERVICE_STOP_ALL,
    SERVICE_SUBMIT_AUDIT,
    SERVICES,
)
from .simulate import BUCKETS, SCENARIOS
from .coordinator import SmartWaterCoordinator
from .presets import resolved_root_depth_in
from .units import depth_to_inches, inches_to_mm

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
        raise ServiceValidationError(f"No Sprinklecast zone named {zone_name!r}.")
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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _zones_for_call(
    hass: HomeAssistant, data: dict[str, Any]
) -> list[tuple[Any, SmartWaterCoordinator, str]]:
    """Resolve zone names, zone entities, or every zone on one hub."""
    hub = data.get("hub")
    found: list[tuple[Any, SmartWaterCoordinator, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(entry: Any, coordinator: SmartWaterCoordinator, zone_id: str) -> None:
        key = (entry.entry_id, zone_id)
        if key in seen:
            return
        seen.add(key)
        found.append((entry, coordinator, zone_id))

    for name in _as_list(data.get("zone")):
        entry, coordinator, zone_id = _find_zone(hass, name, hub)
        _add(entry, coordinator, zone_id)
    entity_ids = _as_list(data.get("entity_id"))
    if entity_ids:
        registry = er.async_get(hass)
        for entity_id in entity_ids:
            entity = registry.async_get(entity_id)
            if entity is None or entity.platform not in (DOMAIN, LEGACY_DOMAIN):
                raise ServiceValidationError(f"{entity_id} is not a Sprinklecast entity.")
            if not entity.config_subentry_id:
                raise ServiceValidationError(
                    f"{entity_id} is a hub entity. Pick a zone, or leave the zone empty to set every zone."
                )
            match = next(
                (
                    (entry, coordinator)
                    for entry, coordinator in _coordinators(hass)
                    if entry.entry_id == entity.config_entry_id
                ),
                None,
            )
            if match is None:
                raise ServiceValidationError(f"{entity_id} belongs to a hub that is not loaded.")
            if hub and not _hub_matches(match[0], hub):
                raise ServiceValidationError(
                    f"{entity_id} is not on the hub named {hub!r}."
                )
            _add(match[0], match[1], entity.config_subentry_id)
    if found:
        return found
    hubs = [
        (entry, coordinator)
        for entry, coordinator in _coordinators(hass)
        if _hub_matches(entry, hub)
    ]
    if not hubs:
        raise ServiceValidationError("No Sprinklecast hub is loaded.")
    if len(hubs) > 1:
        raise ServiceValidationError(
            "More than one Sprinklecast hub is loaded. Pass the hub name or a zone."
        )
    entry, coordinator = hubs[0]
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_ZONE:
            _add(entry, coordinator, subentry.subentry_id)
    if not found:
        raise ServiceValidationError("This hub has no zones.")
    return found


def _soil_deficit_mm(hass: HomeAssistant, data: dict[str, Any]) -> tuple[float | None, float | None]:
    """Return ``(percent, deficit_mm)``. Exactly one of the two is set."""
    percent = data.get("percent")
    kinds = [
        name
        for name in ("deficit_mm", "deficit_in", "deficit")
        if data.get(name) is not None
    ]
    if percent is not None and kinds:
        raise ServiceValidationError(
            "Provide a percent or a deficit, not both."
        )
    if percent is None and len(kinds) != 1:
        raise ServiceValidationError(
            "Provide a percent from 0 to 100, or the water the soil still needs."
        )
    if percent is not None:
        return float(percent), None
    if "deficit_mm" in kinds:
        return None, float(data["deficit_mm"])
    if "deficit_in" in kinds:
        return None, inches_to_mm(float(data["deficit_in"]))
    value = float(data["deficit"])
    unit = hass.config.units.accumulated_precipitation_unit
    if unit == UnitOfPrecipitationDepth.INCHES:
        return None, inches_to_mm(value)
    if unit == UnitOfPrecipitationDepth.CENTIMETERS:
        return None, value * 10.0
    return None, value


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

    def _register(*args, **kwargs):
        """Register on sprinklecast and keep the old smart_water service name."""
        hass.services.async_register(*args, **kwargs)
        if args and args[0] == DOMAIN:
            hass.services.async_register(LEGACY_DOMAIN, *args[1:], **kwargs)

    async def calculate_plan(call: ServiceCall) -> None:
        """Rebuild the plan. An automatic hub can arm tonight's run."""
        notify = bool(call.data.get("notify", True))
        hub = call.data.get("hub")
        targets = [
            coordinator
            for entry, coordinator in _coordinators(hass)
            if _hub_matches(entry, hub)
        ]
        if not targets:
            raise ServiceValidationError("No Sprinklecast hub is loaded.")
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

    async def set_soil_water(call: ServiceCall) -> None:
        """Set how full the soil is, or the water it still needs."""
        percent, deficit = _soil_deficit_mm(hass, call.data)
        grouped: dict[SmartWaterCoordinator, list[str]] = {}
        for _entry, coordinator, zone_id in _zones_for_call(hass, call.data):
            grouped.setdefault(coordinator, []).append(zone_id)
        for coordinator, zone_ids in grouped.items():
            try:
                await coordinator.async_set_soil_water_zones(
                    zone_ids, percent=percent, deficit_mm=deficit
                )
            except HomeAssistantError as err:
                raise ServiceValidationError(str(err)) from err

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
        """Run one zone now, even when automatic watering is off."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        await coordinator.async_run_now(zone_id)

    async def stop_all(call: ServiceCall) -> None:
        """Turn off every zone this hub left on."""
        hub = call.data.get("hub")
        targets = [
            coordinator
            for entry, coordinator in _coordinators(hass)
            if _hub_matches(entry, hub)
        ]
        if not targets:
            raise ServiceValidationError("No Sprinklecast hub is loaded.")
        for coordinator in targets:
            await coordinator.async_stop_all()

    async def reset_learning(call: ServiceCall) -> None:
        """Reset a zone's learned available-water factor."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        await coordinator.async_reset_learning(zone_id)

    async def simulate(call: ServiceCall) -> dict[str, Any]:
        """Play a weather week through the planner. Does not call a valve."""
        matches = [
            (entry, coordinator)
            for entry, coordinator in _coordinators(hass)
            if _hub_matches(entry, call.data.get("hub"))
        ]
        if not matches:
            raise ServiceValidationError("No Sprinklecast hub is loaded.")
        if len(matches) > 1:
            raise ServiceValidationError(
                "More than one Sprinklecast hub is loaded. Pass the hub name."
            )
        _entry, coordinator = matches[0]
        try:
            days = _parse_days(call.data.get("days"))
        except (yaml.YAMLError, ValueError, vol.Invalid) as err:
            raise ServiceValidationError(f"Could not read days: {err}") from err
        try:
            return await coordinator.async_simulate(
                scenario=call.data.get("scenario"),
                days=days,
                bucket=call.data.get("bucket"),
                start=call.data.get("start_date"),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise ServiceValidationError(str(err)) from err

    number = vol.All(vol.Coerce(float), vol.Range(min=0, max=500))
    days = vol.All(vol.Coerce(int), vol.Range(min=0, max=365))
    percent = vol.All(vol.Coerce(float), vol.Range(min=0, max=300))
    soil_percent = vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
    zone_names = vol.Any(str, [str])
    _register(
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
    _register(
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
    _register(
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
    _register(
        DOMAIN,
        SERVICE_SET_SOIL_WATER,
        set_soil_water,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Optional("zone"): zone_names,
                vol.Optional("entity_id"): zone_names,
                vol.Optional("percent"): soil_percent,
                vol.Optional("deficit_mm"): number,
                vol.Optional("deficit_in"): number,
                vol.Optional("deficit"): number,
            }
        ),
    )
    _register(
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
    _register(
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
    _register(
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
    _register(
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
    _register(
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
    _register(
        DOMAIN,
        SERVICE_SIMULATE,
        simulate,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Optional("scenario"): vol.In(SCENARIOS),
                vol.Optional("bucket"): vol.In(BUCKETS),
                vol.Optional("start_date"): str,
                vol.Optional("days"): vol.Any(str, list),
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        DOMAIN,
        SERVICE_STOP_ALL,
        stop_all,
        schema=vol.Schema({vol.Optional("hub"): str}),
    )
    _register(
        DOMAIN,
        SERVICE_RESET_LEARNING,
        reset_learning,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
            }
        ),
    )

    async def reset_flow(call: ServiceCall) -> None:
        """Clear learned flow and a stop-until-reset skip. Omit the zone to clear the hub."""
        zone_name = call.data.get("zone")
        hub = call.data.get("hub")
        clear_baseline = bool(call.data.get("clear_baseline", False))
        if zone_name:
            _entry, coordinator, zone_id = _find_zone(hass, zone_name, hub)
            await coordinator.async_reset_flow(zone_id, clear_baseline=clear_baseline)
            return
        targets = [
            coordinator
            for entry, coordinator in _coordinators(hass)
            if _hub_matches(entry, hub)
        ]
        if not targets:
            raise ServiceValidationError("No Sprinklecast hub is loaded.")
        for coordinator in targets:
            await coordinator.async_reset_flow(None, clear_baseline=clear_baseline)

    _register(
        DOMAIN,
        SERVICE_RESET_FLOW,
        reset_flow,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Optional("zone"): str,
                vol.Optional("clear_baseline", default=False): bool,
            }
        ),
    )

    async def learn_flow(call: ServiceCall) -> None:
        """Run selected zones and save each peak flow from the middle of the run."""
        raw = call.data.get("minutes")
        minutes = None if raw is None else float(raw)
        hub = call.data.get("hub")
        names = _as_list(call.data.get("zone"))
        grouped: dict[Any, list[str]] = {}
        if names:
            for name in names:
                _entry, coordinator, zone_id = _find_zone(hass, name, hub)
                grouped.setdefault(coordinator, []).append(zone_id)
        else:
            targets = [
                coordinator
                for entry, coordinator in _coordinators(hass)
                if _hub_matches(entry, hub)
            ]
            if not targets:
                raise ServiceValidationError("No Sprinklecast hub is loaded.")
            if len(targets) > 1:
                raise ServiceValidationError(
                    "More than one Sprinklecast hub is loaded. Pass the hub name or a zone."
                )
            grouped[targets[0]] = []
        for coordinator, zone_ids in grouped.items():
            try:
                await coordinator.async_learn_flow_rates(zone_ids or None, minutes)
            except HomeAssistantError as err:
                raise ServiceValidationError(str(err)) from err

    async def run_catch_cup(call: ServiceCall) -> None:
        """Run selected zones one at a time for a catch-cup test."""
        minutes = float(call.data.get("minutes", 15))
        hub = call.data.get("hub")
        names = _as_list(call.data.get("zone"))
        grouped: dict[Any, list[str]] = {}
        if names:
            for name in names:
                _entry, coordinator, zone_id = _find_zone(hass, name, hub)
                grouped.setdefault(coordinator, []).append(zone_id)
        else:
            targets = [
                coordinator
                for entry, coordinator in _coordinators(hass)
                if _hub_matches(entry, hub)
            ]
            if not targets:
                raise ServiceValidationError("No Sprinklecast hub is loaded.")
            if len(targets) > 1:
                raise ServiceValidationError(
                    "More than one Sprinklecast hub is loaded. Pass the hub name or a zone."
                )
            grouped[targets[0]] = []
        for coordinator, zone_ids in grouped.items():
            try:
                await coordinator.async_run_catch_cup_test(
                    zone_ids or None, minutes
                )
            except HomeAssistantError as err:
                raise ServiceValidationError(str(err)) from err

    async def set_catch_cup(call: ServiceCall) -> dict[str, Any]:
        """Store one average cup depth as the zone's precipitation rate."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        try:
            depth_in = _catch_depth_in(hass, call.data)
        except ServiceValidationError:
            raise
        try:
            return await coordinator.async_set_catch_cup_result(
                zone_id, depth_in, call.data.get("minutes")
            )
        except HomeAssistantError as err:
            raise ServiceValidationError(str(err)) from err

    async def set_flow_baseline(call: ServiceCall) -> None:
        """Save the current or given gallons per minute as the permanent baseline."""
        gpm = call.data.get("gpm")
        grouped: dict[Any, list[str]] = {}
        for _entry, coordinator, zone_id in _zones_for_call(hass, call.data):
            grouped.setdefault(coordinator, []).append(zone_id)
        errors: list[str] = []
        for coordinator, zone_ids in grouped.items():
            for zone_id in zone_ids:
                try:
                    await coordinator.async_set_flow_baseline(
                        zone_id, None if gpm is None else float(gpm)
                    )
                except HomeAssistantError as err:
                    errors.append(str(err))
        if errors and len(errors) == sum(len(ids) for ids in grouped.values()):
            raise ServiceValidationError("; ".join(errors))

    minutes = vol.All(vol.Coerce(float), vol.Range(min=1, max=180))
    learn_minutes = vol.All(vol.Coerce(float), vol.Range(min=1, max=60))
    _register(
        DOMAIN,
        SERVICE_LEARN_FLOW,
        learn_flow,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Optional("zone"): vol.Any(str, [str]),
                vol.Optional("minutes"): learn_minutes,
            }
        ),
    )
    _register(
        DOMAIN,
        SERVICE_RUN_CATCH_CUP,
        run_catch_cup,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Optional("zone"): vol.Any(str, [str]),
                vol.Optional("minutes", default=15): minutes,
            }
        ),
    )
    _register(
        DOMAIN,
        SERVICE_SET_CATCH_CUP,
        set_catch_cup,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Optional("depth_in"): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=5)),
                vol.Optional("depth_mm"): vol.All(
                    vol.Coerce(float), vol.Range(min=0.1, max=127)
                ),
                vol.Optional("depth"): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=127)),
                vol.Optional("minutes"): minutes,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        DOMAIN,
        SERVICE_SET_FLOW_BASELINE,
        set_flow_baseline,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Optional("zone"): vol.Any(str, [str]),
                vol.Optional("entity_id"): vol.Any(str, [str]),
                vol.Optional("gpm"): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=200)),
            }
        ),
    )

    async def start_audit(call: ServiceCall) -> None:
        """Run a zone for a catch-cup test. Freeze, wind, and rain still apply."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        try:
            await coordinator.async_start_audit(zone_id, float(call.data["minutes"]))
        except HomeAssistantError as err:
            raise ServiceValidationError(str(err)) from err

    async def submit_audit(call: ServiceCall) -> dict[str, Any]:
        """Turn cup readings into a rate, DU_lq, and scheduling efficiency."""
        _entry, coordinator, zone_id = _find_zone(
            hass, call.data["zone"], call.data.get("hub")
        )
        try:
            readings = _cup_readings(call.data["readings"])
        except (TypeError, ValueError) as err:
            raise ServiceValidationError(str(err)) from err
        try:
            return await coordinator.async_submit_audit(
                zone_id,
                readings,
                unit=str(call.data.get("unit") or "in"),
                cup_diameter_in=call.data.get("cup_diameter_in"),
                minutes=call.data.get("minutes"),
            )
        except HomeAssistantError as err:
            raise ServiceValidationError(str(err)) from err

    minutes = vol.All(vol.Coerce(float), vol.Range(min=1, max=180))
    _register(
        DOMAIN,
        SERVICE_START_AUDIT,
        start_audit,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Required("minutes"): minutes,
            }
        ),
    )
    _register(
        DOMAIN,
        SERVICE_SUBMIT_AUDIT,
        submit_audit,
        schema=vol.Schema(
            {
                vol.Optional("hub"): str,
                vol.Required("zone"): str,
                vol.Required("readings"): vol.Any(str, [vol.Coerce(float)]),
                vol.Optional("unit", default="in"): vol.In(
                    ["in", "inch", "inches", "ml", "mL"]
                ),
                vol.Optional("cup_diameter_in"): vol.All(
                    vol.Coerce(float), vol.Range(min=0.5, max=12)
                ),
                vol.Optional("minutes"): minutes,
            }
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    _LOGGER.debug("Registered Sprinklecast services")


def _catch_depth_in(hass: HomeAssistant, data: dict[str, Any]) -> float:
    """One cup depth, in inches. Exactly one of the depth fields is set."""
    kinds = [
        name for name in ("depth_in", "depth_mm", "depth") if data.get(name) is not None
    ]
    if len(kinds) != 1:
        raise ServiceValidationError("Provide one depth: depth_in, depth_mm, or depth.")
    if "depth_in" in kinds:
        return float(data["depth_in"])
    if "depth_mm" in kinds:
        return float(data["depth_mm"]) / 25.4
    unit = hass.config.units.accumulated_precipitation_unit
    return depth_to_inches(float(data["depth"]), str(unit) if unit else "in")


def _cup_readings(value: Any) -> list[float]:
    """Accept a list of numbers or a comma-separated string."""
    if isinstance(value, str):
        parts = [part.strip() for part in value.replace(";", ",").split(",")]
        parts = [part for part in parts if part]
        return [float(part) for part in parts]
    if isinstance(value, list):
        return [float(part) for part in value]
    raise ValueError("Cup readings must be a list or a comma-separated string.")


def _parse_days(value: Any) -> list[dict[str, Any]] | None:
    """Accept a list or a YAML/JSON string from the service form."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        loaded = yaml.safe_load(value)
        if loaded is None:
            return None
        value = loaded
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise ValueError("days must be a list")
    days = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each day must be a mapping")
        days.append(item)
    return days


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove services when the last hub unloads."""
    for domain in (DOMAIN, LEGACY_DOMAIN):
        for service in SERVICES:
            if hass.services.has_service(domain, service):
                hass.services.async_remove(domain, service)
