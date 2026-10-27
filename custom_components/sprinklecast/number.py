"""Per-zone numbers. Adjustment scales the plan. Catch-cup depth sets the rate."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE, UnitOfLength, UnitOfPrecipitationDepth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUBENTRY_ZONE
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterZoneEntity
from .units import depth_to_inches, inches_to_depth, inches_to_length, inches_to_mm, length_to_inches


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
            [
                AdjustmentNumber(coordinator, subentry.subentry_id),
                SoilWaterLevelNumber(coordinator, subentry.subentry_id),
                CatchCupDepthNumber(coordinator, subentry.subentry_id),
                RootDepthNumber(coordinator, subentry.subentry_id),
            ],
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


class SoilWaterLevelNumber(SmartWaterZoneEntity, NumberEntity):
    """How full the soil is. Setting it writes the bucket."""

    _attr_translation_key = "soil_water_level"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Set the unique id."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{zone_id}_soil_water_level"
        )

    @property
    def native_value(self) -> float | None:
        """Return the same percent the soil water sensor shows."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.full_pct

    async def async_set_native_value(self, value: float) -> None:
        """Write the bucket as this percent of the water the soil can hold."""
        await self.coordinator.async_set_soil_water(self._zone_id, percent=value)


class CatchCupDepthNumber(SmartWaterZoneEntity, NumberEntity):
    """Average depth caught in the cups. Setting it stores the precipitation rate."""

    _attr_translation_key = "catch_cup_depth"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:cup-water"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Set the unique id."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{zone_id}_catch_cup_depth"
        )

    @property
    def native_unit_of_measurement(self) -> str:
        """Follow Home Assistant's precipitation unit."""
        return (
            self.coordinator.hass.config.units.accumulated_precipitation_unit
            or UnitOfPrecipitationDepth.INCHES
        )

    @property
    def native_step(self) -> float:
        """Hundredths of an inch, or tenths of a millimeter."""
        if self.native_unit_of_measurement == UnitOfPrecipitationDepth.INCHES:
            return 0.01
        return 0.1

    @property
    def native_min_value(self) -> float:
        """Zero is empty. The coordinator rejects a zero that is saved."""
        return 0.0

    @property
    def native_max_value(self) -> float:
        """About five inches, in the user's unit."""
        unit = self.native_unit_of_measurement
        if unit == UnitOfPrecipitationDepth.MILLIMETERS:
            return 127.0
        if unit == UnitOfPrecipitationDepth.CENTIMETERS:
            return 12.7
        return 5.0

    @property
    def native_value(self) -> float | None:
        """Return the last entered depth, or none before a result is saved."""
        zone = self._zone()
        if zone is None or not zone.catch_cup:
            return None
        depth_in = zone.catch_cup.get("depth_in")
        if depth_in in (None, ""):
            return None
        return round(inches_to_depth(float(depth_in), self.native_unit_of_measurement), 4)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Date, minutes, and the rate computed from the depth."""
        zone = self._zone()
        if zone is None:
            return {}
        record = zone.catch_cup or {}
        pending = zone.catch_cup_pending or {}
        depth_in = record.get("depth_in")
        return {
            "tested": record.get("at"),
            "minutes": record.get("minutes", pending.get("minutes")),
            "depth_in": depth_in,
            "depth_mm": None if depth_in in (None, "") else round(inches_to_mm(float(depth_in)), 2),
            "precipitation_rate_in_hr": record.get("precipitation_rate_in_hr"),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Convert the entered depth to inches and store the precipitation rate."""
        depth_in = depth_to_inches(float(value), self.native_unit_of_measurement)
        await self.coordinator.async_set_catch_cup_result(self._zone_id, depth_in)


def _root_length_unit(hass) -> str:
    """Inches or centimeters from Home Assistant. Anything else stays inches.

    The entity always names its unit. A meter or foot setting is not read
    as inches, and it is not left unlabeled.
    """
    unit = getattr(hass.config.units, "length_unit", None)
    if unit in {UnitOfLength.CENTIMETERS, UnitOfLength.MILLIMETERS, UnitOfLength.INCHES}:
        return str(unit)
    return UnitOfLength.INCHES


class RootDepthNumber(SmartWaterZoneEntity, NumberEntity):
    """How deep the roots are. Blank in setup keeps the plant preset."""

    _attr_translation_key = "root_depth"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:shovel"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Set the unique id."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{zone_id}_root_depth"
        )

    @property
    def native_unit_of_measurement(self) -> str:
        """Inches, or centimeters when that is the length unit."""
        return _root_length_unit(self.coordinator.hass)

    @property
    def native_step(self) -> float:
        """Half an inch, or one centimeter, or ten millimeters."""
        unit = self.native_unit_of_measurement
        if unit == UnitOfLength.CENTIMETERS:
            return 1.0
        if unit == UnitOfLength.MILLIMETERS:
            return 10.0
        return 0.5

    @property
    def native_min_value(self) -> float:
        """One inch, in the entity's unit."""
        return round(inches_to_length(1.0, self.native_unit_of_measurement), 2)

    @property
    def native_max_value(self) -> float:
        """120 inches, in the entity's unit."""
        return round(inches_to_length(120.0, self.native_unit_of_measurement), 2)

    @property
    def native_value(self) -> float | None:
        """The depth in use, including the plant preset when nothing is set."""
        zone = self._zone()
        if zone is None or zone.root_depth_in is None:
            return None
        return round(
            inches_to_length(zone.root_depth_in, self.native_unit_of_measurement),
            2,
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Where the depth came from, and how much water the bucket holds."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "source": zone.root_depth_source,
            "root_depth_in": zone.root_depth_in,
            "bucket_in": zone.bucket_in,
        }

    async def async_set_native_value(self, value: float) -> None:
        """Convert the entity's unit to inches and resize the bucket."""
        inches = length_to_inches(float(value), self.native_unit_of_measurement)
        await self.coordinator.async_set_root_depth(self._zone_id, inches)
