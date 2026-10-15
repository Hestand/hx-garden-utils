"""Hourly weather read, evening bucket update, and dry-run plan.

The coordinator never calls a valve or Hydrawise watering service. It commits
one day of ET and rain at the plan hour (or when calculate_plan asks), then
builds a plan that finishes before sunrise.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .balance import apply_daily_balance, clamp_deficit, root_zone, should_apply_balance
from .const import (
    CONF_ALLOWED_WEEKDAYS,
    CONF_BLACKOUT_END_HOUR,
    CONF_BLACKOUT_START_HOUR,
    CONF_BUCKET,
    CONF_DRIP_IGNORES_SCHEDULE,
    CONF_FIELD_CAPACITY,
    CONF_FLOW_KIND,
    CONF_FLOW_LEAK_RATIO,
    CONF_FLOW_LOW_RATIO,
    CONF_FLOW_SENSOR,
    CONF_MOISTURE_KIND,
    CONF_MOISTURE_MODE,
    CONF_MOISTURE_SENSOR,
    CONF_MOISTURE_WEIGHT,
    CONF_RAIN_AMOUNT_SENSOR,
    CONF_RAIN_KIND,
    CONF_ROUND_MINUTES,
    CONF_SCENARIO,
    CONF_SCHEDULE_PRESET,
    CONF_SIMULATION,
    CONF_SPRINKLER_TYPE,
    CONF_UV_SENSOR,
    CONF_AREA_SQFT,
    CONF_AWC_OVERRIDE,
    CONF_DEPLETION,
    CONF_DRY_RUN,
    CONF_EARLIEST_HOUR,
    CONF_ELEVATION_M,
    CONF_FLOW_GPM,
    CONF_FORECAST_SKIP_MM,
    CONF_HUMIDITY_SENSOR,
    CONF_KC_OVERRIDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MAX_DAILY_RUNTIME_MIN,
    CONF_MODE,
    CONF_NOTIFY_TARGET,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRESSURE_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_SOIL_TYPE,
    CONF_SOLAR_SENSOR,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_HEIGHT_M,
    CONF_WIND_SENSOR,
    DEFAULT_ADJUSTMENT_PCT,
    DEFAULT_DRY_RUN,
    DEFAULT_ELEVATION_M,
    DEFAULT_FLOW_KIND,
    DEFAULT_FLOW_LEAK_RATIO,
    DEFAULT_FLOW_LOW_RATIO,
    DEFAULT_MOISTURE_KIND,
    DEFAULT_MOISTURE_MODE,
    DEFAULT_MOISTURE_WEIGHT,
    DEFAULT_RAIN_KIND,
    DEFAULT_ROUND_MINUTES,
    DEFAULT_SCHEDULE_PRESET,
    DEFAULT_SPRINKLER_TYPE,
    DEFAULT_PLAN_HOUR,
    DEFAULT_SUNRISE_BUFFER_MIN,
    DEFAULT_WIND_HEIGHT_M,
    DOMAIN,
    MODE_NOTIFY_ONLY,
    MODE_OFF,
    MOISTURE_CORRECT,
    MOISTURE_OVERRIDE,
    SUBENTRY_ZONE,
)
from .flow import classify_flow, expected_gallons, note_flow
from .moisture import apply_moisture, deficit_from_reading
from .observe import note_rain, note_solar_w, note_temperature, observed_temperature_range, uv_index_to_w_m2
from .schedule import rules_for
from .et import ETInputs, daily_et0
from .planner import NightPlan, PlanRequest, build_plan, build_zone_request, short_status
from .presets import resolved_root_depth_in
from .safety import would_execute
from .solar import next_sunrise
from .store import SmartWaterStore
from .units import (
    depth_mm,
    pressure_kpa,
    rate_gpm,
    solar_parts,
    speed_m_s,
    temperature_c,
    volume_gallons,
)

_LOGGER = logging.getLogger(__name__)
UPDATE_INTERVAL = timedelta(hours=1)


@dataclass
class ZoneSnapshot:
    """What the zone sensors display."""

    zone_id: str
    name: str
    deficit_mm: float
    taw_mm: float
    raw_mm: float
    p: float
    kc: float
    etc_mm: float | None
    enabled: bool
    reason: str
    next_run: datetime | None
    runtime_min: int | float
    cycles: tuple[int | float, ...]
    soak_min: int
    max_cycle_min: int
    precipitation_rate_in_hr: float
    soil_type: str
    plant_type: str
    scheduled: bool
    valve_entity: str | None
    adjustment_pct: float = DEFAULT_ADJUSTMENT_PCT
    sprinkler_type: str = DEFAULT_SPRINKLER_TYPE
    moisture_deficit_mm: float | None = None
    moisture_mode: str = "off"
    flow_status: str = "not_configured"
    flow_delivered_gal: float = 0.0
    flow_expected_gal: float | None = None
    last_run_now: str | None = None


@dataclass
class HubSnapshot:
    """Coordinator data for hub and zone entities."""

    et0_mm: float | None
    et0_method: str | None
    et0_detail: str | None
    et0_date: str | None
    mode: str
    dry_run: bool
    block_reason: str
    would_execute: bool
    plan: NightPlan | None
    zones: dict[str, ZoneSnapshot]
    last_error: str | None
    summary_short: str
    elevation_m: float
    latitude: float | None
    rain_today_mm: float = 0.0
    effective_rain_mm: float = 0.0
    rain_ignored: bool = False
    precip_source: str = "none"
    solar_mj: float = 0.0
    schedule_source: str = "none"
    allowed_weekdays: tuple[str, ...] | None = None
    blackout_start: int | None = None
    blackout_end: int | None = None
    round_minutes: bool = True
    simulation: dict[str, Any] | None = None


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = _optional_float(data, key)
    if value is None:
        return None
    return int(value)


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None or value == "":
        return None
    return float(value)


def _state_float(
    hass: HomeAssistant, entity_id: str | None
) -> tuple[float | None, str | None]:
    if not entity_id:
        return None, None
    state = hass.states.get(entity_id)
    if state is None or state.state in {"unknown", "unavailable", "none", ""}:
        return None, None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None, None
    unit = state.attributes.get("unit_of_measurement")
    return value, unit


def _is_wet(hass: HomeAssistant, entity_id: str | None) -> bool:
    """True only when the binary sensor is explicitly on."""
    if not entity_id:
        return False
    state = hass.states.get(entity_id)
    if state is None:
        return False
    return state.state == "on"


class SmartWaterCoordinator(DataUpdateCoordinator[HubSnapshot]):
    """Fetch weather, update buckets, and publish a dry-run plan."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: SmartWaterStore,
    ) -> None:
        """Set up the coordinator for one hub."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.config_entry = entry
        self.store = store
        self._notified_date = store.notified_date
        self._lock = asyncio.Lock()

    @callback
    def async_track_plan_time(self) -> None:
        """Refresh a few minutes after the configured plan hour."""
        hour = int(self._options().get(CONF_PLAN_HOUR, DEFAULT_PLAN_HOUR))

        @callback
        def _at_plan_hour(_now: datetime) -> None:
            self.hass.async_create_task(self.async_request_refresh())

        self.config_entry.async_on_unload(
            async_track_time_change(self.hass, _at_plan_hour, hour=hour, minute=5)
        )

    def _options(self) -> dict[str, Any]:
        return dict(self.config_entry.options)

    def _timezone(self) -> ZoneInfo:
        name = self.hass.config.time_zone or "UTC"
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - bad config should not take the hub down
            return ZoneInfo("UTC")

    async def _async_update_data(self) -> HubSnapshot:
        """Hourly refresh. Applies the daily balance only at the plan hour."""
        return await self._async_build(force_balance=False, force_notify=False)

    async def async_calculate_plan(self, *, notify: bool) -> HubSnapshot:
        """Service entry: commit today's balance if needed, then plan."""
        snapshot = await self._async_build(force_balance=True, force_notify=notify)
        self.async_set_updated_data(snapshot)
        return snapshot

    async def async_reset_bucket(self, zone_id: str) -> None:
        """Set the deficit to field capacity without adding today's ET again."""
        state = self.store.zone(zone_id)
        state["deficit_mm"] = 0.0
        await self._save_and_refresh_snapshot()

    async def async_set_bucket(self, zone_id: str, deficit_mm: float) -> None:
        """Set an absolute deficit, clamped to today's TAW on the next build."""
        state = self.store.zone(zone_id)
        state["deficit_mm"] = max(0.0, deficit_mm)
        await self._save_and_refresh_snapshot()

    async def async_mark_watered(self, zone_id: str, depth_mm: float | None) -> None:
        """Subtract a net depth, or refill to field capacity when depth is omitted."""
        state = self.store.zone(zone_id)
        if depth_mm is None:
            state["deficit_mm"] = 0.0
        else:
            state["deficit_mm"] = max(0.0, float(state["deficit_mm"]) - depth_mm)
        await self._save_and_refresh_snapshot()

    async def async_skip_zone(self, zone_id: str, until: str) -> None:
        """Skip the zone through an ISO date, inclusive of that morning."""
        self.store.zone(zone_id)["skipped_until"] = until
        await self._save_and_refresh_snapshot()

    async def async_set_zone_enabled(self, zone_id: str, enabled: bool) -> None:
        """Enable or disable a zone without reloading the config entry."""
        self.store.zone(zone_id)["enabled"] = enabled
        await self._save_and_refresh_snapshot()

    async def async_pause_zone(self, zone_id: str, days: int) -> None:
        """Skip a zone for ``days`` local mornings. Zero clears the pause."""
        if days <= 0:
            self.store.zone(zone_id)["skipped_until"] = None
        else:
            until = (dt_util.now(self._timezone()).date() + timedelta(days=days)).isoformat()
            self.store.zone(zone_id)["skipped_until"] = until
        await self._save_and_refresh_snapshot()

    async def async_set_adjustment(self, zone_id: str, percent: float) -> None:
        """Scale the planned depth. 100 is unchanged. This does not water."""
        self.store.zone(zone_id)["adjustment_pct"] = min(300.0, max(0.0, percent))
        await self._save_and_refresh_snapshot()

    async def async_run_now(self, zone_id: str) -> None:
        """Log the zone's current plan. No valve, switch, or service is called."""
        snapshot = await self._async_build(force_balance=False, force_notify=False)
        zone = snapshot.zones.get(zone_id)
        if zone is None:
            raise HomeAssistantError(f"Unknown Smart Water zone {zone_id}")
        cycles = "+".join(str(minutes) for minutes in zone.cycles) or "0"
        message = (
            f"Smart Water run-now for {zone.name} planned {zone.runtime_min} min "
            f"({cycles}). Not executed; no valve or switch was called."
        )
        _LOGGER.info(message)
        self.store.zone(zone_id)["last_run_now"] = message
        await self.store.async_save()
        self.async_set_updated_data(
            await self._async_build(force_balance=False, force_notify=False)
        )

    async def async_set_mode(self, mode: str) -> None:
        """Change hub mode. This does not change the dry-run flag."""
        options = self._options()
        options[CONF_MODE] = mode
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)

    async def _save_and_refresh_snapshot(self) -> None:
        snapshot = await self._async_build(force_balance=False, force_notify=False)
        self.async_set_updated_data(snapshot)

    async def _async_build(self, *, force_balance: bool, force_notify: bool) -> HubSnapshot:
        async with self._lock:
            return await self._async_build_locked(
                force_balance=force_balance, force_notify=force_notify
            )

    async def _async_build_locked(
        self, *, force_balance: bool, force_notify: bool
    ) -> HubSnapshot:
        options = self._options()
        now = dt_util.now(self._timezone())
        today = now.date().isoformat()
        plan_hour = int(options.get(CONF_PLAN_HOUR, DEFAULT_PLAN_HOUR))
        dry_run = bool(options.get(CONF_DRY_RUN, DEFAULT_DRY_RUN))
        mode = str(options.get(CONF_MODE, MODE_NOTIFY_ONLY))
        elevation = float(options.get(CONF_ELEVATION_M, DEFAULT_ELEVATION_M))
        latitude = options.get(CONF_LATITUDE, self.hass.config.latitude)
        longitude = options.get(CONF_LONGITUDE, self.hass.config.longitude)
        latitude_f = None if latitude is None else float(latitude)
        longitude_f = None if longitude is None else float(longitude)
        error: str | None = None

        self._accumulate_day(now, today)
        observation = self._overlay_observed(await self._async_observation(now))
        if observation.error:
            error = observation.error
        et_result = daily_et0(observation.inputs) if observation.inputs else None
        et0 = None if et_result is None else et_result.et0_mm
        if et_result is not None and et0 is not None:
            self.store.et0_mm = et0
            self.store.et0_method = et_result.method
            self.store.et0_detail = et_result.detail
            self.store.et0_date = today
        elif et_result is not None and et_result.detail:
            error = error or et_result.detail

        zone_ids = [
            subentry.subentry_id
            for subentry in self.config_entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_ZONE
        ]
        self.store.prune(set(zone_ids))
        # Planning can reuse the last good ET0 when today's weather read fails.
        # The bucket is only credited when this refresh actually computed ET0.
        et0_for_plan = et0 if et0 is not None else self.store.et0_mm
        if et0 is not None:
            preview = apply_daily_balance(
                0.0,
                1000.0,
                etc_mm=et0,
                precip_mm=observation.precip_today_mm,
                et0_mm=et0,
            )
            self.store.weather["effective_rain_mm"] = preview.effective_precip_mm
            self.store.weather["rain_ignored"] = preview.rain_ignored

        for subentry_id in zone_ids:
            subentry = self.config_entry.subentries[subentry_id]
            state = self.store.zone(subentry_id)
            try:
                limits = self._limits(subentry.data, et0, now.month)
            except (KeyError, ValueError) as err:
                error = f"{subentry.title}: {err}"
                continue
            state["deficit_mm"] = clamp_deficit(float(state["deficit_mm"]), limits.taw_mm)
            balanced = False
            if (
                et0 is not None
                and limits.etc_mm is not None
                and should_apply_balance(
                    state.get("balance_date"),
                    today,
                    now.hour,
                    plan_hour,
                    force=force_balance,
                )
            ):
                updated = apply_daily_balance(
                    float(state["deficit_mm"]),
                    limits.taw_mm,
                    etc_mm=limits.etc_mm,
                    precip_mm=observation.precip_today_mm,
                    et0_mm=et0,
                )
                state["deficit_mm"] = updated.deficit_mm
                state["balance_date"] = today
                balanced = True
            self._apply_moisture(state, dict(subentry.data), limits, balanced=balanced)
            self._note_zone_flow(state, dict(subentry.data), now, today)

        plan: NightPlan | None = None
        try:
            plan = self._build_plan(
                now=now,
                et0=et0_for_plan,
                latitude=latitude_f,
                longitude=longitude_f,
                precip_tomorrow_mm=observation.precip_tomorrow_mm,
                dry_run=dry_run,
                mode=mode,
            )
        except (KeyError, ValueError) as err:
            error = str(err)
            _LOGGER.warning("Smart Water could not build a plan: %s", err)

        if plan is not None:
            self.store.plan = plan.to_dict()
            await self._maybe_notify(
                plan,
                today=today,
                mode=mode,
                force_notify=force_notify,
            )
        if (
            self.config_entry.data.get(CONF_SIMULATION)
            and not self.store.simulation
            and zone_ids
        ):
            try:
                self.store.simulation = self.simulate_week()
            except (KeyError, TypeError, ValueError) as err:
                error = error or f"Simulation: {err}"
                _LOGGER.warning("Smart Water could not simulate a week: %s", err)
        await self.store.async_save()
        return self._snapshot(
            et0=self.store.et0_mm,
            method=self.store.et0_method,
            detail=self.store.et0_detail,
            et0_date=self.store.et0_date,
            dry_run=dry_run,
            mode=mode,
            plan=plan,
            error=error,
            elevation=elevation,
            latitude=latitude_f,
        )

    def _accumulate_day(self, now: datetime, today: str) -> None:
        """Fold entity samples into today's temperature, rain, solar, and flow."""
        options = self._options()
        track = self.store.weather_for(today)
        temp, temp_unit = _state_float(self.hass, options.get(CONF_TEMPERATURE_SENSOR))
        if temp is not None:
            note_temperature(track, temperature_c(temp, temp_unit))
        rain, rain_unit = _state_float(self.hass, options.get(CONF_RAIN_AMOUNT_SENSOR))
        if rain is not None:
            note_rain(
                track,
                kind=str(options.get(CONF_RAIN_KIND, DEFAULT_RAIN_KIND)),
                value_mm=depth_mm(rain, rain_unit),
                at=now,
            )
            track["precip_source"] = "sensor"
        solar, solar_unit = _state_float(self.hass, options.get(CONF_SOLAR_SENSOR))
        if solar is not None:
            _rs, watts = solar_parts(solar, solar_unit)
            if watts is not None:
                note_solar_w(track, watts, now)
            elif _rs is not None:
                track["solar_mj"] = max(float(track["solar_mj"]), _rs)
        elif (uv := _state_float(self.hass, options.get(CONF_UV_SENSOR))[0]) is not None:
            note_solar_w(track, uv_index_to_w_m2(uv), now)

    def _overlay_observed(self, observation: Observation) -> Observation:
        """Prefer accumulated entity data, then the weather entity."""
        options = self._options()
        track = self.store.weather
        inputs = observation.inputs
        observed = observed_temperature_range(track)
        solar_mj = float(track["solar_mj"] or 0.0)
        if inputs is None and observed is None and solar_mj <= 0:
            return observation
        if inputs is None:
            latitude = options.get(CONF_LATITUDE, self.hass.config.latitude)
            high, low = observed if observed is not None else (None, None)
            inputs = ETInputs(
                t_max_c=high,
                t_min_c=low,
                latitude_deg=None if latitude is None else float(latitude),
                day_of_year=dt_util.now(self._timezone()).timetuple().tm_yday,
                elevation_m=float(options.get(CONF_ELEVATION_M, DEFAULT_ELEVATION_M)),
                wind_height_m=float(options.get(CONF_WIND_HEIGHT_M, DEFAULT_WIND_HEIGHT_M)),
            )
        if observed is not None and options.get(CONF_TEMPERATURE_SENSOR):
            inputs = ETInputs(
                t_max_c=observed[0],
                t_min_c=observed[1],
                latitude_deg=inputs.latitude_deg,
                day_of_year=inputs.day_of_year,
                elevation_m=inputs.elevation_m,
                rh_mean_pct=inputs.rh_mean_pct,
                rh_max_pct=inputs.rh_max_pct,
                rh_min_pct=inputs.rh_min_pct,
                wind_m_s=inputs.wind_m_s,
                wind_height_m=inputs.wind_height_m,
                pressure_kpa=inputs.pressure_kpa,
                rs_mj_m2_day=inputs.rs_mj_m2_day,
                solar_w_m2=inputs.solar_w_m2,
            )
        if solar_mj > 0:
            # The integral is the daily total, so the instantaneous reading
            # must not also be described as unused.
            inputs = ETInputs(
                t_max_c=inputs.t_max_c,
                t_min_c=inputs.t_min_c,
                latitude_deg=inputs.latitude_deg,
                day_of_year=inputs.day_of_year,
                elevation_m=inputs.elevation_m,
                rh_mean_pct=inputs.rh_mean_pct,
                rh_max_pct=inputs.rh_max_pct,
                rh_min_pct=inputs.rh_min_pct,
                wind_m_s=inputs.wind_m_s,
                wind_height_m=inputs.wind_height_m,
                pressure_kpa=inputs.pressure_kpa,
                rs_mj_m2_day=solar_mj,
                solar_w_m2=None,
            )
        precip = observation.precip_today_mm
        if options.get(CONF_RAIN_AMOUNT_SENSOR):
            precip = float(track["rain_mm"])
            track["precip_source"] = "sensor"
        elif precip:
            track["precip_source"] = "forecast"
            track["rain_mm"] = precip
        error = observation.error
        if (
            error == "Weather entity is unavailable."
            and inputs is not None
            and inputs.t_max_c is not None
        ):
            error = None
        return Observation(
            inputs=inputs,
            precip_today_mm=precip,
            precip_tomorrow_mm=observation.precip_tomorrow_mm,
            error=error,
        )

    def _apply_moisture(
        self,
        state: dict[str, Any],
        data: dict[str, Any],
        limits,
        *,
        balanced: bool,
    ) -> None:
        mode = str(data.get(CONF_MOISTURE_MODE, DEFAULT_MOISTURE_MODE))
        if mode in {"", "off"} or not data.get(CONF_MOISTURE_SENSOR):
            state["moisture_deficit_mm"] = None
            return
        reading, _unit = _state_float(self.hass, data.get(CONF_MOISTURE_SENSOR))
        if reading is None:
            return
        try:
            sensor_mm = deficit_from_reading(
                reading=reading,
                kind=str(data.get(CONF_MOISTURE_KIND, DEFAULT_MOISTURE_KIND)),
                taw_mm=limits.taw_mm,
                zr_m=limits.zr_m,
                field_capacity_vwc=_optional_float(data, CONF_FIELD_CAPACITY),
            )
        except ValueError as err:
            _LOGGER.debug("Moisture reading skipped: %s", err)
            return
        state["moisture_deficit_mm"] = sensor_mm
        if mode == MOISTURE_OVERRIDE or (mode == MOISTURE_CORRECT and balanced):
            state["deficit_mm"] = clamp_deficit(
                apply_moisture(
                    float(state["deficit_mm"]),
                    sensor_mm,
                    mode=mode,
                    weight=float(data.get(CONF_MOISTURE_WEIGHT, DEFAULT_MOISTURE_WEIGHT)),
                ),
                limits.taw_mm,
            )

    def _note_zone_flow(
        self,
        state: dict[str, Any],
        data: dict[str, Any],
        now: datetime,
        today: str,
    ) -> None:
        entity_id = data.get(CONF_FLOW_SENSOR) or None
        if not entity_id:
            return
        value, unit = _state_float(self.hass, entity_id)
        if value is None:
            return
        kind = str(data.get(CONF_FLOW_KIND, DEFAULT_FLOW_KIND))
        gallons = volume_gallons(value, unit) if kind != "rate" else rate_gpm(value, unit)
        note_flow(state, kind=kind, gallons=gallons, at=now, today=today)

    def _limits(self, data: dict[str, Any], et0: float | None, month: int | None = None):
        return root_zone(
            soil_type=data[CONF_SOIL_TYPE],
            plant_type=data[CONF_PLANT_TYPE],
            sun_exposure=data[CONF_SUN_EXPOSURE],
            root_depth_in=resolved_root_depth_in(data),
            p_table=_optional_float(data, CONF_DEPLETION),
            kc_override=_optional_float(data, CONF_KC_OVERRIDE),
            awc_override=_optional_float(data, CONF_AWC_OVERRIDE),
            et0_mm=et0,
            month=month,
        )

    def _build_plan(
        self,
        *,
        now: datetime,
        et0: float | None,
        latitude: float | None,
        longitude: float | None,
        precip_tomorrow_mm: float,
        dry_run: bool,
        mode: str,
    ) -> NightPlan:
        options = self._options()
        if latitude is None or longitude is None:
            raise ValueError("Latitude and longitude are required to find sunrise.")
        buffer_min = int(options.get(CONF_SUNRISE_BUFFER_MIN, DEFAULT_SUNRISE_BUFFER_MIN))
        rise = next_sunrise(latitude, longitude, now)
        finish_by = rise.astimezone(now.tzinfo) - timedelta(minutes=buffer_min)
        earliest = None
        if options.get(CONF_EARLIEST_HOUR) is not None:
            hour = int(options[CONF_EARLIEST_HOUR])
            local_finish = finish_by.astimezone(now.tzinfo)
            earliest = local_finish.replace(hour=hour, minute=0, second=0, microsecond=0)
        hub_wet = _is_wet(self.hass, options.get(CONF_RAIN_SENSOR) or None)
        requests = []
        drip_ignores = bool(options.get(CONF_DRIP_IGNORES_SCHEDULE, False))
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ZONE:
                continue
            data = dict(subentry.data)
            state = self.store.zone(subentry.subentry_id)
            requests.append(
                build_zone_request(
                    zone_id=subentry.subentry_id,
                    name=subentry.title,
                    data=data,
                    deficit_mm=float(state["deficit_mm"]),
                    et0_mm=et0,
                    month=now.month,
                    enabled=bool(state.get("enabled", True)),
                    rain_sensor_wet=_is_wet(self.hass, data.get(CONF_RAIN_SENSOR) or None),
                    skipped_until=state.get("skipped_until"),
                    adjustment_pct=float(
                        state.get("adjustment_pct", DEFAULT_ADJUSTMENT_PCT)
                    ),
                    drip_ignores_schedule=drip_ignores,
                )
            )
        skip = _optional_float(options, CONF_FORECAST_SKIP_MM)
        cap = options.get(CONF_MAX_DAILY_RUNTIME_MIN)
        schedule = rules_for(
            str(options.get(CONF_SCHEDULE_PRESET, DEFAULT_SCHEDULE_PRESET)),
            options.get(CONF_ALLOWED_WEEKDAYS),
            _optional_int(options, CONF_BLACKOUT_START_HOUR),
            _optional_int(options, CONF_BLACKOUT_END_HOUR),
        )
        return build_plan(
            PlanRequest(
                zones=tuple(requests),
                finish_by=finish_by,
                earliest_start=earliest,
                forecast_precip_mm=precip_tomorrow_mm,
                forecast_skip_mm=skip,
                hub_rain_wet=hub_wet,
                mode=mode,
                dry_run=dry_run,
                max_daily_runtime_min=None if cap in (None, "") else int(cap),
                allowed_weekdays=schedule.allowed_weekdays,
                blackout_start_hour=schedule.blackout_start,
                blackout_end_hour=schedule.blackout_end,
                whole_minutes=bool(options.get(CONF_ROUND_MINUTES, DEFAULT_ROUND_MINUTES)),
            )
        )

    def _measurement_fields(
        self,
        state: dict[str, Any],
        data: dict[str, Any],
        *,
        scheduled: bool,
        runtime_min: float,
        precip: float | None,
        next_run: datetime | None,
    ) -> dict[str, Any]:
        """Flow classification and the stored overrides for one zone snapshot."""
        delivered = float(state.get("flow_delivered_gal") or 0.0)
        expected = None
        status = "not_configured"
        if data.get(CONF_FLOW_SENSOR):
            expected = expected_gallons(
                runtime_min=runtime_min,
                precipitation_rate_in_hr=precip,
                area_sqft=_optional_float(data, CONF_AREA_SQFT),
                flow_gpm=_optional_float(data, CONF_FLOW_GPM),
            )
            now = dt_util.now(self._timezone())
            run_finished = True
            if scheduled and next_run is not None:
                run_finished = now >= next_run + timedelta(minutes=float(runtime_min))
            status = classify_flow(
                expected_gal=expected,
                delivered_gal=delivered,
                scheduled=scheduled,
                run_finished=run_finished,
                low_ratio=float(data.get(CONF_FLOW_LOW_RATIO, DEFAULT_FLOW_LOW_RATIO)),
                leak_ratio=float(data.get(CONF_FLOW_LEAK_RATIO, DEFAULT_FLOW_LEAK_RATIO)),
            )
        return {
            "adjustment_pct": float(state.get("adjustment_pct", DEFAULT_ADJUSTMENT_PCT)),
            "sprinkler_type": str(data.get(CONF_SPRINKLER_TYPE, DEFAULT_SPRINKLER_TYPE)),
            "moisture_deficit_mm": state.get("moisture_deficit_mm"),
            "moisture_mode": str(data.get(CONF_MOISTURE_MODE, DEFAULT_MOISTURE_MODE)),
            "flow_status": status,
            "flow_delivered_gal": delivered,
            "flow_expected_gal": expected,
            "last_run_now": state.get("last_run_now"),
        }

    def _snapshot(
        self,
        *,
        et0: float | None,
        method: str | None,
        detail: str | None,
        et0_date: str | None,
        dry_run: bool,
        mode: str,
        plan: NightPlan | None,
        error: str | None,
        elevation: float,
        latitude: float | None,
    ) -> HubSnapshot:
        by_zone: dict[str, Any] = {}
        if plan is not None:
            next_run: dict[str, datetime] = {}
            for event in plan.timeline:
                next_run.setdefault(event.zone_id, event.start)
            for zone in plan.zones:
                subentry = self.config_entry.subentries.get(zone.zone_id)
                data = dict(subentry.data) if subentry is not None else {}
                state = self.store.zone(zone.zone_id)
                by_zone[zone.zone_id] = ZoneSnapshot(
                    zone_id=zone.zone_id,
                    name=zone.name,
                    deficit_mm=float(state["deficit_mm"]),
                    taw_mm=zone.taw_mm,
                    raw_mm=zone.raw_mm,
                    p=zone.p,
                    kc=zone.kc,
                    etc_mm=zone.etc_mm,
                    enabled=bool(state.get("enabled", True)),
                    reason=zone.reason,
                    next_run=next_run.get(zone.zone_id),
                    runtime_min=zone.runtime_min,
                    cycles=zone.cycles,
                    soak_min=zone.soak_min,
                    max_cycle_min=zone.max_cycle_min,
                    precipitation_rate_in_hr=zone.precipitation_rate_in_hr,
                    soil_type=str(data.get(CONF_SOIL_TYPE, "")),
                    plant_type=str(data.get(CONF_PLANT_TYPE, "")),
                    scheduled=zone.scheduled,
                    valve_entity=data.get(CONF_VALVE_ENTITY) or None,
                    **self._measurement_fields(
                        state,
                        data,
                        scheduled=zone.scheduled,
                        runtime_min=zone.runtime_min,
                        precip=zone.precipitation_rate_in_hr,
                        next_run=next_run.get(zone.zone_id),
                    ),
                )
        else:
            for subentry in self.config_entry.subentries.values():
                if subentry.subentry_type != SUBENTRY_ZONE:
                    continue
                state = self.store.zone(subentry.subentry_id)
                try:
                    limits = self._limits(
                        dict(subentry.data),
                        et0,
                        dt_util.now(self._timezone()).month,
                    )
                    taw, raw, p, kc, etc = (
                        limits.taw_mm,
                        limits.raw_mm,
                        limits.p,
                        limits.kc,
                        limits.etc_mm,
                    )
                except (KeyError, ValueError):
                    taw, raw, p, kc, etc = 0.0, 0.0, 0.0, 0.0, None
                by_zone[subentry.subentry_id] = ZoneSnapshot(
                    zone_id=subentry.subentry_id,
                    name=subentry.title,
                    deficit_mm=float(state["deficit_mm"]),
                    taw_mm=taw,
                    raw_mm=raw,
                    p=p,
                    kc=kc,
                    etc_mm=etc,
                    enabled=bool(state.get("enabled", True)),
                    reason=error or "No plan yet.",
                    next_run=None,
                    runtime_min=0,
                    cycles=(),
                    soak_min=0,
                    max_cycle_min=0,
                    precipitation_rate_in_hr=0.0,
                    soil_type=str(subentry.data.get(CONF_SOIL_TYPE, "")),
                    plant_type=str(subentry.data.get(CONF_PLANT_TYPE, "")),
                    scheduled=False,
                    valve_entity=subentry.data.get(CONF_VALVE_ENTITY) or None,
                    **self._measurement_fields(
                        state,
                        dict(subentry.data),
                        scheduled=False,
                        runtime_min=0,
                        precip=_optional_float(dict(subentry.data), CONF_PRECIPITATION_RATE),
                        next_run=None,
                    ),
                )
        blocked = plan.block_reason if plan is not None else "No plan yet."
        options = self._options()
        rules = rules_for(
            str(options.get(CONF_SCHEDULE_PRESET, DEFAULT_SCHEDULE_PRESET)),
            options.get(CONF_ALLOWED_WEEKDAYS),
            _optional_int(options, CONF_BLACKOUT_START_HOUR),
            _optional_int(options, CONF_BLACKOUT_END_HOUR),
        )
        return HubSnapshot(
            et0_mm=et0,
            et0_method=method,
            et0_detail=detail,
            et0_date=et0_date,
            mode=mode,
            dry_run=dry_run,
            block_reason=blocked,
            would_execute=would_execute(dry_run=dry_run, mode=mode),
            plan=plan,
            zones=by_zone,
            last_error=error,
            summary_short=short_status(plan),
            elevation_m=elevation,
            latitude=latitude,
            rain_today_mm=float(self.store.weather.get("rain_mm") or 0.0),
            effective_rain_mm=float(self.store.weather.get("effective_rain_mm") or 0.0),
            rain_ignored=bool(self.store.weather.get("rain_ignored")),
            precip_source=str(self.store.weather.get("precip_source") or "none"),
            solar_mj=float(self.store.weather.get("solar_mj") or 0.0),
            schedule_source=rules.source,
            allowed_weekdays=rules.allowed_weekdays,
            blackout_start=rules.blackout_start,
            blackout_end=rules.blackout_end,
            round_minutes=bool(options.get(CONF_ROUND_MINUTES, DEFAULT_ROUND_MINUTES)),
            simulation=self.store.simulation,
        )

    async def _maybe_notify(
        self,
        plan: NightPlan,
        *,
        today: str,
        mode: str,
        force_notify: bool,
    ) -> None:
        target = str(self._options().get(CONF_NOTIFY_TARGET) or "").strip()
        if not target:
            return
        now = dt_util.now(self._timezone())
        plan_hour = int(self._options().get(CONF_PLAN_HOUR, DEFAULT_PLAN_HOUR))
        automatic = (
            not force_notify
            and mode != MODE_OFF
            and now.hour >= plan_hour
            and self._notified_date != today
        )
        if not force_notify and not automatic:
            return
        if "." in target:
            domain, service = target.split(".", 1)
        else:
            domain, service = "notify", target
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {
                    "title": "Smart Water dry-run",
                    "message": plan.summary,
                },
                blocking=False,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Smart Water could not notify %s: %s", target, err)
            return
        if automatic:
            self._notified_date = today
            self.store.notified_date = today

    def simulate_week(
        self,
        *,
        scenario: str | None = None,
        days: list[dict[str, Any]] | None = None,
        bucket: str | None = None,
        start: str | None = None,
    ) -> dict[str, Any]:
        """Run a week in memory. Does not change zone deficits or call a valve."""
        from .simulate import (
            DEFAULT_BUCKET,
            DEFAULT_SCENARIO,
            SimSettings,
            SimZone,
            parse_day,
            preset_week,
            run_week,
        )

        options = self._options()
        chosen = str(scenario or options.get(CONF_SCENARIO) or DEFAULT_SCENARIO)
        chosen_bucket = str(bucket or options.get(CONF_BUCKET) or DEFAULT_BUCKET)
        if days:
            weather = tuple(parse_day(day) for day in days)
            scenario_key: str | None = None
        else:
            weather = preset_week(chosen)
            scenario_key = chosen
        latitude = options.get(CONF_LATITUDE, self.hass.config.latitude)
        longitude = options.get(CONF_LONGITUDE, self.hass.config.longitude)
        if latitude is None or longitude is None:
            raise ValueError("Latitude and longitude are required to simulate a week.")
        start_date = None
        if start:
            start_date = date.fromisoformat(str(start)[:10])
        zones = []
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ZONE:
                continue
            state = self.store.zone(subentry.subentry_id)
            zones.append(
                SimZone(
                    zone_id=subentry.subentry_id,
                    name=subentry.title,
                    data=dict(subentry.data),
                    enabled=bool(state.get("enabled", True)),
                    skipped_until=state.get("skipped_until"),
                    adjustment_pct=float(
                        state.get("adjustment_pct", DEFAULT_ADJUSTMENT_PCT)
                    ),
                )
            )
        cap = options.get(CONF_MAX_DAILY_RUNTIME_MIN)
        return run_week(
            tuple(zones),
            weather,
            SimSettings(
                latitude=float(latitude),
                longitude=float(longitude),
                elevation_m=float(options.get(CONF_ELEVATION_M, DEFAULT_ELEVATION_M)),
                timezone=self._timezone().key,
                start=start_date,
                sunrise_buffer_min=int(
                    options.get(CONF_SUNRISE_BUFFER_MIN, DEFAULT_SUNRISE_BUFFER_MIN)
                ),
                plan_hour=int(options.get(CONF_PLAN_HOUR, DEFAULT_PLAN_HOUR)),
                earliest_hour=_optional_int(options, CONF_EARLIEST_HOUR),
                forecast_skip_mm=_optional_float(options, CONF_FORECAST_SKIP_MM),
                max_daily_runtime_min=None if cap in (None, "") else int(cap),
                schedule_preset=str(
                    options.get(CONF_SCHEDULE_PRESET, DEFAULT_SCHEDULE_PRESET)
                ),
                allowed_weekdays=(
                    tuple(options.get(CONF_ALLOWED_WEEKDAYS) or ()) or None
                ),
                blackout_start_hour=_optional_int(options, CONF_BLACKOUT_START_HOUR),
                blackout_end_hour=_optional_int(options, CONF_BLACKOUT_END_HOUR),
                drip_ignores_schedule=bool(options.get(CONF_DRIP_IGNORES_SCHEDULE, False)),
                whole_minutes=bool(options.get(CONF_ROUND_MINUTES, DEFAULT_ROUND_MINUTES)),
                wind_height_m=float(options.get(CONF_WIND_HEIGHT_M, DEFAULT_WIND_HEIGHT_M)),
                mode=str(options.get(CONF_MODE, MODE_NOTIFY_ONLY)),
                dry_run=bool(options.get(CONF_DRY_RUN, DEFAULT_DRY_RUN)),
            ),
            bucket=chosen_bucket,
            scenario=scenario_key,
        )

    async def async_simulate(
        self,
        *,
        scenario: str | None = None,
        days: list[dict[str, Any]] | None = None,
        bucket: str | None = None,
        start: str | None = None,
    ) -> dict[str, Any]:
        """Store a week simulation and refresh sensors. Does not actuate."""
        result = self.simulate_week(
            scenario=scenario, days=days, bucket=bucket, start=start
        )
        self.store.simulation = result
        snapshot = await self._async_build(force_balance=False, force_notify=False)
        self.async_set_updated_data(snapshot)
        return result

    async def _async_observation(self, now: datetime) -> Observation:
        options = self._options()
        entity_id = self.config_entry.data.get(CONF_WEATHER_ENTITY)
        if self.config_entry.data.get(CONF_SIMULATION) and not entity_id:
            return Observation(
                inputs=None,
                precip_today_mm=0.0,
                precip_tomorrow_mm=0.0,
                error=None,
            )
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in {"unknown", "unavailable"}:
            return Observation(
                inputs=None,
                precip_today_mm=0.0,
                precip_tomorrow_mm=0.0,
                error="Weather entity is unavailable.",
            )
        attributes = state.attributes
        temp_unit = attributes.get("temperature_unit")
        precip_unit = attributes.get("precipitation_unit")
        wind_unit = attributes.get("wind_speed_unit")
        forecast, forecast_error = await self._async_forecast(entity_id)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        today_row = _forecast_on(forecast, today)
        tomorrow_row = _forecast_on(forecast, tomorrow)
        t_max = _row_temp(today_row, "temperature", temp_unit)
        t_min = _row_temp(today_row, "templow", temp_unit)
        if t_max is None:
            current = attributes.get("temperature")
            if current is not None:
                t_max = temperature_c(float(current), temp_unit)
                t_min = t_max
        humidity, _unit = _state_float(self.hass, options.get(CONF_HUMIDITY_SENSOR))
        if humidity is None and attributes.get("humidity") is not None:
            humidity = float(attributes["humidity"])
        wind, wind_sensor_unit = _state_float(self.hass, options.get(CONF_WIND_SENSOR))
        if wind is not None:
            wind = speed_m_s(wind, wind_sensor_unit)
        elif attributes.get("wind_speed") is not None:
            wind = speed_m_s(float(attributes["wind_speed"]), wind_unit)
        elif today_row and today_row.get("wind_speed") is not None:
            wind = speed_m_s(float(today_row["wind_speed"]), wind_unit)
        pressure, pressure_unit = _state_float(
            self.hass, options.get(CONF_PRESSURE_SENSOR)
        )
        if pressure is not None:
            pressure = pressure_kpa(pressure, pressure_unit)
        solar_value, solar_unit = _state_float(self.hass, options.get(CONF_SOLAR_SENSOR))
        rs_mj = None
        solar_w = None
        if solar_value is not None:
            rs_mj, solar_w = solar_parts(solar_value, solar_unit)
        # A configured temperature sensor is recorded only as a fallback when
        # the forecast has no high. It is still a single reading, so max and
        # min stay equal and Hargreaves ET from that path is zero — the detail
        # string from daily_et0 explains it. Prefer the forecast.
        sensor_temp, sensor_unit = _state_float(
            self.hass, options.get(CONF_TEMPERATURE_SENSOR)
        )
        if t_max is None and sensor_temp is not None:
            t_max = temperature_c(sensor_temp, sensor_unit)
            t_min = t_max
        latitude = options.get(CONF_LATITUDE, self.hass.config.latitude)
        inputs = ETInputs(
            t_max_c=t_max,
            t_min_c=t_min,
            latitude_deg=None if latitude is None else float(latitude),
            day_of_year=today.timetuple().tm_yday,
            elevation_m=float(options.get(CONF_ELEVATION_M, DEFAULT_ELEVATION_M)),
            rh_mean_pct=humidity,
            wind_m_s=wind,
            wind_height_m=float(options.get(CONF_WIND_HEIGHT_M, DEFAULT_WIND_HEIGHT_M)),
            pressure_kpa=pressure,
            rs_mj_m2_day=rs_mj,
            solar_w_m2=solar_w,
        )
        return Observation(
            inputs=inputs,
            precip_today_mm=_row_precip(today_row, precip_unit),
            precip_tomorrow_mm=_row_precip(tomorrow_row, precip_unit),
            error=forecast_error,
        )

    async def _async_forecast(
        self, entity_id: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": "daily"},
                target={"entity_id": entity_id},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            return [], f"Weather forecast failed: {err}"
        if not isinstance(response, dict):
            return [], "Weather forecast returned no data."
        payload = response.get(entity_id) or {}
        forecast = payload.get("forecast") or []
        return list(forecast), None


@dataclass
class Observation:
    """Weather reduced to ET inputs and two precipitation totals."""

    inputs: ETInputs | None
    precip_today_mm: float
    precip_tomorrow_mm: float
    error: str | None


def _forecast_on(forecast: list[dict[str, Any]], day) -> dict[str, Any] | None:
    for row in forecast:
        stamp = row.get("datetime")
        if not stamp:
            continue
        parsed = dt_util.parse_datetime(str(stamp))
        if parsed is None:
            continue
        if dt_util.as_local(parsed).date() == day:
            return row
    return None


def _row_temp(row: dict[str, Any] | None, key: str, unit: str | None) -> float | None:
    if not row or row.get(key) is None:
        return None
    return temperature_c(float(row[key]), unit)


def _row_precip(row: dict[str, Any] | None, unit: str | None) -> float:
    if not row or row.get("precipitation") is None:
        return 0.0
    return depth_mm(float(row["precipitation"]), unit)


type SmartWaterConfigEntry = ConfigEntry[SmartWaterCoordinator]
