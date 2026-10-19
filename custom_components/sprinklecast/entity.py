"""Shared entity base classes."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, VERSION
from .coordinator import SmartWaterCoordinator


class SmartWaterHubEntity(CoordinatorEntity[SmartWaterCoordinator]):
    """Entity attached to the hub device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartWaterCoordinator) -> None:
        """Bind the hub device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Sprinklecast",
            model="Water-balance planner",
            sw_version=VERSION,
        )


class SmartWaterZoneEntity(CoordinatorEntity[SmartWaterCoordinator]):
    """Entity attached to one zone device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SmartWaterCoordinator, zone_id: str) -> None:
        """Bind the zone device."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        subentry = entry.subentries[zone_id]
        self._zone_id = zone_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{zone_id}")},
            name=subentry.title,
            manufacturer="Sprinklecast",
            model="Zone",
            via_device=(DOMAIN, entry.entry_id),
        )

    def _zone(self):
        """Return the latest zone snapshot, if the coordinator has one."""
        data = self.coordinator.data
        if data is None:
            return None
        return data.zones.get(self._zone_id)
