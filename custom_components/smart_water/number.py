"""Per-zone adjustment. Changing it only scales the next plan."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUBENTRY_ZONE
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one adjustment number per zone."""
    coordinator = entry.runtime_data
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        async_add_entities(
            [AdjustmentNumber(coordinator, subentry.subentry_id)],
            config_subentry_id=subentry.subentry_id,
        )


class AdjustmentNumber(SmartWaterZoneEntity, NumberEntity):
    """Percent of the calculated depth to plan. 100 leaves it unchanged."""

    _attr_translation_key = "adjustment"
    _attr_native_min_value = 0
    _attr_native_max_value = 300
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:percent"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Set the unique id."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{zone_id}_adjustment"
        )

    @property
    def native_value(self) -> float | None:
        """Return the stored adjustment percent."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.adjustment_pct

    async def async_set_native_value(self, value: float) -> None:
        """Store the percent. The next plan uses it. Nothing is turned on."""
        await self.coordinator.async_set_adjustment(self._zone_id, value)
