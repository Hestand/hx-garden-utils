"""Sensors for the hub and for each zone."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CURRENCY_DOLLAR,
    PERCENTAGE,
    EntityCategory,
    UnitOfPrecipitationDepth,
    UnitOfVolume,
    UnitOfVolumeFlowRate,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_COST_PER_1000_GAL,
    CONF_FLOW_SENSOR,
    CONF_MOISTURE_SENSOR,
    CONF_SIMULATION,
    DOMAIN,
    SUBENTRY_ZONE,
)
from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity, SmartWaterZoneEntity
from .units import mm_to_inches
from .week_plan import exact_next_text


def _drop_sensor(hass: HomeAssistant, unique_id: str) -> None:
    """Remove a sensor that no longer has a moisture sensor or a flow meter."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if entity_id is not None:
        registry.async_remove(entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create hub sensors and one set of sensors per zone."""
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    for platform in (DOMAIN, "smart_water"):
        mode_entity = registry.async_get_entity_id(
            "sensor", platform, f"{entry.entry_id}_mode"
        )
        if mode_entity is not None:
            registry.async_remove(mode_entity)
    hub_sensors: list[SensorEntity] = [
        TonightPlanSensor(coordinator),
        ET0Sensor(coordinator),
        RainSensor(coordinator),
        ScheduleSensor(coordinator),
        WateringScheduleSensor(coordinator),
        WateringNowSensor(coordinator),
        WaterUseSensor(coordinator),
        WaterSavedSensor(coordinator),
        AverageSoilMoistureSensor(coordinator),
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
        prefix = f"{entry.entry_id}_{zone_id}"
        zone_sensors: list[SensorEntity] = [
            SoilWaterSensor(coordinator, zone_id),
            DeficitSensor(coordinator, zone_id),
            RawSensor(coordinator, zone_id),
            NextRunSensor(coordinator, zone_id),
            PlanReasonSensor(coordinator, zone_id),
            ZonePlanSensor(coordinator, zone_id),
            LastRunSensor(coordinator, zone_id),
            DormancySensor(coordinator, zone_id),
            ZoneWaterUseSensor(coordinator, zone_id),
            ZoneWaterSavedSensor(coordinator, zone_id),
        ]
        if subentry.data.get(CONF_MOISTURE_SENSOR):
            zone_sensors.append(MoistureSensor(coordinator, zone_id))
        else:
            _drop_sensor(hass, f"{prefix}_moisture")
        if entry.options.get(CONF_FLOW_SENSOR):
            zone_sensors.extend(
                [
                    FlowSensor(coordinator, zone_id),
                    LearnedGpmSensor(coordinator, zone_id),
                    LastRunGpmSensor(coordinator, zone_id),
                    BaselineFlowSensor(coordinator, zone_id),
                    FlowVsBaselineSensor(coordinator, zone_id),
                    FlowTrendSensor(coordinator, zone_id),
                ]
            )
        else:
            for suffix in (
                "flow",
                "learned_gpm",
                "last_run_gpm",
                "baseline_flow",
                "flow_vs_baseline",
                "flow_trend",
            ):
                _drop_sensor(hass, f"{prefix}_{suffix}")
        async_add_entities(zone_sensors, config_subentry_id=zone_id)


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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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


class AverageSoilMoistureSensor(SmartWaterHubEntity, SensorEntity):
    """Mean soil moisture of the enabled zones."""

    _attr_translation_key = "average_soil_moisture"
    _attr_device_class = SensorDeviceClass.MOISTURE
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_average_soil_moisture"
        )

    @property
    def native_value(self) -> float | None:
        """Return the mean percent, or nothing when every zone is off."""
        data = self.coordinator.data
        if data is None:
            return None
        values = [zone.full_pct for zone in data.zones.values() if zone.enabled]
        if not values:
            return None
        return sum(values) / len(values)


class SoilWaterSensor(_ZoneSensor):
    """How full the root zone is, as a percent."""

    _attr_translation_key = "soil_water"
    _attr_device_class = SensorDeviceClass.MOISTURE
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the soil-water sensor."""
        super().__init__(coordinator, zone_id, "soil_water")

    @property
    def native_value(self) -> float | None:
        """Return how full the soil is, from 0 to 100."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.full_pct


class DeficitSensor(_ZoneSensor):
    """How much water the root zone still needs."""

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
            "full_pct": zone.full_pct,
            "history": zone.bucket_history,
            "adjustments": list(
                self.coordinator.store.zone(self._zone_id).get("bucket_adjustments")
                or []
            ),
            "precip_source": zone.precip_source,
            "preset_precip_in_hr": zone.preset_precip_in_hr,
            "preset_efficiency": zone.preset_efficiency,
            "measured_precip_in_hr": zone.measured_precip_in_hr,
            "measured_efficiency": zone.measured_efficiency,
            "du_lq": zone.du_lq,
        }


class RawSensor(_ZoneSensor):
    """The soil dryness that means it is time to water."""

    _attr_translation_key = "raw"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
            "estimated": zone.next_estimated,
            "note": zone.next_note,
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


def earliest_enabled_run(zones) -> datetime | None:
    """Earliest next watering among zones that are turned on."""
    moments = [
        zone.next_run
        for zone in zones
        if getattr(zone, "enabled", True) and zone.next_run is not None
    ]
    if not moments:
        return None
    return min(moments)


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
        """Return the earliest next watering among enabled zones."""
        data = self.coordinator.data
        if data is None or not data.zones:
            return None
        return earliest_enabled_run(data.zones.values())

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Show the allowed days and whether the date is an estimate."""
        data = self.coordinator.data
        if data is None:
            return {}
        earliest = earliest_enabled_run(data.zones.values())
        estimated = False
        note = data.outlook_summary
        if earliest is not None:
            matched = [
                zone for zone in data.zones.values() if zone.next_run == earliest
            ]
            estimated = any(zone.next_estimated for zone in matched)
            notes = [zone.next_note for zone in matched if zone.next_note]
            if notes:
                note = notes[0]
        return {
            "source": data.schedule_source,
            "allowed_weekdays": list(data.allowed_weekdays or []),
            "blackout_start": data.blackout_start,
            "blackout_end": data.blackout_end,
            "round_minutes": data.round_minutes,
            "estimated": estimated,
            "note": note,
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
            "next_run": None if zone.next_run is None else zone.next_run.isoformat(),
            "precip_source": zone.precip_source,
            "preset_precip_in_hr": zone.preset_precip_in_hr,
            "preset_efficiency": zone.preset_efficiency,
            "du_lq": zone.du_lq,
            "precipitation_rate_in_hr": zone.precipitation_rate_in_hr,
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
    """The configured soil-moisture sensor's own reading, as a percent."""

    _attr_translation_key = "moisture"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.MOISTURE
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the moisture sensor."""
        super().__init__(coordinator, zone_id, "moisture")

    @property
    def native_value(self) -> float | None:
        """Return the raw moisture reading as a percent."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.moisture_pct

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Keep the old deficit-from-sensor figure as an attribute."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "mode": zone.moisture_mode,
            "water_needed_mm": zone.moisture_deficit_mm,
            "learn_factor": round(zone.learn_factor, 3),
            "learn_confidence": round(zone.learn_confidence, 2),
        }


class WateringScheduleSensor(SmartWaterHubEntity, SensorEntity):
    """The next watering days, one for each allowed weekday."""

    _attr_translation_key = "watering_schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_watering_schedule"

    @property
    def native_value(self) -> str | None:
        """Return the next watering as an exact local date and time."""
        data = self.coordinator.data
        if data is None or not data.zones:
            return None
        for day in data.schedule_days or []:
            start_at = str(day.get("start_at") or "")
            if not start_at:
                continue
            return exact_next_text(datetime.fromisoformat(start_at))[:255]
        if data.outlook_summary:
            return data.outlook_summary[:255]
        for zone in data.zones.values():
            if zone.enabled and zone.next_note:
                return zone.next_note[:255]
        if all(not zone.enabled for zone in data.zones.values()):
            return "Zone is disabled"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Watering days, each zone's plan, and markdown for a Lovelace card."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "days": data.schedule_days or [],
            "markdown": data.schedule_markdown,
            "window": data.schedule_window,
            "note": (
                "The list is the next watering days, one for each allowed weekday, "
                "within a year. Days with nothing scheduled are left out. Later days "
                "use the forecast or the recent water-loss average and assume no rain. "
                "A day past the weather forecast has estimated set. The date and time stay exact."
            ),
            "alerts": data.alerts,
            "week_gal": round(sum(zone.water_week_gal for zone in data.zones.values()), 1),
            "saved_gal": round(
                sum(zone.saved_week_gal or 0.0 for zone in data.zones.values()), 1
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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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


class BaselineFlowSensor(_ZoneSensor):
    """Permanent catch-cup baseline, or the learned rate when no test has been run."""

    _attr_translation_key = "baseline_flow"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.GALLONS_PER_MINUTE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:speedometer-medium"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the baseline-flow sensor."""
        super().__init__(coordinator, zone_id, "baseline_flow")

    @property
    def native_value(self) -> float | None:
        """Return the baseline, or the learned rate, or none."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.flow_reference_gpm

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """When the baseline was saved, and whether it is learned or measured."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "date": zone.baseline_gpm_at,
            "source": zone.baseline_source,
        }


class FlowVsBaselineSensor(_ZoneSensor):
    """Percent difference of the last run from the baseline."""

    _attr_translation_key = "flow_vs_baseline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:percent"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the flow-versus-baseline sensor."""
        super().__init__(coordinator, zone_id, "flow_vs_baseline")

    @property
    def native_value(self) -> float | None:
        """Return the percent gap. Positive means this run was higher."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.flow_vs_baseline_pct

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """The reference this percent was compared with."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "source": zone.baseline_source,
            "reference_gpm": zone.flow_reference_gpm,
            "last_run_gpm": zone.last_run_gpm,
        }


class FlowTrendSensor(_ZoneSensor):
    """Percent drift of the recent median from the baseline."""

    _attr_translation_key = "flow_trend"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, coordinator, zone_id: str) -> None:
        """Create the flow-trend sensor."""
        super().__init__(coordinator, zone_id, "flow_trend")

    @property
    def native_value(self) -> float | None:
        """Return the median drift. None until a reference exists."""
        zone = self._zone()
        if zone is None:
            return None
        return zone.flow_trend_pct

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Whether the recent median is still learning or past the trend line."""
        zone = self._zone()
        if zone is None:
            return {}
        return {
            "status": zone.flow_trend_status,
            "source": zone.baseline_source,
            "reference_gpm": zone.flow_reference_gpm,
        }


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
