"""Switches. Turning these on never clears dry-run and never opens a valve."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUBENTRY_ZONE
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity, SmartWaterZoneEntity
from .safety import mode_after_master_switch


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the master switch and one enabled switch per zone."""
    coordinator = entry.runtime_data
    async_add_entities([MasterAutoSwitch(coordinator)])
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        async_add_entities(
            [ZoneEnabledSwitch(coordinator, subentry.subentry_id)],
            config_subentry_id=subentry.subentry_id,
        )


class MasterAutoSwitch(SmartWaterHubEntity, SwitchEntity):
    """On when the hub mode is not off.

    Off forces mode off. On restores notify-only while dry-run is set, and
    never writes dry_run to false. In v0.1 the on position still does not water.
    """

    _attr_translation_key = "master_auto"
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_master_auto"

    @property
    def is_on(self) -> bool | None:
        """Return true when the mode is auto or notify-only."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.mode != "off"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Repeat the guard so the on state cannot be read as permission to water."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "mode": data.mode,
            "dry_run": data.dry_run,
            "would_execute": False,
            "block_reason": data.block_reason,
        }

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable the hub without leaving dry-run."""
        data = self.coordinator.data
        if data is None:
            return
        mode = mode_after_master_switch(
            mode=data.mode, dry_run=data.dry_run, turn_on=True
        )
        await self.coordinator.async_set_mode(mode)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Set the hub mode to off. The bucket keeps updating."""
        await self.coordinator.async_set_mode("off")


class ZoneEnabledSwitch(SmartWaterZoneEntity, SwitchEntity):
    """Include or exclude a zone from the plan. This does not move a valve."""

    _attr_translation_key = "zone_enabled"
    _attr_icon = "mdi:water"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Set the unique id."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{zone_id}_enabled"
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the zone is included in plans."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.enabled

    async def async_turn_on(self, **kwargs: object) -> None:
        """Include the zone in the next plan."""
        await self.coordinator.async_set_zone_enabled(self._zone_id, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Leave the zone out of the plan until it is enabled again."""
        await self.coordinator.async_set_zone_enabled(self._zone_id, False)
