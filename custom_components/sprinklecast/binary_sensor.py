"""Binary sensors. Flow problem is on only when a saved baseline says so."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_FLOW_HIGH_PCT,
    CONF_FLOW_LOW_PCT,
    CONF_FLOW_SENSOR,
    DOMAIN,
    SUBENTRY_ZONE,
)
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterZoneEntity
from .flow_learn import DEFAULT_HIGH_PCT, DEFAULT_LOW_PCT, flow_problem

_ATTRIBUTE_KEYS = (
    "last_run_gpm",
    "baseline_gpm",
    "percent_difference",
    "reason",
    "high_pct",
    "low_pct",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """One Flow problem sensor per zone when the hub has a flow meter."""
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        zone_id = subentry.subentry_id
        unique_id = f"{entry.entry_id}_{zone_id}_flow_problem"
        if not entry.options.get(CONF_FLOW_SENSOR):
            entity_id = registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id)
            if entity_id is not None:
                registry.async_remove(entity_id)
            continue
        async_add_entities(
            [FlowProblemBinarySensor(coordinator, zone_id)],
            config_subentry_id=zone_id,
        )


class FlowProblemBinarySensor(SmartWaterZoneEntity, RestoreEntity, BinarySensorEntity):
    """Off is normal. On means the last run or the trend is outside the baseline.

    The store is the source of truth once the coordinator has a snapshot, so a
    restart does not fall back to "no data". The restored state is used only
    when that snapshot is missing.
    """

    _attr_translation_key = "flow_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the sensor for one zone."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{zone_id}_flow_problem"
        )
        self._restored_on = False
        self._restored_attrs: dict[str, Any] = {"reason": "No baseline yet"}

    async def async_added_to_hass(self) -> None:
        """Keep the last on/off result until the coordinator has a snapshot."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is None or last.state not in {"on", "off"}:
            return
        self._restored_on = last.state == "on"
        self._restored_attrs = {
            key: last.attributes[key]
            for key in _ATTRIBUTE_KEYS
            if key in last.attributes
        }

    @property
    def is_on(self) -> bool:
        """True when the saved baseline says this zone's flow is abnormal."""
        zone = self._zone()
        if zone is None:
            return self._restored_on
        problem, _reason, _gap = self._reading(zone)
        return problem

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Last run, baseline, the percent gap, the reason, and the band."""
        zone = self._zone()
        if zone is None:
            return dict(self._restored_attrs)
        _problem, reason, gap = self._reading(zone)
        high, low = self._band()
        return {
            "last_run_gpm": zone.last_run_gpm,
            "baseline_gpm": zone.baseline_gpm,
            "percent_difference": gap,
            "reason": reason,
            "high_pct": high,
            "low_pct": low,
        }

    def _band(self) -> tuple[float, float]:
        options = self.coordinator.config_entry.options
        try:
            high = float(options.get(CONF_FLOW_HIGH_PCT, DEFAULT_HIGH_PCT))
        except (TypeError, ValueError):
            high = DEFAULT_HIGH_PCT
        try:
            low = float(options.get(CONF_FLOW_LOW_PCT, DEFAULT_LOW_PCT))
        except (TypeError, ValueError):
            low = DEFAULT_LOW_PCT
        return high, low

    def _reading(self, zone) -> tuple[bool, str, float | None]:
        high, low = self._band()
        return flow_problem(
            baseline_gpm=zone.baseline_gpm,
            last_run_gpm=zone.last_run_gpm,
            trend=zone.flow_trend_status,
            high_pct=high,
            low_pct=low,
        )
