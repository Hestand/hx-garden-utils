"""Hourly weather read, evening bucket update, and dry-run plan.

The coordinator never calls a valve or Hydrawise watering service. It commits
one day of ET and rain at the plan hour (or when calculate_plan asks), then
builds a plan that finishes before sunrise.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    CONF_AREA_SQFT,
    CONF_AWC_OVERRIDE,
    CONF_DEPLETION,
    CONF_DRY_RUN,
    CONF_EARLIEST_HOUR,
    CONF_EFFICIENCY,
    CONF_ELEVATION_M,
    CONF_FLOW_GPM,
    CONF_FORECAST_SKIP_MM,
    CONF_HUMIDITY_SENSOR,
    CONF_KC_OVERRIDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MAX_CYCLE_MIN,
    CONF_MAX_DAILY_RUNTIME_MIN,
    CONF_MODE,
    CONF_NOTIFY_TARGET,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRESSURE_SENSOR,
    CONF_PRIORITY,
    CONF_RAIN_SENSOR,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOAK_MIN,
    CONF_SOIL_TYPE,
    CONF_SOLAR_SENSOR,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_HEIGHT_M,
    CONF_WIND_SENSOR,
    DEFAULT_DRY_RUN,
    DEFAULT_EFFICIENCY,
    DEFAULT_ELEVATION_M,
    DEFAULT_PLAN_HOUR,
    DEFAULT_PRIORITY,
    DEFAULT_SUNRISE_BUFFER_MIN,
    DEFAULT_WIND_HEIGHT_M,
    DOMAIN,
    MODE_NOTIFY_ONLY,
    MODE_OFF,
    SUBENTRY_ZONE,
)
from .cycle_soak import resolve_precipitation_rate
from .et import ETInputs, daily_et0
from .planner import NightPlan, PlanRequest, ZoneRequest, build_plan, short_status
from .safety import would_execute
from .solar import next_sunrise
from .store import SmartWaterStore
from .units import (
    depth_mm,
    pressure_kpa,
    solar_parts,
    speed_m_s,
    temperature_c,
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
    runtime_min: int
    cycles: tuple[int, ...]
    soak_min: int
    max_cycle_min: int
    precipitation_rate_in_hr: float
    soil_type: str
    plant_type: str
    scheduled: bool
    valve_entity: str | None


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

        observation = await self._async_observation(now)
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

        for subentry_id in zone_ids:
            subentry = self.config_entry.subentries[subentry_id]
            state = self.store.zone(subentry_id)
            try:
                limits = self._limits(subentry.data, et0)
            except (KeyError, ValueError) as err:
                error = f"{subentry.title}: {err}"
                continue
            state["deficit_mm"] = clamp_deficit(float(state["deficit_mm"]), limits.taw_mm)
            if et0 is None or limits.etc_mm is None:
                continue
            if not should_apply_balance(
                state.get("balance_date"),
                today,
                now.hour,
                plan_hour,
                force=force_balance,
            ):
                continue
            updated = apply_daily_balance(
                float(state["deficit_mm"]),
                limits.taw_mm,
                etc_mm=limits.etc_mm,
                precip_mm=observation.precip_today_mm,
                et0_mm=et0,
            )
            state["deficit_mm"] = updated.deficit_mm
            state["balance_date"] = today

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

    def _limits(self, data: dict[str, Any], et0: float | None):
        return root_zone(
            soil_type=data[CONF_SOIL_TYPE],
            plant_type=data[CONF_PLANT_TYPE],
            sun_exposure=data[CONF_SUN_EXPOSURE],
            root_depth_in=float(data[CONF_ROOT_DEPTH_IN]),
            p_table=_optional_float(data, CONF_DEPLETION),
            kc_override=_optional_float(data, CONF_KC_OVERRIDE),
            awc_override=_optional_float(data, CONF_AWC_OVERRIDE),
            et0_mm=et0,
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
        requests: list[ZoneRequest] = []
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ZONE:
                continue
            data = dict(subentry.data)
            state = self.store.zone(subentry.subentry_id)
            limits = self._limits(data, et0)
            pr = resolve_precipitation_rate(
                _optional_float(data, CONF_PRECIPITATION_RATE),
                _optional_float(data, CONF_FLOW_GPM),
                _optional_float(data, CONF_AREA_SQFT),
            )
            zone_wet = _is_wet(self.hass, data.get(CONF_RAIN_SENSOR) or None)
            requests.append(
                ZoneRequest(
                    zone_id=subentry.subentry_id,
                    name=subentry.title,
                    soil_type=data[CONF_SOIL_TYPE],
                    slope_pct=float(data[CONF_SLOPE_PCT]),
                    precipitation_rate_in_hr=pr,
                    efficiency=float(data.get(CONF_EFFICIENCY, DEFAULT_EFFICIENCY)),
                    deficit_mm=float(state["deficit_mm"]),
                    taw_mm=limits.taw_mm,
                    raw_mm=limits.raw_mm,
                    etc_mm=0.0 if limits.etc_mm is None else limits.etc_mm,
                    kc=limits.kc,
                    p=limits.p,
                    enabled=bool(state.get("enabled", True)),
                    rain_sensor_wet=zone_wet,
                    skipped_until=state.get("skipped_until"),
                    priority=int(data.get(CONF_PRIORITY, DEFAULT_PRIORITY)),
                    max_cycle_override_min=(
                        None
                        if data.get(CONF_MAX_CYCLE_MIN) in (None, "")
                        else int(data[CONF_MAX_CYCLE_MIN])
                    ),
                    soak_override_min=(
                        None
                        if data.get(CONF_SOAK_MIN) in (None, "")
                        else int(data[CONF_SOAK_MIN])
                    ),
                )
            )
        skip = _optional_float(options, CONF_FORECAST_SKIP_MM)
        cap = options.get(CONF_MAX_DAILY_RUNTIME_MIN)
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
            )
        )

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
                )
        else:
            for subentry in self.config_entry.subentries.values():
                if subentry.subentry_type != SUBENTRY_ZONE:
                    continue
                state = self.store.zone(subentry.subentry_id)
                try:
                    limits = self._limits(dict(subentry.data), et0)
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
                )
        blocked = plan.block_reason if plan is not None else "No plan yet."
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

    async def _async_observation(self, now: datetime) -> Observation:
        options = self._options()
        entity_id = self.config_entry.data.get(CONF_WEATHER_ENTITY)
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
