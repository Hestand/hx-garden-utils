"""Switches. The master switch is automatic watering. It does not call a valve itself."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUBENTRY_ZONE
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity, SmartWaterZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the automatic-watering switch and one enabled switch per zone."""
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
    """Automatic watering for this hub. Off on a new install and after an upgrade.

    Turning it on does not by itself call a valve. The executor runs the plan
    on the next refresh when the switch is on and the mode is not off.
    Turning it off stops a run that is already going.
    """

    _attr_translation_key = "master_auto"
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_master_auto"

    @property
    def is_on(self) -> bool:
        """Return whether automatic watering is enabled."""
        return bool(self.coordinator.store.automatic)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Show the mode and whether a plan would actually run."""
        data = self.coordinator.data
        if data is None:
            return {"automatic": self.is_on}
        return {
            "mode": data.mode,
            "automatic": data.automatic,
            "would_execute": data.would_execute,
            "block_reason": data.block_reason,
        }

    async def async_turn_on(self, **kwargs: object) -> None:
        """Allow the executor to run the nightly plan."""
        await self.coordinator.async_set_automatic(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Stop automatic watering and turn off a zone that is running."""
        await self.coordinator.async_set_automatic(False)


class ZoneEnabledSwitch(SmartWaterZoneEntity, SwitchEntity):
    """Include or exclude a zone from the plan. This does not move a valve by itself."""

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
