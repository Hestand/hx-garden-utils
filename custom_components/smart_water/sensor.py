"""Sensors for the hub and for each zone."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CURRENCY_DOLLAR,
    UnitOfPrecipitationDepth,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_COST_PER_1000_GAL, CONF_SIMULATION, SUBENTRY_ZONE
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity, SmartWaterZoneEntity
from .units import mm_to_inches


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create hub sensors and one set of sensors per zone."""
    coordinator = entry.runtime_data
    hub_sensors: list[SensorEntity] = [
        ModeSensor(coordinator),
        TonightPlanSensor(coordinator),
        ET0Sensor(coordinator),
        RainSensor(coordinator),
        ScheduleSensor(coordinator),
        WateringScheduleSensor(coordinator),
        WateringNowSensor(coordinator),
        WaterUseSensor(coordinator),
        WaterSavedSensor(coordinator),
    ]
    if entry.options.get(CONF_COST_PER_1000_GAL) not in (None, ""):
        hub_sensors.append(WaterCostSensor(coordinator))
    if entry.data.get(CONF_SIMULATION):
        hub_sensors.append(SimulationSensor(coordinator))
    async_add_entities(hub_sensors)
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        zone_id = subentry.subentry_id
        async_add_entities(
            [
                DeficitSensor(coordinator, zone_id),
                RawSensor(coordinator, zone_id),
                NextRunSensor(coordinator, zone_id),
                PlanReasonSensor(coordinator, zone_id),
                ZonePlanSensor(coordinator, zone_id),
                FlowSensor(coordinator, zone_id),
                MoistureSensor(coordinator, zone_id),
                LastRunSensor(coordinator, zone_id),
                DormancySensor(coordinator, zone_id),
                LearnedGpmSensor(coordinator, zone_id),
                LastRunGpmSensor(coordinator, zone_id),
                ZoneWaterUseSensor(coordinator, zone_id),
                ZoneWaterSavedSensor(coordinator, zone_id),
            ],
            config_subentry_id=zone_id,
        )


class ModeSensor(SmartWaterHubEntity, SensorEntity):
    """Hub mode: auto, notify_only, or off. Dry-run is an attribute."""

    _attr_translation_key = "mode"
    _attr_icon = "mdi:tune"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_mode"

    @property
    def native_value(self) -> str | None:
        """Return the configured mode."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.mode

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the execution guard next to the mode."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "automatic": data.automatic,
            "would_execute": data.would_execute,
            "block_reason": data.block_reason,
            "last_error": data.last_error,
        }


class TonightPlanSensor(SmartWaterHubEntity, SensorEntity):
    """Short status for tonight, with the full plan in attributes."""

    _attr_translation_key = "tonight_plan"
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_tonight_plan"

    @property
    def native_value(self) -> str | None:
        """Return a short dry-run status."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.summary_short

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return the full plan, including whether automatic watering would run it."""
        data = self.coordinator.data
        if data is None or data.plan is None:
            return {"would_execute": False}
        plan = data.plan
        return {
            "summary": plan.summary,
            "warning": plan.warning,
            "automatic": plan.automatic,
            "would_execute": plan.would_execute,
            "block_reason": plan.block_reason,
            "finish_by": plan.finish_by.isoformat(),
            "timeline": plan.to_dict()["timeline"],
            "zones": plan.to_dict()["zones"],
        }


class ET0Sensor(SmartWaterHubEntity, SensorEntity):
    """Today's reference evapotranspiration."""

    _attr_translation_key = "et0"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_et0"

    @property
    def native_value(self) -> float | None:
        """Return ET0 in millimeters."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.et0_mm

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Show whether Penman-Monteith or Hargreaves was used."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "method": data.et0_method,
            "detail": data.et0_detail,
            "date": data.et0_date,
            "elevation_m": data.elevation_m,
            "latitude": data.latitude,
        }


class _ZoneSensor(SmartWaterZoneEntity, SensorEntity):
    """Base for per-zone sensors."""

    def __init__(self, coordinator, zone_id: str, key: str) -> None:
        """Set the unique id from the zone and the sensor key."""
        super().__init__(coordinator, zone_id)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{zone_id}_{key}"


class DeficitSensor(_ZoneSensor):
    """Root-zone depletion Dr."""

    _attr_translation_key = "deficit"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-minus"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the deficit sensor."""
        super().__init__(coordinator, zone_id, "deficit")

    @property
    def native_value(self) -> float | None:
        """Return the deficit in millimeters."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.deficit_mm

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Include TAW and the inputs that set the bucket size."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "deficit_in": round(mm_to_inches(zone.deficit_mm), 3),
            "taw_mm": round(zone.taw_mm, 2),
            "taw_in": round(mm_to_inches(zone.taw_mm), 3),
            "raw_mm": round(zone.raw_mm, 2),
            "kc": zone.kc,
            "p": zone.p,
            "etc_mm": None if zone.etc_mm is None else round(zone.etc_mm, 2),
            "soil_type": zone.soil_type,
            "plant_type": zone.plant_type,
            "precipitation_rate_in_hr": zone.precipitation_rate_in_hr,
            "valve_entity": zone.valve_entity,
            "enabled": zone.enabled,
        }


class RawSensor(_ZoneSensor):
    """Readily available water, the irrigation threshold."""

    _attr_translation_key = "raw"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the RAW sensor."""
        super().__init__(coordinator, zone_id, "raw")

    @property
    def native_value(self) -> float | None:
        """Return RAW in millimeters."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.raw_mm

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Show the depletion fraction and TAW used for RAW."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "p": zone.p,
            "taw_mm": round(zone.taw_mm, 2),
            "raw_in": round(mm_to_inches(zone.raw_mm), 3),
        }


class NextRunSensor(_ZoneSensor):
    """Start of the next planned cycle. Empty when the zone is not scheduled."""

    _attr_translation_key = "next_run"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the next-run sensor."""
        super().__init__(coordinator, zone_id, "next_run")

    @property
    def native_value(self):
        """Return the next cycle start, or none."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.next_run

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Cycle lengths for a later generic entity run. Nothing is turned on."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "scheduled": zone.scheduled,
            "runtime_min": zone.runtime_min,
            "cycles_min": list(zone.cycles),
            "soak_min": zone.soak_min,
            "max_cycle_min": zone.max_cycle_min,
        }


class PlanReasonSensor(_ZoneSensor):
    """Why the zone was scheduled or left out."""

    _attr_translation_key = "plan_reason"
    _attr_icon = "mdi:comment-text-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the reason sensor."""
        super().__init__(coordinator, zone_id, "plan_reason")

    @property
    def native_value(self) -> str | None:
        """Return the latest reason."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.reason


class RainSensor(SmartWaterHubEntity, SensorEntity):
    """Today's rain, with the FAO effective-rain decision in attributes."""

    _attr_translation_key = "rain_today"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_rain_today"

    @property
    def native_value(self) -> float | None:
        """Return accumulated rain in millimeters."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.rain_today_mm

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Effective rain is what the bucket is allowed to use."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "effective_mm": data.effective_rain_mm,
            "ignored": data.rain_ignored,
            "source": data.precip_source,
            "solar_mj": data.solar_mj,
        }


class ScheduleSensor(SmartWaterHubEntity, SensorEntity):
    """Next planned start across zones, plus the watering-day rules."""

    _attr_translation_key = "schedule"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_schedule"

    @property
    def native_value(self):
        """Return the earliest cycle start, if any zone is scheduled."""
        data = self.coordinator.data
        if data is None or data.plan is None or not data.plan.timeline:
            return None
        return data.plan.timeline[0].start

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Show the allowed days and the blackout that shaped the window."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "source": data.schedule_source,
            "allowed_weekdays": list(data.allowed_weekdays or []),
            "blackout_start": data.blackout_start,
            "blackout_end": data.blackout_end,
            "round_minutes": data.round_minutes,
        }


class ZonePlanSensor(_ZoneSensor):
    """Per-zone plan: scheduled or the reason it was left out."""

    _attr_translation_key = "zone_plan"
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the zone plan sensor."""
        super().__init__(coordinator, zone_id, "zone_plan")

    @property
    def native_value(self) -> str | None:
        """Return scheduled or idle."""
        zone = self._zone()
        if zone is None:
            return None
        return "scheduled" if zone.scheduled else "idle"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Runtime, cycles, adjustment, and the stored on/off entity."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "reason": zone.reason,
            "runtime_min": zone.runtime_min,
            "cycles_min": list(zone.cycles),
            "soak_min": zone.soak_min,
            "adjustment_pct": zone.adjustment_pct,
            "sprinkler_type": zone.sprinkler_type,
            "valve_entity": zone.valve_entity,
            "last_run_now": zone.last_run_now,
        }


class FlowSensor(_ZoneSensor):
    """Delivered volume versus the plan. Status only; nothing is closed."""

    _attr_translation_key = "flow"
    _attr_icon = "mdi:water-pump"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the flow sensor."""
        super().__init__(coordinator, zone_id, "flow")

    @property
    def native_value(self) -> str | None:
        """Return pending, ok, low_flow, leak, no_data, or not_configured."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.flow_status

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Gallons observed and gallons the plan expected."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "delivered_gal": round(zone.flow_delivered_gal, 2),
            "expected_gal": zone.flow_expected_gal,
        }


class MoistureSensor(_ZoneSensor):
    """Sensor-derived deficit. The bucket uses it only in correct or override mode."""

    _attr_translation_key = "moisture"
    _attr_device_class = SensorDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the moisture sensor."""
        super().__init__(coordinator, zone_id, "moisture")

    @property
    def native_value(self) -> float | None:
        """Return the deficit implied by the moisture sensor."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.moisture_deficit_mm

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Show whether the reading corrects or replaces the bucket."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "mode": zone.moisture_mode,
            "learn_factor": round(zone.learn_factor, 3),
            "learn_confidence": round(zone.learn_confidence, 2),
        }


class WateringScheduleSensor(SmartWaterHubEntity, SensorEntity):
    """The next seven days of planned watering."""

    _attr_translation_key = "watering_schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_watering_schedule"

    @property
    def native_value(self) -> str | None:
        """Return how many waterings are planned and when the next one is."""
        data = self.coordinator.data
        if data is None or not data.schedule_days:
            return "No watering in the next 7 days"
        planned = [
            (day["date"], zone)
            for day in data.schedule_days
            for zone in day.get("zones", [])
            if zone.get("scheduled")
        ]
        if not planned:
            return "No watering in the next 7 days"
        day, zone = planned[0]
        return f"{len(planned)} waterings · next {day} {zone['name']}"[:255]

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Days, skip reasons, and a markdown table for a Lovelace card."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "days": data.schedule_days or [],
            "markdown": data.schedule_markdown,
            "note": (
                "Later days repeat today's crop ET and assume no rain."
            ),
        }


class WateringNowSensor(SmartWaterHubEntity, SensorEntity):
    """The zone currently on, or Idle."""

    _attr_translation_key = "watering_now"
    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_watering_now"

    @property
    def native_value(self) -> str:
        """Return the running zone name."""
        executor = self.coordinator.executor
        if executor is not None and executor.current_name:
            return executor.current_name
        data = self.coordinator.data
        if data is None:
            return "Idle"
        return data.watering_now or "Idle"


class LastRunSensor(_ZoneSensor):
    """What the last cycle of this zone actually did."""

    _attr_translation_key = "last_run"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the last-run sensor."""
        super().__init__(coordinator, zone_id, "last_run")

    @property
    def native_value(self) -> str:
        """Return the result, or none when the zone has not run."""
        zone = self._zone()
        if zone is None or not zone.last_run:
            return "none"
        return str(zone.last_run.get("result") or "none")

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """When, how long, and how much."""
        zone = self._zone()
        if zone is None or not zone.last_run:
            return {}
        run = zone.last_run
        return {
            "at": run.get("at"),
            "minutes": run.get("minutes"),
            "net_mm": run.get("net_mm"),
            "gallons": run.get("gallons"),
            "gpm": run.get("gpm"),
            "result": run.get("result"),
        }


class DormancySensor(_ZoneSensor):
    """Active, slow, or dormant, from the recent air-temperature mean."""

    _attr_translation_key = "dormancy"
    _attr_icon = "mdi:snowflake-thermometer"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the dormancy sensor."""
        super().__init__(coordinator, zone_id, "dormancy")

    @property
    def native_value(self) -> str | None:
        """Return active, slow, or dormant."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.dormancy

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """The rolling mean behind the status."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "mean_f": zone.dormancy_mean_f,
            "detail": zone.dormancy_detail,
        }


class LearnedGpmSensor(_ZoneSensor):
    """Median gallons per minute learned from finished runs."""

    _attr_translation_key = "learned_gpm"
    _attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.GALLONS_PER_MINUTE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the learned-GPM sensor."""
        super().__init__(coordinator, zone_id, "learned_gpm")

    @property
    def native_value(self) -> float | None:
        """Return the learned rate, or none until enough runs exist."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.learned_gpm


class LastRunGpmSensor(_ZoneSensor):
    """Gallons per minute measured on the last finished cycle."""

    _attr_translation_key = "last_run_gpm"
    _attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.GALLONS_PER_MINUTE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the last-run GPM sensor."""
        super().__init__(coordinator, zone_id, "last_run_gpm")

    @property
    def native_value(self) -> float | None:
        """Return the last measured rate."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.last_run_gpm


class ZoneWaterUseSensor(_ZoneSensor):
    """Lifetime gallons for one zone. Period totals are attributes."""

    _attr_translation_key = "water_use"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the zone water-use sensor."""
        super().__init__(coordinator, zone_id, "water_use")

    @property
    def native_value(self) -> float:
        """Return lifetime gallons. This value does not reset."""
        zone = self._zone()
        if zone is None:
            return 0.0
        return zone.water_total_gal

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Today, this week, and this month, summed from the date log."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "today_gal": zone.water_today_gal,
            "week_gal": zone.water_week_gal,
            "month_gal": zone.water_month_gal,
        }


class ZoneWaterSavedSensor(_ZoneSensor):
    """This week's gallons versus a fixed timer. Can be negative."""

    _attr_translation_key = "water_saved"
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the zone savings sensor."""
        super().__init__(coordinator, zone_id, "water_saved")

    @property
    def native_value(self) -> float | None:
        """Return baseline minus actual for the last seven days."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.saved_week_gal

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """The fixed-timer gallons this comparison uses."""
        zone = self._zone()
        if zone is None:
            return {}
        return {"baseline_week_gal": zone.baseline_week_gal}


class WaterUseSensor(SmartWaterHubEntity, SensorEntity):
    """Lifetime gallons for the hub, for the Home Assistant water dashboard."""

    _attr_translation_key = "water_use"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_water_use"

    @property
    def native_value(self) -> float:
        """Return the sum of zone lifetime gallons."""
        return _hub_gallons(self.coordinator, "water_total_gal")

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Period sums. These reset and are not the long-term statistic."""
        return {
            "today_gal": _hub_gallons(self.coordinator, "water_today_gal"),
            "week_gal": _hub_gallons(self.coordinator, "water_week_gal"),
            "month_gal": _hub_gallons(self.coordinator, "water_month_gal"),
        }


class WaterSavedSensor(SmartWaterHubEntity, SensorEntity):
    """Hub gallons saved this week against each zone's fixed-timer baseline."""

    _attr_translation_key = "water_saved"
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_water_saved"

    @property
    def native_value(self) -> float | None:
        """Return the sum of zone savings, or none when no zone has a volume."""
        data = self.coordinator.data
        if data is None:
            return None
        values = [
            zone.saved_week_gal
            for zone in data.zones.values()
            if zone.saved_week_gal is not None
        ]
        if not values:
            return None
        return round(sum(values), 3)


class WaterCostSensor(SmartWaterHubEntity, SensorEntity):
    """Lifetime water cost. Created only when a price per 1,000 gallons is set."""

    _attr_translation_key = "water_cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:currency-usd"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_water_cost"

    @property
    def native_value(self) -> float | None:
        """Return dollars for the hub's lifetime gallons."""
        return self.coordinator.lifetime_cost()


def _hub_gallons(coordinator, field: str) -> float:
    data = coordinator.data
    if data is None:
        return 0.0
    return round(sum(getattr(zone, field) for zone in data.zones.values()), 3)


class SimulationSensor(SmartWaterHubEntity, SensorEntity):
    """The last simulated week. Only created for a simulation hub."""

    _attr_translation_key = "simulation"
    _attr_icon = "mdi:calendar-week"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_simulation"

    @property
    def native_value(self) -> str:
        """Return the scenario and the week's total runtime."""
        data = self.coordinator.data
        simulation = None if data is None else data.simulation
        if not simulation:
            return "Not run"
        name = simulation.get("scenario_name") or "Simulation"
        total = float(simulation.get("total_runtime_min") or 0)
        return f"{name} · {total:.0f} min"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the day-by-day result and the markdown table."""
        data = self.coordinator.data
        simulation = None if data is None else data.simulation
        if not simulation:
            return {"would_execute": False}
        return {
            "scenario": simulation.get("scenario"),
            "scenario_name": simulation.get("scenario_name"),
            "bucket": simulation.get("bucket"),
            "start_date": simulation.get("start_date"),
            "would_execute": simulation.get("would_execute", False),
            "note": simulation.get("note"),
            "total_runtime_min": simulation.get("total_runtime_min"),
            "summary": simulation.get("summary"),
            "days": simulation.get("days"),
            "markdown": simulation.get("markdown"),
        }
