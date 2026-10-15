"""Buttons record a plan or replay a simulated week. They do not move a valve."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SIMULATION, SUBENTRY_ZONE
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity, SmartWaterZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one run-now button per zone, and a week button on a simulation hub."""
    coordinator = entry.runtime_data
    if entry.data.get(CONF_SIMULATION):
        async_add_entities([SimulateButton(coordinator)])
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        async_add_entities(
            [RunNowButton(coordinator, subentry.subentry_id)],
            config_subentry_id=subentry.subentry_id,
        )


class SimulateButton(SmartWaterHubEntity, ButtonEntity):
    """Run the stored weather week again. The press does not call a valve."""

    _attr_translation_key = "simulate"
    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_simulate"

    async def async_press(self) -> None:
        """Replace the stored week using the hub's scenario and starting soil."""
        await self.coordinator.async_simulate()


class RunNowButton(SmartWaterZoneEntity, ButtonEntity):
    """Log the zone's planned run. The press does not call the valve entity."""

    _attr_translation_key = "run_now"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Set the unique id."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{zone_id}_run_now"

    async def async_press(self) -> None:
        """Write the planned minutes to the log and to last_run_now."""
        await self.coordinator.async_run_now(self._zone_id)
