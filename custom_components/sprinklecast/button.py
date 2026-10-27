"""Buttons. Run now and the catch-cup test open a zone. Run simulation does not."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FLOW_SENSOR, CONF_SIMULATION, DOMAIN, SUBENTRY_ZONE
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity, SmartWaterZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the catch-cup button, one run-now button per zone, and a week button."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            CatchCupTestButton(coordinator),
            WaterNextChanceButton(coordinator),
            CancelWaterNextChanceButton(coordinator),
        ]
    )
    learn_id = f"{entry.entry_id}_learn_flow"
    if entry.options.get(CONF_FLOW_SENSOR):
        async_add_entities([LearnFlowButton(coordinator)])
    else:
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id("button", DOMAIN, learn_id)
        if entity_id is not None:
            registry.async_remove(entity_id)
    if entry.data.get(CONF_SIMULATION):
        async_add_entities([SimulateButton(coordinator)])
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        async_add_entities(
            [RunNowButton(coordinator, subentry.subentry_id)],
            config_subentry_id=subentry.subentry_id,
        )


class CatchCupTestButton(SmartWaterHubEntity, ButtonEntity):
    """Run every enabled zone for 15 minutes so catch cups can be read."""

    _attr_translation_key = "catch_cup_test"
    _attr_icon = "mdi:cup-water"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_catch_cup_test"

    async def async_press(self) -> None:
        """Start the catch-cup sequence. Stop all watering cancels it."""
        await self.coordinator.async_run_catch_cup_test(None, 15)


class LearnFlowButton(SmartWaterHubEntity, ButtonEntity):
    """Run every enabled zone and save the peak flow from the middle."""

    _attr_translation_key = "learn_flow"
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_learn_flow"

    async def async_press(self) -> None:
        """Start the learn-flow sequence. Stop all watering cancels it."""
        await self.coordinator.async_learn_flow_rates(None)


class WaterNextChanceButton(SmartWaterHubEntity, ButtonEntity):
    """Arm every enabled zone for the next allowed watering morning."""

    _attr_translation_key = "water_next_chance"
    _attr_icon = "mdi:calendar-plus"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_water_next_chance"

    async def async_press(self) -> None:
        """Arm the amount selected on Water next chance amount."""
        await self.coordinator.async_arm_next_chance(None)


class CancelWaterNextChanceButton(SmartWaterHubEntity, ButtonEntity):
    """Clear an armed Water next chance run."""

    _attr_translation_key = "cancel_water_next_chance"
    _attr_icon = "mdi:calendar-remove"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_cancel_water_next_chance"
        )

    async def async_press(self) -> None:
        """Leave the next mornings on the normal plan."""
        await self.coordinator.async_cancel_next_chance()


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
