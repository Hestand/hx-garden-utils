"""Hub select for how much Water next chance applies."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NEXT_CHANCE_FILL_LABEL, NEXT_CHANCE_REFILL_LABEL, next_chance_label
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the amount select. It does not open a valve."""
    _ = hass
    async_add_entities([WaterNextChanceAmountSelect(entry.runtime_data)])


class WaterNextChanceAmountSelect(SmartWaterHubEntity, SelectEntity):
    """Refill the estimate, or fill the whole root zone."""

    _attr_translation_key = "water_next_chance_amount"
    _attr_icon = "mdi:water-plus"
    _attr_options = [NEXT_CHANCE_REFILL_LABEL, NEXT_CHANCE_FILL_LABEL]

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_water_next_chance_amount"
        )

    @property
    def current_option(self) -> str | None:
        """Return the amount the button will arm."""
        amount = self.coordinator.store.next_chance_amount
        label = next_chance_label(amount)
        if label == "off":
            return NEXT_CHANCE_REFILL_LABEL
        return label

    async def async_select_option(self, option: str) -> None:
        """Store the amount. Arming still takes the button or the service."""
        await self.coordinator.async_set_next_chance_amount(option)
