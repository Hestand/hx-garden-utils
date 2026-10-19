"""Hourly weather read, evening bucket update, and watering plan.

The coordinator commits one day of ET and measured rain at the plan hour
(or when calculate_plan asks), then builds a plan for the next morning.
Valves open at the start time and finish by the finish time. When automatic
watering is on, the executor runs that plan. Rain from the weather forecast
is not treated as rain that already fell.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field, replace
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
    CONF_AREA_SQFT,
    CONF_AWC_OVERRIDE,
    CONF_BLACKOUT_END_HOUR,
    CONF_BLACKOUT_START_HOUR,
    CONF_BUCKET,
    CONF_DEPLETION,
    CONF_DORMANT_BELOW_F,
    CONF_DRIP_IGNORES_SCHEDULE,
    CONF_EARLIEST_START,
    CONF_EFFICIENCY,
    CONF_ELEVATION_M,
    CONF_FIELD_CAPACITY,
    CONF_FLOW_GPM,
    CONF_FLOW_KIND,
    CONF_FLOW_LEAK_RATIO,
    CONF_FLOW_LOW_RATIO,
    CONF_FLOW_SCOPE,
    CONF_FLOW_SENSOR,
    CONF_FORECAST_DEFER_DAYS,
    CONF_FORECAST_HOURS,
    CONF_FORECAST_PROBABILITY_PCT,
    CONF_FORECAST_SKIP_MM,
    CONF_FREEZE_ALERT,
    CONF_FREEZE_ALERT_F,
    CONF_FREEZE_SKIP_F,
    CONF_HARD_FREEZE_F,
    CONF_HUB_NIGHTLY_CAP_MIN,
    CONF_HEAT_ABOVE_F,
    CONF_HUMIDITY_SENSOR,
    CONF_KC_OVERRIDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MAINTENANCE_WATERING,
    CONF_MAX_DAILY_RUNTIME_MIN,
    CONF_MAX_RUN_MIN,
    CONF_MIN_INTERVAL_DAYS,
    CONF_MODE,
    CONF_MOISTURE_KIND,
    CONF_MOISTURE_LEARN,
    CONF_MOISTURE_MODE,
    CONF_MOISTURE_SENSOR,
    CONF_MOISTURE_SKIP_PCT,
    CONF_MOISTURE_WEIGHT,
    CONF_NOTIFY_TARGET,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRESSURE_SENSOR,
    CONF_RAIN_AMOUNT_SENSOR,
    CONF_RAIN_KIND,
    CONF_RAIN_SENSOR,
    CONF_RECENT_RAIN_HOURS,
    CONF_RECENT_RAIN_MM,
    CONF_ROUND_MINUTES,
    CONF_SCENARIO,
    CONF_SIMULATION,
    CONF_SLOW_BELOW_F,
    CONF_SOIL_TYPE,
    CONF_SOLAR_SENSOR,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_FINISH_TIME,
    CONF_START_TIME,
    CONF_TARGET_DEPTH_IN,
    CONF_TEMPERATURE_SENSOR,
    CONF_UV_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_HEIGHT_M,
    CONF_WIND_SENSOR,
    CONF_WIND_SKIP_MPH,
    CONF_ZONE_MAX_RUN_MIN,
    DEFAULT_ADJUSTMENT_PCT,
    DEFAULT_ELEVATION_M,
    DEFAULT_FLOW_KIND,
    DEFAULT_FLOW_LEAK_RATIO,
    DEFAULT_FLOW_LOW_RATIO,
    CONF_BASELINE_DAYS,
    CONF_BASELINE_MINUTES,
    CONF_COST_PER_1000_GAL,
    CONF_FLOW_HIGH_ACTION,
    CONF_FLOW_HIGH_PCT,
    CONF_FLOW_IDLE_ACTION,
    CONF_FLOW_IDLE_GPM,
    CONF_FLOW_LEARN_RUNS,
    CONF_FLOW_LOW_ACTION,
    CONF_FLOW_LOW_PCT,
    CONF_WEEKLY_BUDGET_GAL,
    CONF_WEEKLY_SUMMARY,
    EVENT_BUDGET_ALERT,
    EVENT_FLOW_ALERT,
    EVENT_FREEZE_ALERT,
    EVENT_WEEKLY_SUMMARY,
    FLOW_ACTION_STOP,
    FLOW_SCOPE_IRRIGATION,
    DEFAULT_FREEZE_SKIP_F,
    DEFAULT_MAX_RUN_MIN,
    DEFAULT_MOISTURE_KIND,
    DEFAULT_MOISTURE_MODE,
    DEFAULT_MOISTURE_WEIGHT,
    DEFAULT_PLAN_HOUR,
    DEFAULT_RAIN_KIND,
    DEFAULT_RECENT_RAIN_HOURS,
    DEFAULT_RECENT_RAIN_MM,
    DEFAULT_ROUND_MINUTES,
    DEFAULT_SPRINKLER_TYPE,
    DEFAULT_EARLIEST_START,
    DEFAULT_FINISH_TIME,
    DEFAULT_START_TIME,
    DEFAULT_WIND_HEIGHT_M,
    DOMAIN,
    MODE_AUTO,
    MODE_NOTIFY_ONLY,
    MODE_OFF,
    MOISTURE_CORRECT,
    MOISTURE_OVERRIDE,
    SUBENTRY_ZONE,
)
from .cycle_soak import plan_cycles
from .dormancy import MAINTENANCE_MM, classify, maintenance_due
from .audit import audit_result
from .et import ETInputs, daily_et0, extraterrestrial_radiation_mj, hargreaves_et0_mm
from .forecast_rain import (
    DEFAULT_FORECAST_DEFER_DAYS,
    DEFAULT_FORECAST_HOURS,
    DEFAULT_FORECAST_PROBABILITY_PCT,
    DEFAULT_FREEZE_ALERT_F,
    DEFAULT_HARD_FREEZE_F,
    defer_days_before_today,
    defer_reason,
    expected_rain,
    freeze_message,
    upcoming_freeze,
    wants_defer,
)
from .executor import CycleJob, WateringExecutor
from .flow import classify_flow, expected_gallons, note_flow
from .flow_learn import (
    DEFAULT_HIGH_PCT,
    DEFAULT_IDLE_GPM,
    DEFAULT_LEARN_RUNS,
    DEFAULT_LOW_PCT,
    accept_sample,
    alert_detail,
    robust_gpm,
    run_status,
)
from .learn import relative_full, should_learn, update_awc_factor
from .moisture import apply_moisture, deficit_from_reading, reading_percent
from .observe import (
    note_rain,
    note_solar_w,
    note_temperature,
    observed_temperature_range,
    rain_between,
    rain_in_hours,
    uv_index_to_w_m2,
)
from .planner import NightPlan, PlanRequest, ZoneRequest, build_plan, build_zone_request, short_status
from .presets import (
    min_interval_days,
    resolved_efficiency,
    resolved_root_depth_in,
    sprinkler_efficiency,
    sprinkler_precip,
    wind_skip_mph,
)
from .safety import would_execute
from .schedule import morning_window, rules_for, shift_minutes
from .skips import SkipInputs, safety_reason
from .week_plan import OUTLOOK_DAYS, project_week, split_outlook
from .store import SmartWaterStore
from .usage import (
    DEFAULT_BASELINE_DAYS,
    DEFAULT_BASELINE_MINUTES,
    add_use,
    baseline_week_gallons,
    cost_of,
    period_gallons,
    saved_gallons,
)
from .units import (
    depth_mm,
    inches_to_mm,
    pressure_kpa,
    rate_gpm,
    solar_parts,
    speed_m_s,
    speed_mph,
    temperature_c,
    temperature_f,
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
    moisture_pct: float | None = None
    moisture_mode: str = "off"
    next_estimated: bool = False
    next_note: str = ""
    flow_status: str = "not_configured"
    flow_delivered_gal: float = 0.0
    flow_expected_gal: float | None = None
    last_run_now: str | None = None
    last_run: dict[str, Any] | None = None
    dormancy: str = "active"
    dormancy_mean_f: float | None = None
    dormancy_detail: str = ""
    learn_factor: float = 1.0
    learn_confidence: float = 0.0
    learned_gpm: float | None = None
    last_run_gpm: float | None = None
    water_total_gal: float = 0.0
    water_today_gal: float = 0.0
    water_week_gal: float = 0.0
    water_month_gal: float = 0.0
    baseline_week_gal: float | None = None
    saved_week_gal: float | None = None
    full_pct: float = 100.0
    bucket_history: list[dict[str, Any]] = field(default_factory=list)
    du_lq: float | None = None
    precip_source: str = "preset"
    preset_precip_in_hr: float | None = None
    preset_efficiency: float | None = None
    measured_precip_in_hr: float | None = None
    measured_efficiency: float | None = None


@dataclass
class HubSnapshot:
    """Coordinator data for hub and zone entities."""

    et0_mm: float | None
    et0_method: str | None
    et0_detail: str | None
    et0_date: str | None
    mode: str
    automatic: bool
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
    schedule_markdown: str = ""
    schedule_days: list[dict[str, Any]] | None = None
    schedule_window: str = ""
    watering_now: str = "Idle"
    alerts: list[str] = field(default_factory=list)
    outlook_summary: str = ""


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
        self.executor: WateringExecutor | None = None
        self._notified_date = store.notified_date
        self._lock = asyncio.Lock()
        self._week: dict[str, Any] | None = None
        self._outlook: dict[str, Any] = {"by_zone": {}, "summary": ""}
        self._last_observation: Observation | None = None
        # A main-leak stop must not run while this lock is held. Credit needs it.
        self._pending_flow_stop = False
        self._forecast_expected_mm = 0.0
        self._forecast_probability: float | None = None
        self._forecast_has_probability = False

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
        return await self._publish(force_balance=False, force_notify=False)

    async def _publish(self, *, force_balance: bool, force_notify: bool) -> HubSnapshot:
        """Rebuild, then start an automatic run when this refresh armed one."""
        snapshot, jobs = await self._async_build(
            force_balance=force_balance, force_notify=force_notify
        )
        if jobs and self.executor is not None:
            await self.executor.start(jobs)
        return snapshot

    async def async_calculate_plan(self, *, notify: bool) -> HubSnapshot:
        """Service entry: commit today's balance if needed, then plan."""
        snapshot = await self._publish(force_balance=True, force_notify=notify)
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
        """Run one zone now. This ignores the automatic switch. It still skips unsafe weather."""
        snapshot = await self._publish(force_balance=False, force_notify=False)
        if zone_id not in snapshot.zones:
            raise HomeAssistantError(f"Unknown Smart Water zone {zone_id}")
        jobs, reason = self._manual_jobs(zone_id)
        if reason or not jobs:
            await self._write_run(
                zone_id, minutes=0, net_mm=0, gallons=None, result=reason or "Nothing to water."
            )
            self.async_set_updated_data(
                await self._publish(force_balance=False, force_notify=False)
            )
            return
        if self.executor is None:
            raise HomeAssistantError("Smart Water executor is not ready.")
        await self.executor.start(jobs)

    async def async_start_audit(self, zone_id: str, minutes: float) -> None:
        """Run one continuous catch-cup test. Safety still applies. The cap does too."""
        if minutes <= 0:
            raise HomeAssistantError("Audit minutes must be greater than 0.")
        subentry = self.config_entry.subentries.get(zone_id)
        if subentry is None:
            raise HomeAssistantError(f"Unknown Smart Water zone {zone_id}")
        reason = self.live_skip(zone_id, True)
        if reason:
            raise HomeAssistantError(reason)
        data = dict(subentry.data)
        entity_id = str(data.get(CONF_VALVE_ENTITY) or "")
        if not entity_id or entity_id.startswith("simulation."):
            raise HomeAssistantError("This zone has no on/off entity.")
        precip = _optional_float(data, CONF_PRECIPITATION_RATE)
        if precip is None:
            precip = sprinkler_precip(str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE))
        if precip is None or precip <= 0:
            raise HomeAssistantError("This zone needs a precipitation rate before an audit.")
        actual = min(float(minutes), self.zone_run_cap(data))
        efficiency = resolved_efficiency(data)
        net_mm = (actual / 60.0) * precip * efficiency * 25.4
        now = dt_util.now(self._timezone())
        state = self.store.zone(zone_id)
        state["audit_pending"] = {"minutes": actual, "started": now.isoformat()}
        await self.store.async_save()
        if self.executor is None:
            raise HomeAssistantError("Smart Water executor is not ready.")
        job = self._cycle_job(
            zone_id=zone_id,
            name=subentry.title,
            data=data,
            start=None,
            minutes=actual,
            net_mm=net_mm,
            zone_net_mm=net_mm,
            precip=precip,
            finish_by=None,
            marked_at=now,
            soak_after_min=0,
            manual=True,
        )
        await self.executor.start([job])

    async def async_submit_audit(
        self,
        zone_id: str,
        readings: list[float],
        *,
        unit: str,
        cup_diameter_in: float | None,
        minutes: float | None,
    ) -> dict[str, Any]:
        """Store the measured rate and DU_lq. Save the store before the reload."""
        subentry = self.config_entry.subentries.get(zone_id)
        if subentry is None:
            raise HomeAssistantError(f"Unknown Smart Water zone {zone_id}")
        state = self.store.zone(zone_id)
        pending = state.get("audit_pending") or {}
        used = minutes if minutes is not None else pending.get("minutes")
        if used in (None, "") or float(used) <= 0:
            raise HomeAssistantError("Run an audit first, or pass how many minutes it ran.")
        try:
            result = audit_result(
                readings,
                minutes=float(used),
                unit=unit,
                cup_diameter_in=cup_diameter_in,
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        preset_sprinkler = str(dict(subentry.data).get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE)
        history = list(state.get("audit_history") or [])
        history.append(
            {
                "at": dt_util.now(self._timezone()).isoformat(),
                "minutes": float(used),
                "readings": list(readings),
                "unit": unit,
                "precipitation_rate_in_hr": result.precipitation_rate_in_hr,
                "du_lq": result.du_lq,
                "scheduling_efficiency": result.scheduling_efficiency,
                "preset_precip_in_hr": sprinkler_precip(preset_sprinkler),
                "preset_efficiency": sprinkler_efficiency(preset_sprinkler),
            }
        )
        state["audit_history"] = history[-12:]
        state["measured_precipitation_rate_in_hr"] = result.precipitation_rate_in_hr
        state["measured_efficiency"] = result.scheduling_efficiency
        state["measured_du_lq"] = result.du_lq
        state["audit_pending"] = None
        await self.store.async_save()
        data = dict(subentry.data)
        data[CONF_PRECIPITATION_RATE] = result.precipitation_rate_in_hr
        data[CONF_EFFICIENCY] = result.scheduling_efficiency
        self.hass.config_entries.async_update_subentry(
            self.config_entry, subentry, data=data
        )
        return {
            "precipitation_rate_in_hr": result.precipitation_rate_in_hr,
            "du_lq": result.du_lq,
            "scheduling_efficiency": result.scheduling_efficiency,
            "average_in": result.average_in,
            "low_quarter_in": result.low_quarter_in,
            "cups": result.cups,
            "minutes": float(used),
        }

    async def async_set_automatic(self, enabled: bool) -> None:
        """Turn automatic watering on or off without writing config options.

        Off stops a run that is already going. On, when the hub mode is off,
        sets the mode to auto, which reloads the entry. The stored flag is
        saved first so the reloaded hub comes back on.
        """
        self.store.automatic = bool(enabled)
        await self.store.async_save()
        if not enabled:
            if self.executor is not None:
                await self.executor.stop()
            self.async_set_updated_data(
                await self._publish(force_balance=False, force_notify=False)
            )
            return
        if str(self._options().get(CONF_MODE, MODE_NOTIFY_ONLY)) == MODE_OFF:
            await self.async_set_mode(MODE_AUTO)
            return
        self.async_set_updated_data(
            await self._publish(force_balance=False, force_notify=False)
        )

    async def async_stop_all(self) -> None:
        """Turn off whatever this hub turned on."""
        if self.executor is not None:
            await self.executor.stop()
        self.async_set_updated_data(
            await self._publish(force_balance=False, force_notify=False)
        )

    async def async_reset_learning(self, zone_id: str) -> None:
        """Return the moisture factor to 1 and clear its confidence."""
        state = self.store.zone(zone_id)
        state["learn_factor"] = 1.0
        state["learn_confidence"] = 0.0
        state["learn_samples"] = 0
        state["learn_date"] = None
        await self._save_and_refresh_snapshot()

    async def async_credit_cycle(
        self,
        *,
        zone_id: str,
        minutes: float,
        net_mm: float,
        gallons: float | None,
        result: str,
        gpm: float | None = None,
    ) -> None:
        """Credit one finished cycle. Called by the executor outside the build lock."""
        alert = None
        async with self._lock:
            alert = self._write_run_locked(
                zone_id,
                minutes=minutes,
                net_mm=net_mm,
                gallons=gallons,
                result=result,
                gpm=gpm,
            )
            await self.store.async_save()
        if alert is not None:
            self._raise_flow_alert(alert)
        self._maybe_budget_alert()
        self.hass.async_create_task(self._refresh_after_cycle())

    async def _refresh_after_cycle(self) -> None:
        snapshot, _jobs = await self._async_build(force_balance=False, force_notify=False)
        self.async_set_updated_data(snapshot)

    def poke_status(self) -> None:
        """Ask entities to re-read the executor without rebuilding the plan."""
        if self.data is not None:
            self.async_set_updated_data(self.data)

    async def async_set_mode(self, mode: str) -> None:
        """Change hub mode. This does not change the dry-run flag."""
        options = self._options()
        options[CONF_MODE] = mode
        self.hass.config_entries.async_update_entry(self.config_entry, options=options)

    async def _save_and_refresh_snapshot(self) -> None:
        self.async_set_updated_data(
            await self._publish(force_balance=False, force_notify=False)
        )

    async def _async_build(
        self, *, force_balance: bool, force_notify: bool
    ) -> tuple[HubSnapshot, list[CycleJob] | None]:
        async with self._lock:
            snapshot, jobs = await self._async_build_locked(
                force_balance=force_balance, force_notify=force_notify
            )
        if self._pending_flow_stop:
            self._pending_flow_stop = False
            jobs = None
            if self.executor is not None:
                self.hass.async_create_task(self.executor.stop())
        return snapshot, jobs

    async def _async_build_locked(
        self, *, force_balance: bool, force_notify: bool
    ) -> tuple[HubSnapshot, list[CycleJob] | None]:
        options = self._options()
        now = dt_util.now(self._timezone())
        today = now.date().isoformat()
        plan_hour = int(options.get(CONF_PLAN_HOUR, DEFAULT_PLAN_HOUR))
        automatic = bool(self.store.automatic)
        mode = str(options.get(CONF_MODE, MODE_NOTIFY_ONLY))
        elevation = float(options.get(CONF_ELEVATION_M, DEFAULT_ELEVATION_M))
        latitude = options.get(CONF_LATITUDE, self.hass.config.latitude)
        longitude = options.get(CONF_LONGITUDE, self.hass.config.longitude)
        latitude_f = None if latitude is None else float(latitude)
        longitude_f = None if longitude is None else float(longitude)
        error: str | None = None

        self._accumulate_day(now, today)
        self._note_temp_history(now, today)
        observation = self._overlay_observed(await self._async_observation(now))
        self._last_observation = observation
        if observation.error:
            error = observation.error
        et_result = daily_et0(observation.inputs) if observation.inputs else None
        et0 = None if et_result is None else et_result.et0_mm
        if et_result is not None and et0 is not None:
            self.store.et0_mm = et0
            self.store.et0_method = et_result.method
            self.store.et0_detail = et_result.detail
            self.store.et0_date = today
            history = [
                item
                for item in self.store.et0_history
                if isinstance(item, dict) and item.get("date") != today
            ]
            history.append({"date": today, "mm": round(float(et0), 3)})
            self.store.et0_history = history[-14:]
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

        pending_learn: list[tuple[str, float, float, float]] = []
        for subentry_id in zone_ids:
            subentry = self.config_entry.subentries[subentry_id]
            state = self.store.zone(subentry_id)
            data = dict(subentry.data)
            try:
                limits = self._limits(data, et0, now.month)
            except (KeyError, ValueError) as err:
                error = f"{subentry.title}: {err}"
                continue
            factor = float(state.get("learn_factor") or 1.0)
            season = classify(
                str(data.get(CONF_PLANT_TYPE, "")),
                self.store.temp_history,
                dormant_below_f=_optional_float(data, CONF_DORMANT_BELOW_F),
                slow_below_f=_optional_float(data, CONF_SLOW_BELOW_F),
                heat_above_f=_optional_float(data, CONF_HEAT_ABOVE_F),
            )
            state["dormancy"] = season.status
            state["dormancy_mean_f"] = season.mean_f
            state["dormancy_detail"] = season.detail
            state["deficit_mm"] = clamp_deficit(
                float(state["deficit_mm"]), limits.taw_mm * factor
            )
            balanced = False
            etc_today = None if limits.etc_mm is None else limits.etc_mm * season.factor
            if (
                et0 is not None
                and etc_today is not None
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
                    limits.taw_mm * factor,
                    etc_mm=etc_today,
                    precip_mm=observation.precip_today_mm,
                    et0_mm=et0,
                )
                state["deficit_mm"] = updated.deficit_mm
                state["balance_date"] = today
                balanced = True
            learned = self._consider_learning(
                state, data, limits, today=now.date(), rain_mm=observation.precip_today_mm
            )
            if learned is not None:
                pending_learn.append((subentry_id, *learned))
            self._apply_moisture(state, data, limits, balanced=balanced, awc_factor=factor)
            self._note_bucket(state, today, limits.taw_mm * factor)
        self._note_hub_flow(now, today)

        plan: NightPlan | None = None
        try:
            plan = self._build_plan(
                now=now,
                et0=et0_for_plan,
                precip_tomorrow_mm=observation.precip_tomorrow_mm,
                automatic=automatic,
                mode=mode,
                observation=observation,
            )
        except (KeyError, ValueError) as err:
            error = str(err)
            _LOGGER.warning("Smart Water could not build a plan: %s", err)

        for zone_id, new_factor, confidence, samples in pending_learn:
            learned_state = self.store.zone(zone_id)
            learned_state["learn_factor"] = new_factor
            learned_state["learn_confidence"] = confidence
            learned_state["learn_samples"] = samples
            learned_state["learn_date"] = today
        jobs: list[CycleJob] | None = None
        if (
            automatic
            and not self.config_entry.data.get(CONF_SIMULATION)
            and plan is not None
            and (now.hour >= plan_hour or force_balance)
            and self.store.armed_date != today
            and would_execute(automatic=True, mode=mode)
        ):
            self.store.armed_date = today
            self.store.plan_marked_at = now.isoformat()
            built = self._jobs_from_plan(plan, now)
            jobs = built or None
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
        if plan is not None:
            self._note_forecast_state(plan, today)
        self._consider_freeze(observation, now)
        self._consider_reports(now)
        await self.store.async_save()
        return (
            self._snapshot(
                et0=self.store.et0_mm,
                method=self.store.et0_method,
                detail=self.store.et0_detail,
                et0_date=self.store.et0_date,
                automatic=automatic,
                mode=mode,
                plan=plan,
                error=error,
                elevation=elevation,
                latitude=latitude_f,
            ),
            jobs,
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
        # Forecast precipitation is not rain that already fell. Only the
        # configured rain sensor fills today's bucket.
        precip = 0.0
        if options.get(CONF_RAIN_AMOUNT_SENSOR):
            precip = float(track["rain_mm"])
            track["precip_source"] = "sensor"
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
            forecast_low_c=observation.forecast_low_c,
            wind_m_s=observation.wind_m_s,
            hourly_wind=observation.hourly_wind,
            hourly_precip=observation.hourly_precip,
            daily_precip=observation.daily_precip,
            forecast_lows=observation.forecast_lows,
            forecast_days=observation.forecast_days,
        )

    def _apply_moisture(
        self,
        state: dict[str, Any],
        data: dict[str, Any],
        limits,
        *,
        balanced: bool,
        awc_factor: float = 1.0,
    ) -> None:
        if not data.get(CONF_MOISTURE_SENSOR):
            state["moisture_deficit_mm"] = None
            state["moisture_pct"] = None
            return
        reading, unit = _state_float(self.hass, data.get(CONF_MOISTURE_SENSOR))
        if reading is None:
            return
        state["moisture_pct"] = reading_percent(reading, unit)
        mode = str(data.get(CONF_MOISTURE_MODE, DEFAULT_MOISTURE_MODE))
        try:
            sensor_mm = deficit_from_reading(
                reading=reading,
                kind=str(data.get(CONF_MOISTURE_KIND, DEFAULT_MOISTURE_KIND)),
                taw_mm=limits.taw_mm * awc_factor,
                zr_m=limits.zr_m,
                field_capacity_vwc=_optional_float(data, CONF_FIELD_CAPACITY),
            )
        except ValueError as err:
            _LOGGER.debug("Moisture reading skipped: %s", err)
            state["moisture_deficit_mm"] = None
            return
        state["moisture_deficit_mm"] = sensor_mm
        if mode in {"", "off"}:
            return
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

    def _note_hub_flow(self, now: datetime, today: str) -> None:
        """Credit the one hub meter to the zone that is actually running.

        A whole-home meter is not checked while every zone is off. House use
        would look like a leak, and this does not try to subtract that use.
        """
        options = self._options()
        entity_id = options.get(CONF_FLOW_SENSOR) or None
        if not entity_id:
            return
        value, unit = _state_float(self.hass, entity_id)
        if value is None:
            return
        kind = str(options.get(CONF_FLOW_KIND, DEFAULT_FLOW_KIND))
        reading = volume_gallons(value, unit) if kind != "rate" else rate_gpm(value, unit)
        running = None
        if self.executor is not None and self.executor.current_zone_id:
            running = self.executor.current_zone_id
        if running and running in self.config_entry.subentries:
            note_flow(
                self.store.zone(running),
                kind=kind,
                gallons=reading,
                at=now,
                today=today,
            )
        if str(options.get(CONF_FLOW_SCOPE) or "") != FLOW_SCOPE_IRRIGATION:
            return
        self._note_idle_hub(
            kind,
            reading,
            today,
            running is not None or bool(self.store.watering_entity),
        )

    def _note_idle_hub(
        self,
        kind: str,
        reading: float,
        today: str,
        running: bool,
    ) -> None:
        """Flag flow while every zone is off. Only an irrigation-only meter."""
        if running:
            if kind != "rate":
                self.store.flow_idle_cursor = reading
            return
        options = self._options()
        idle_gpm = float(options.get(CONF_FLOW_IDLE_GPM, DEFAULT_IDLE_GPM))
        leaking = False
        gpm = None
        if kind == "rate":
            gpm = reading
            leaking = reading >= idle_gpm
        else:
            cursor = self.store.flow_idle_cursor
            if cursor is not None and reading - float(cursor) >= 1.0:
                leaking = True
                gpm = (reading - float(cursor)) / 60.0
            self.store.flow_idle_cursor = reading
        if not leaking or self.store.flow_idle_alert_date == today:
            return
        self.store.flow_idle_alert_date = today
        action = str(options.get(CONF_FLOW_IDLE_ACTION, "notify"))
        if action == FLOW_ACTION_STOP:
            self.store.flow_locked = True
        name = self.config_entry.title
        self._raise_flow_alert(
            {
                "kind": "main_leak",
                "zone_id": None,
                "name": name,
                "gpm": None if gpm is None else round(gpm, 3),
                "learned_gpm": None,
                "action": action,
                "detail": alert_detail("main_leak", name=name, gpm=gpm, learned=None),
            }
        )

    def _learn_gpm(
        self,
        zone_id: str,
        state: dict[str, Any],
        data: dict[str, Any],
        gpm: float,
    ) -> dict[str, Any] | None:
        options = self._options()
        high = float(options.get(CONF_FLOW_HIGH_PCT, DEFAULT_HIGH_PCT))
        low = float(options.get(CONF_FLOW_LOW_PCT, DEFAULT_LOW_PCT))
        minimum = int(options.get(CONF_FLOW_LEARN_RUNS, DEFAULT_LEARN_RUNS))
        samples = [float(value) for value in list(state.get("gpm_samples") or [])]
        status = run_status(
            gpm, samples, high_pct=high, low_pct=low, minimum_runs=minimum
        )
        learned_before = robust_gpm(samples)
        state["gpm_samples"] = accept_sample(samples, gpm, minimum_runs=minimum)
        learned_now = robust_gpm(list(state["gpm_samples"]))
        state["learned_gpm"] = (
            learned_now if len(state["gpm_samples"]) >= minimum else None
        )
        state["last_run_gpm"] = round(gpm, 3)
        if status not in {"high_flow", "low_flow"}:
            if status == "ok":
                state["flow_alert"] = None
            return None
        action_key = CONF_FLOW_HIGH_ACTION if status == "high_flow" else CONF_FLOW_LOW_ACTION
        action = str(options.get(action_key, "notify"))
        subentry = self.config_entry.subentries.get(zone_id)
        name = subentry.title if subentry is not None else zone_id
        state["flow_alert"] = status
        if action == FLOW_ACTION_STOP:
            state["flow_locked"] = True
        _ = data
        return {
            "kind": status,
            "zone_id": zone_id,
            "name": name,
            "gpm": round(gpm, 3),
            "learned_gpm": None if learned_before is None else round(learned_before, 3),
            "action": action,
            "detail": alert_detail(status, name=name, gpm=gpm, learned=learned_before),
        }

    def _raise_flow_alert(self, alert: dict[str, Any]) -> None:
        """Repair, event, and optional notify. Stop-and-skip is stored on the zone."""
        from homeassistant.helpers import issue_registry as ir

        self.hass.bus.async_fire(
            EVENT_FLOW_ALERT,
            {
                "hub": self.config_entry.title,
                "kind": alert["kind"],
                "zone": alert.get("name"),
                "zone_id": alert.get("zone_id"),
                "gpm": alert.get("gpm"),
                "learned_gpm": alert.get("learned_gpm"),
                "action": alert.get("action"),
                "detail": alert["detail"],
            },
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"flow_{alert.get('zone_id') or 'hub'}_{alert['kind']}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="flow_alert",
            translation_placeholders={
                "name": str(alert.get("name") or "Smart Water"),
                "detail": str(alert["detail"]),
            },
        )
        title = str(alert["kind"]).replace("_", " ")
        self.hass.async_create_task(self._notify(f"Smart Water {title}", str(alert["detail"])))
        if alert.get("kind") == "main_leak" and alert.get("action") == FLOW_ACTION_STOP:
            # Stopping from inside the build lock deadlocks with cycle credit.
            if self._lock.locked():
                self._pending_flow_stop = True
            elif self.executor is not None:
                self.hass.async_create_task(self.executor.stop())

    async def _notify(self, title: str, message: str) -> None:
        target = str(self._options().get(CONF_NOTIFY_TARGET) or "").strip()
        if not target:
            return
        if "." in target:
            domain, service = target.split(".", 1)
        else:
            domain, service = "notify", target
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {"title": title, "message": message},
                blocking=False,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Smart Water could not notify %s: %s", target, err)

    def _maybe_budget_alert(self) -> None:
        options = self._options()
        budget = _optional_float(options, CONF_WEEKLY_BUDGET_GAL)
        if budget is None or budget <= 0:
            return
        today = dt_util.now(self._timezone()).date()
        week = _iso_week(today)
        if self.store.budget_alert_week == week:
            return
        used = 0.0
        for state in self.store.zones.values():
            used += period_gallons(state.get("water_days"), today, span="week")
        if used <= budget:
            return
        self.store.budget_alert_week = week
        detail = (
            f"This week used {used:.0f} gal. The weekly budget is {budget:.0f} gal."
        )
        self.hass.bus.async_fire(
            EVENT_BUDGET_ALERT,
            {
                "hub": self.config_entry.title,
                "gallons": round(used, 1),
                "budget_gal": budget,
                "detail": detail,
            },
        )
        self.hass.async_create_task(self._notify("Smart Water weekly budget", detail))

    def _consider_reports(self, now: datetime) -> None:
        """Weekly summary, once, on Monday at or after the plan hour."""
        self._maybe_budget_alert()
        options = self._options()
        if not bool(options.get(CONF_WEEKLY_SUMMARY, False)):
            return
        if now.weekday() != 0:
            return
        plan_hour = int(options.get(CONF_PLAN_HOUR, DEFAULT_PLAN_HOUR))
        if now.hour < plan_hour:
            return
        week = _iso_week(now.date())
        if self.store.summary_sent_week == week:
            return
        self.store.summary_sent_week = week
        today = now.date()
        rows = []
        total = 0.0
        saved = 0.0
        have_saved = False
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ZONE:
                continue
            state = self.store.zone(subentry.subentry_id)
            week_gal = period_gallons(state.get("water_days"), today, span="week")
            total += week_gal
            base = self._baseline_for(dict(subentry.data), state)
            zone_saved = saved_gallons(base, week_gal)
            if zone_saved is not None:
                have_saved = True
                saved += zone_saved
            rows.append(f"{subentry.title}: {week_gal:.0f} gal")
        text = "Weekly water use. " + "; ".join(rows)
        if have_saved:
            text += f". About {saved:.0f} gal compared with the fixed-timer baseline."
        text += f" Hub total {total:.0f} gal."
        self.hass.bus.async_fire(
            EVENT_WEEKLY_SUMMARY,
            {
                "hub": self.config_entry.title,
                "gallons": round(total, 1),
                "saved_gal": round(saved, 1) if have_saved else None,
                "detail": text,
            },
        )
        self.hass.async_create_task(self._notify("Smart Water week", text))

    def _baseline_for(self, data: dict[str, Any], state: dict[str, Any]) -> float | None:
        minutes = _optional_float(data, CONF_BASELINE_MINUTES)
        days = _optional_float(data, CONF_BASELINE_DAYS)
        if minutes is None:
            minutes = DEFAULT_BASELINE_MINUTES
        if days is None:
            days = float(DEFAULT_BASELINE_DAYS)
        from .presets import sprinkler_precip

        precip = _optional_float(data, CONF_PRECIPITATION_RATE)
        if precip is None:
            precip = sprinkler_precip(str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE))
        return baseline_week_gallons(
            minutes=minutes,
            days_per_week=days,
            precipitation_rate_in_hr=precip,
            area_sqft=_optional_float(data, CONF_AREA_SQFT),
            flow_gpm=_volume_gpm(state, data),
        )

    async def async_reset_flow(self, zone_id: str | None) -> None:
        """Clear learned flow, the alert, and the skip that a stop action set."""
        from homeassistant.helpers import issue_registry as ir

        ids = [zone_id] if zone_id else list(self.store.zones)
        for item in ids:
            state = self.store.zone(item)
            state["gpm_samples"] = []
            state["learned_gpm"] = None
            state["last_run_gpm"] = None
            state["flow_alert"] = None
            state["flow_locked"] = False
            for kind in ("high_flow", "low_flow", "main_leak"):
                ir.async_delete_issue(self.hass, DOMAIN, f"flow_{item}_{kind}")
        if zone_id is None:
            self.store.flow_locked = False
        else:
            self.store.flow_locked = any(
                bool(self.store.zone(item).get("flow_locked")) for item in self.store.zones
            )
        await self.store.async_save()
        self.async_set_updated_data(
            await self._publish(force_balance=False, force_notify=False)
        )

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
        precip_tomorrow_mm: float,
        automatic: bool,
        mode: str,
        observation: Observation,
    ) -> NightPlan:
        options = self._options()
        earliest, start_at, finish_by = morning_window(
            now,
            options.get(CONF_EARLIEST_START, DEFAULT_EARLIEST_START),
            options.get(CONF_START_TIME, DEFAULT_START_TIME),
            options.get(CONF_FINISH_TIME, DEFAULT_FINISH_TIME),
        )
        hub_wet = _is_wet(self.hass, options.get(CONF_RAIN_SENSOR) or None)
        self._remember_forecast(observation, now)
        requests = []
        areas: dict[str, float | None] = {}
        drip_ignores = bool(options.get(CONF_DRIP_IGNORES_SCHEDULE, False))
        temp_f, forecast_low_f, wind = self._weather_facts(observation)
        recent_hours = int(options.get(CONF_RECENT_RAIN_HOURS, DEFAULT_RECENT_RAIN_HOURS))
        recent_mm = rain_in_hours(self.store.weather, recent_hours, now)
        recent_limit = float(options.get(CONF_RECENT_RAIN_MM, DEFAULT_RECENT_RAIN_MM))
        freeze_default = float(options.get(CONF_FREEZE_SKIP_F, DEFAULT_FREEZE_SKIP_F))
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ZONE:
                continue
            data = dict(subentry.data)
            state = self.store.zone(subentry.subentry_id)
            areas[subentry.subentry_id] = _optional_float(data, CONF_AREA_SQFT)
            requests.append(
                self._zone_request(
                    zone_id=subentry.subentry_id,
                    name=subentry.title,
                    data=data,
                    state=state,
                    et0=et0,
                    month=now.month,
                    now=now,
                    temp_f=temp_f,
                    forecast_low_f=forecast_low_f,
                    wind_mph=wind,
                    recent_mm=recent_mm,
                    recent_hours=recent_hours,
                    recent_limit=recent_limit,
                    freeze_default=freeze_default,
                    drip_ignores=drip_ignores,
                    hub_wet=hub_wet,
                )
            )
        skip = _optional_float(options, CONF_FORECAST_SKIP_MM)
        legacy_precip = 0.0 if self._forecast_has_probability else precip_tomorrow_mm
        cap = options.get(CONF_MAX_DAILY_RUNTIME_MIN)
        schedule = rules_for(
            options.get(CONF_ALLOWED_WEEKDAYS),
            _optional_int(options, CONF_BLACKOUT_START_HOUR),
            _optional_int(options, CONF_BLACKOUT_END_HOUR),
        )
        plan = build_plan(
            PlanRequest(
                zones=tuple(requests),
                start_at=start_at,
                finish_by=finish_by,
                earliest_start=earliest,
                forecast_precip_mm=legacy_precip,
                forecast_skip_mm=skip,
                hub_rain_wet=hub_wet,
                mode=mode,
                automatic=automatic,
                max_daily_runtime_min=None if cap in (None, "") else int(cap),
                allowed_weekdays=schedule.allowed_weekdays,
                blackout_start_hour=schedule.blackout_start,
                blackout_end_hour=schedule.blackout_end,
                whole_minutes=bool(options.get(CONF_ROUND_MINUTES, DEFAULT_ROUND_MINUTES)),
                max_run_min=self.hub_nightly_cap(),
                hourly_wind=tuple(observation.hourly_wind),
            )
        )
        try:
            full = project_week(
                tuple(requests),
                now=now,
                timezone=self._timezone().key,
                earliest_start=str(
                    options.get(CONF_EARLIEST_START, DEFAULT_EARLIEST_START)
                ),
                start_time=str(options.get(CONF_START_TIME, DEFAULT_START_TIME)),
                finish_time=str(options.get(CONF_FINISH_TIME, DEFAULT_FINISH_TIME)),
                forecast_precip_mm=legacy_precip,
                forecast_skip_mm=skip,
                hub_rain_wet=hub_wet,
                mode=mode,
                automatic=automatic,
                allowed_weekdays=schedule.allowed_weekdays,
                blackout_start_hour=schedule.blackout_start,
                blackout_end_hour=schedule.blackout_end,
                whole_minutes=bool(options.get(CONF_ROUND_MINUTES, DEFAULT_ROUND_MINUTES)),
                max_daily_runtime_min=None if cap in (None, "") else int(cap),
                areas=areas,
                max_run_min=self.hub_nightly_cap(),
                hourly_wind=tuple(observation.hourly_wind),
                forecast_expected_mm=self._forecast_expected_mm,
                forecast_probability_pct=(
                    self._forecast_probability
                    if self._forecast_has_probability
                    else None
                ),
                forecast_probability_min=self._forecast_probability_min(),
                forecast_defer_max=self._forecast_defer_max(),
                forecast_horizon_days=self._forecast_horizon_days(),
                forecast_threshold_mm=skip,
                defer_days=self._defer_days_before(now),
                days=OUTLOOK_DAYS,
                et_factors=self._et_factors(observation, now.date(), et0),
            )
            self._week, self._outlook = split_outlook(
                full, timezone=self._timezone().key
            )
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Smart Water could not project a week: %s", err)
        return plan

    def lifetime_cost(self) -> float | None:
        """Dollars for the hub's lifetime gallons, or None when no price is set."""
        price = _optional_float(self._options(), CONF_COST_PER_1000_GAL)
        if price is None or self.data is None:
            return None
        gallons = sum(zone.water_total_gal for zone in self.data.zones.values())
        return cost_of(gallons, price)

    def zone_run_cap(self, data: dict[str, Any]) -> float:
        """Valve-on minutes for this zone tonight. A blank zone uses the hub default."""
        override = _optional_float(data, CONF_MAX_RUN_MIN)
        if override is not None:
            return override
        value = self._options().get(CONF_ZONE_MAX_RUN_MIN, DEFAULT_MAX_RUN_MIN)
        if value in (None, ""):
            return float(DEFAULT_MAX_RUN_MIN)
        return float(value)

    def hub_nightly_cap(self) -> float | None:
        """Optional valve-on total for every zone together. Blank means off."""
        return _optional_float(self._options(), CONF_HUB_NIGHTLY_CAP_MIN)

    def _forecast_probability_min(self) -> float:
        value = self._options().get(
            CONF_FORECAST_PROBABILITY_PCT, DEFAULT_FORECAST_PROBABILITY_PCT
        )
        if value in (None, ""):
            return float(DEFAULT_FORECAST_PROBABILITY_PCT)
        return float(value)

    def _forecast_defer_max(self) -> int:
        value = self._options().get(CONF_FORECAST_DEFER_DAYS, DEFAULT_FORECAST_DEFER_DAYS)
        if value in (None, ""):
            return int(DEFAULT_FORECAST_DEFER_DAYS)
        return int(value)

    def _forecast_hours(self) -> float:
        value = self._options().get(CONF_FORECAST_HOURS, DEFAULT_FORECAST_HOURS)
        if value in (None, ""):
            return float(DEFAULT_FORECAST_HOURS)
        return float(value)

    def _forecast_horizon_days(self) -> int:
        return max(1, math.ceil(self._forecast_hours() / 24.0))

    def _remember_forecast(self, observation: Observation, now: datetime) -> None:
        """Store confident expected rain. Forecast depth is never a bucket credit."""
        self._forecast_has_probability = any(
            probability is not None
            for _stamp, _depth, probability in (
                *observation.hourly_precip,
                *observation.daily_precip,
            )
        )
        hours = self._forecast_hours()
        minimum = self._forecast_probability_min()
        hourly = expected_rain(
            observation.hourly_precip, now=now, hours=hours, probability_min=minimum
        )
        chosen = hourly if hourly.slots else expected_rain(
            observation.daily_precip, now=now, hours=hours, probability_min=minimum
        )
        self._forecast_expected_mm = chosen.expected_mm
        if not self._forecast_has_probability:
            self._forecast_probability = None
        elif chosen.slots:
            self._forecast_probability = chosen.probability_pct
        else:
            self._forecast_probability = 0.0

    def _defer_days_before(self, now: datetime) -> dict[str, int]:
        today = now.date().isoformat()
        days: dict[str, int] = {}
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ZONE:
                continue
            state = self.store.zone(subentry.subentry_id)
            days[subentry.subentry_id] = defer_days_before_today(
                int(state.get("forecast_defer_days") or 0),
                state.get("forecast_defer_last"),
                today,
            )
        return days

    def _defer_reason_for(
        self, state: dict[str, Any], deficit_mm: float, now: datetime
    ) -> str | None:
        if not self._forecast_has_probability:
            return None
        used = defer_days_before_today(
            int(state.get("forecast_defer_days") or 0),
            state.get("forecast_defer_last"),
            now.date().isoformat(),
        )
        return defer_reason(
            expected_mm=self._forecast_expected_mm,
            probability_pct=self._forecast_probability,
            probability_min=self._forecast_probability_min(),
            deficit_mm=deficit_mm,
            threshold_mm=_optional_float(self._options(), CONF_FORECAST_SKIP_MM),
            days_used=used,
            max_days=self._forecast_defer_max(),
        )

    def _note_forecast_state(self, plan: NightPlan, today: str) -> None:
        """Count one deferral per morning, and clear it when the forecast gives up."""
        threshold = _optional_float(self._options(), CONF_FORECAST_SKIP_MM)
        minimum = self._forecast_probability_min()
        for zone_plan in plan.zones:
            state = self.store.zone(zone_plan.zone_id)
            reason = zone_plan.reason or ""
            if reason.startswith("Deferred for forecast rain"):
                if state.get("forecast_defer_last") != today:
                    state["forecast_defer_days"] = int(state.get("forecast_defer_days") or 0) + 1
                    state["forecast_defer_last"] = today
                continue
            still = wants_defer(
                expected_mm=self._forecast_expected_mm,
                probability_pct=self._forecast_probability,
                probability_min=minimum,
                deficit_mm=float(state.get("deficit_mm") or 0.0),
                threshold_mm=threshold,
            )
            if zone_plan.scheduled or not still:
                state["forecast_defer_days"] = 0
                state["forecast_defer_last"] = None

    def _note_bucket(self, state: dict[str, Any], today: str, taw_mm: float) -> None:
        """One soil-full sample per date, for the card's week chart."""
        deficit = float(state.get("deficit_mm") or 0.0)
        if taw_mm <= 0:
            full = 100.0
        else:
            full = max(0.0, min(100.0, (1.0 - deficit / taw_mm) * 100.0))
        history = [dict(item) for item in list(state.get("bucket_history") or [])]
        sample = {"date": today, "full_pct": round(full, 1)}
        if history and history[-1].get("date") == today:
            history[-1] = sample
        else:
            history.append(sample)
        state["bucket_history"] = history[-14:]

    def _bucket_fields(
        self, state: dict[str, Any], data: dict[str, Any], *, taw_mm: float
    ) -> dict[str, Any]:
        deficit = float(state.get("deficit_mm") or 0.0)
        if taw_mm <= 0:
            full = 100.0
        else:
            full = max(0.0, min(100.0, (1.0 - deficit / taw_mm) * 100.0))
        sprinkler = str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE)
        measured_rate = state.get("measured_precipitation_rate_in_hr")
        if measured_rate not in (None, ""):
            source = "measured"
        elif (
            _optional_float(data, CONF_PRECIPITATION_RATE) is not None
            or _optional_float(data, CONF_EFFICIENCY) is not None
        ):
            source = "override"
        else:
            source = "preset"
        history = list(state.get("bucket_history") or [])[-7:]
        return {
            "full_pct": round(full, 1),
            "bucket_history": history,
            "du_lq": state.get("measured_du_lq"),
            "precip_source": source,
            "preset_precip_in_hr": sprinkler_precip(sprinkler),
            "preset_efficiency": sprinkler_efficiency(sprinkler),
            "measured_precip_in_hr": measured_rate,
            "measured_efficiency": state.get("measured_efficiency"),
        }

    def _alert_lines(self) -> list[str]:
        lines: list[str] = []
        if self.store.freeze_alert_detail:
            lines.append(str(self.store.freeze_alert_detail))
        for subentry in self.config_entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_ZONE:
                continue
            alert = self.store.zone(subentry.subentry_id).get("flow_alert")
            if alert:
                lines.append(f"{subentry.title}: {str(alert).replace('_', ' ')}")
        return lines

    def _consider_freeze(self, observation: Observation, now: datetime) -> None:
        """One winterize notice per cold snap. This does not change the 40°F skip."""
        from homeassistant.helpers import issue_registry as ir

        options = self._options()
        if not bool(options.get(CONF_FREEZE_ALERT, True)):
            return
        outlook = upcoming_freeze(
            observation.forecast_lows,
            now=now,
            hours=self._forecast_hours(),
            freeze_f=float(options.get(CONF_FREEZE_ALERT_F, DEFAULT_FREEZE_ALERT_F)),
            hard_f=float(options.get(CONF_HARD_FREEZE_F, DEFAULT_HARD_FREEZE_F)),
        )
        if outlook is None:
            if self.store.freeze_alert_key:
                self.store.freeze_alert_key = None
                self.store.freeze_alert_detail = None
                ir.async_delete_issue(self.hass, DOMAIN, "freeze_alert")
                ir.async_delete_issue(self.hass, DOMAIN, "hard_freeze_alert")
            return
        key = outlook.when.date().isoformat()
        if self.store.freeze_alert_key == key:
            return
        message = freeze_message(outlook)
        self.store.freeze_alert_key = key
        self.store.freeze_alert_detail = message
        issue_key = "hard_freeze_alert" if outlook.hard else "freeze_alert"
        other = "freeze_alert" if outlook.hard else "hard_freeze_alert"
        ir.async_delete_issue(self.hass, DOMAIN, other)
        self.hass.bus.async_fire(
            EVENT_FREEZE_ALERT,
            {
                "hub": self.config_entry.title,
                "low_f": outlook.low_f,
                "hard": outlook.hard,
                "when": outlook.when.isoformat(),
                "detail": message,
            },
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_key,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=issue_key,
            translation_placeholders={"detail": message},
        )
        self.hass.async_create_task(self._notify("Smart Water freeze", message))

    def max_run_minutes(self) -> float:
        """Per-zone default. Kept so older callers still see a number."""
        value = self._options().get(CONF_ZONE_MAX_RUN_MIN, DEFAULT_MAX_RUN_MIN)
        if value in (None, ""):
            return float(DEFAULT_MAX_RUN_MIN)
        return float(value)

    def rain_since_mark(self, marked: datetime) -> float:
        """Measured rain since a plan or a manual run was armed."""
        until = dt_util.now(marked.tzinfo)
        return rain_between(self.store.weather, marked, until)

    def live_skip(self, zone_id: str, manual: bool) -> str | None:
        """Re-check safety immediately before a cycle. Manual runs skip the schedule."""
        subentry = self.config_entry.subentries.get(zone_id)
        if subentry is None:
            return "Zone was removed."
        data = dict(subentry.data)
        state = self.store.zone(zone_id)
        if state.get("flow_locked") or self.store.flow_locked:
            return "Skipped because a flow alert is waiting for reset."
        options = self._options()
        now = dt_util.now(self._timezone())
        hours = int(options.get(CONF_RECENT_RAIN_HOURS, DEFAULT_RECENT_RAIN_HOURS))
        temp_f, forecast_low_f, wind = self._weather_facts(self._last_observation)
        freeze = _optional_float(data, CONF_FREEZE_SKIP_F)
        if freeze is None:
            freeze = float(options.get(CONF_FREEZE_SKIP_F, DEFAULT_FREEZE_SKIP_F))
        wind_limit = _optional_float(data, CONF_WIND_SKIP_MPH)
        if wind_limit is None:
            wind_limit = wind_skip_mph(
                str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE)
            )
        reason = safety_reason(
            SkipInputs(
                hub_rain_wet=_is_wet(self.hass, options.get(CONF_RAIN_SENSOR) or None),
                rain_sensor_wet=_is_wet(self.hass, data.get(CONF_RAIN_SENSOR) or None),
                currently_raining=_is_wet(self.hass, options.get(CONF_RAIN_SENSOR) or None),
                recent_rain_mm=rain_in_hours(self.store.weather, hours, now),
                recent_rain_skip_mm=float(
                    options.get(CONF_RECENT_RAIN_MM, DEFAULT_RECENT_RAIN_MM)
                ),
                recent_rain_hours=hours,
                temp_f=temp_f,
                forecast_low_f=forecast_low_f,
                freeze_f=freeze,
                wind_mph=wind,
                wind_limit_mph=wind_limit,
                moisture_full=self._moisture_full(data),
                moisture_skip_full=self._moisture_skip_full(data, now.month),
            )
        )
        if reason or manual:
            return reason
        if not bool(state.get("enabled", True)):
            return "Zone is disabled."
        skipped = state.get("skipped_until")
        if skipped and str(skipped) >= now.date().isoformat():
            return f"Skipped until {skipped}."
        return None

    def _jobs_from_plan(self, plan: NightPlan, now: datetime) -> list[CycleJob]:
        """Timeline cycles, in order, skipping virtual simulation entities."""
        zones = {zone.zone_id: zone for zone in plan.zones}
        jobs: list[CycleJob] = []
        for event in plan.timeline:
            zone = zones.get(event.zone_id)
            subentry = self.config_entry.subentries.get(event.zone_id)
            if zone is None or subentry is None or not zone.runtime_min:
                continue
            data = dict(subentry.data)
            entity_id = str(data.get(CONF_VALVE_ENTITY) or "")
            if not entity_id or entity_id.startswith("simulation."):
                continue
            share = float(event.duration_min) / float(zone.runtime_min)
            jobs.append(
                self._cycle_job(
                    zone_id=event.zone_id,
                    name=event.zone_name,
                    data=data,
                    start=event.start,
                    minutes=float(event.duration_min),
                    net_mm=zone.net_mm * share,
                    zone_net_mm=zone.net_mm,
                    precip=zone.precipitation_rate_in_hr,
                    finish_by=plan.finish_by,
                    marked_at=now,
                    soak_after_min=0,
                    manual=False,
                )
            )
        return jobs

    def _manual_jobs(self, zone_id: str) -> tuple[list[CycleJob], str | None]:
        """Cycle-and-soak for a manual run. Schedule rules are not applied."""
        subentry = self.config_entry.subentries.get(zone_id)
        if subentry is None:
            return [], "Unknown zone."
        reason = self.live_skip(zone_id, True)
        if reason:
            return [], reason
        data = dict(subentry.data)
        entity_id = str(data.get(CONF_VALVE_ENTITY) or "")
        if not entity_id or entity_id.startswith("simulation."):
            return [], "This zone has no on/off entity."
        state = self.store.zone(zone_id)
        adjusted = float(state["deficit_mm"]) * float(
            state.get("adjustment_pct", DEFAULT_ADJUSTMENT_PCT)
        ) / 100.0
        if adjusted <= 0:
            return [], "Soil is at field capacity."
        try:
            limits = self._limits(data, self.store.et0_mm, dt_util.now().month)
        except (KeyError, ValueError) as err:
            return [], str(err)
        sprinkler = str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE)
        try:
            request = build_zone_request(
                zone_id=zone_id,
                name=subentry.title,
                data=data,
                deficit_mm=adjusted,
                et0_mm=self.store.et0_mm,
                month=dt_util.now().month,
            )
        except (KeyError, ValueError) as err:
            return [], str(err)
        cycles = plan_cycles(
            net_mm=adjusted,
            precipitation_rate_in_hr=request.precipitation_rate_in_hr,
            efficiency=request.efficiency,
            soil_type=request.soil_type,
            slope_pct=request.slope_pct,
            max_cycle_override_min=request.max_cycle_override_min,
            soak_override_min=request.soak_override_min,
            whole_minutes=bool(self._options().get(CONF_ROUND_MINUTES, DEFAULT_ROUND_MINUTES)),
            sprinkler_type=sprinkler,
            intake_override_in_hr=request.intake_override_in_hr,
        )
        if not cycles.cycles_min:
            return [], "Runtime rounds to 0 minutes."
        now = dt_util.now(self._timezone())
        total = float(sum(cycles.cycles_min))
        jobs = []
        for index, minutes in enumerate(cycles.cycles_min):
            share = float(minutes) / total if total else 0.0
            jobs.append(
                self._cycle_job(
                    zone_id=zone_id,
                    name=subentry.title,
                    data=data,
                    start=None,
                    minutes=float(minutes),
                    net_mm=cycles.net_mm * share,
                    zone_net_mm=cycles.net_mm,
                    precip=request.precipitation_rate_in_hr,
                    finish_by=None,
                    marked_at=now,
                    soak_after_min=cycles.soak_min if index < len(cycles.cycles_min) - 1 else 0,
                    manual=True,
                )
            )
        _ = limits
        return jobs, None

    def _cycle_job(
        self,
        *,
        zone_id: str,
        name: str,
        data: dict[str, Any],
        start: datetime | None,
        minutes: float,
        net_mm: float,
        zone_net_mm: float,
        precip: float,
        finish_by: datetime | None,
        marked_at: datetime,
        soak_after_min: float,
        manual: bool,
    ) -> CycleJob:
        return CycleJob(
            zone_id=zone_id,
            name=name,
            entity_id=str(data.get(CONF_VALVE_ENTITY) or ""),
            start=start,
            minutes=minutes,
            net_mm=net_mm,
            zone_net_mm=zone_net_mm,
            precip_in_hr=precip,
            efficiency=resolved_efficiency(data),
            area_sqft=_optional_float(data, CONF_AREA_SQFT),
            flow_entity=self._options().get(CONF_FLOW_SENSOR) or None,
            flow_kind=str(self._options().get(CONF_FLOW_KIND) or "") or None,
            finish_by=finish_by,
            marked_at=marked_at,
            soak_after_min=soak_after_min,
            manual=manual,
            zone_cap_min=self.zone_run_cap(data),
        )

    async def _write_run(
        self,
        zone_id: str,
        *,
        minutes: float,
        net_mm: float,
        gallons: float | None,
        result: str,
    ) -> None:
        async with self._lock:
            self._write_run_locked(
                zone_id, minutes=minutes, net_mm=net_mm, gallons=gallons, result=result
            )
            await self.store.async_save()

    def _write_run_locked(
        self,
        zone_id: str,
        *,
        minutes: float,
        net_mm: float,
        gallons: float | None,
        result: str,
        gpm: float | None = None,
    ) -> dict[str, Any] | None:
        state = self.store.zone(zone_id)
        subentry = self.config_entry.subentries.get(zone_id)
        data = dict(subentry.data) if subentry is not None else {}
        applied = gallons
        if applied is None and result == "ok" and minutes > 0:
            from .presets import sprinkler_precip

            precip = _optional_float(data, CONF_PRECIPITATION_RATE)
            if precip is None:
                precip = sprinkler_precip(
                    str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE)
                )
            applied = expected_gallons(
                runtime_min=minutes,
                precipitation_rate_in_hr=precip,
                area_sqft=_optional_float(data, CONF_AREA_SQFT),
                flow_gpm=_volume_gpm(state, data),
            )
        if result == "ok" and net_mm > 0:
            state["deficit_mm"] = max(0.0, float(state["deficit_mm"]) - net_mm)
            state["last_watered"] = dt_util.now(self._timezone()).date().isoformat()
        today = dt_util.now(self._timezone()).date().isoformat()
        if applied is not None and applied > 0 and result == "ok":
            state["water_days"] = add_use(state.get("water_days"), today, applied)
            state["water_total_gal"] = round(
                float(state.get("water_total_gal") or 0.0) + applied, 3
            )
        alert = None
        if gpm is not None and gpm > 0 and result == "ok":
            alert = self._learn_gpm(zone_id, state, data, gpm)
        state["last_run"] = {
            "at": dt_util.now(self._timezone()).isoformat(),
            "minutes": round(minutes, 2),
            "net_mm": round(net_mm, 2),
            "gallons": None if applied is None else round(applied, 2),
            "gpm": None if gpm is None else round(gpm, 3),
            "result": result,
        }
        state["last_run_now"] = f"{result}: {minutes:.0f} min, {net_mm:.1f} mm"
        return alert

    def _note_temp_history(self, now: datetime, today: str) -> None:
        """Store one daily mean Fahrenheit for the dormancy window."""
        track = self.store.weather
        high = track.get("t_max_c")
        low = track.get("t_min_c")
        if high is not None and low is not None:
            mean_c = (float(high) + float(low)) / 2.0
        else:
            temp_c = self._current_temp_c()
            if temp_c is None:
                return
            mean_c = temp_c
        history = [row for row in self.store.temp_history if row.get("date") != today]
        history.append({"date": today, "mean_f": temperature_f(mean_c)})
        self.store.temp_history = history[-14:]
        _ = now

    def _current_temp_c(self) -> float | None:
        options = self._options()
        sensor, unit = _state_float(self.hass, options.get(CONF_TEMPERATURE_SENSOR))
        if sensor is not None:
            return temperature_c(sensor, unit)
        entity_id = self.config_entry.data.get(CONF_WEATHER_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.attributes.get("temperature") is None:
            return None
        return temperature_c(
            float(state.attributes["temperature"]),
            state.attributes.get("temperature_unit"),
        )

    def _weather_facts(
        self, observation: Observation | None
    ) -> tuple[float | None, float | None, float | None]:
        temp_c = self._current_temp_c()
        temp_f = None if temp_c is None else temperature_f(temp_c)
        low = None if observation is None else observation.forecast_low_c
        low_f = None if low is None else temperature_f(low)
        wind = None
        if observation is not None and observation.wind_m_s is not None:
            wind = speed_mph(observation.wind_m_s)
        return temp_f, low_f, wind

    def _moisture_full(self, data: dict[str, Any]) -> float | None:
        if not data.get(CONF_MOISTURE_SENSOR):
            return None
        reading, _unit = _state_float(self.hass, data.get(CONF_MOISTURE_SENSOR))
        if reading is None:
            return None
        kind = str(data.get(CONF_MOISTURE_KIND, DEFAULT_MOISTURE_KIND))
        if kind != "relative":
            capacity = _optional_float(data, CONF_FIELD_CAPACITY)
            if not capacity:
                return None
            return min(1.0, max(0.0, reading / capacity))
        return relative_full(reading)

    def _moisture_skip_full(self, data: dict[str, Any], month: int) -> float | None:
        override = _optional_float(data, CONF_MOISTURE_SKIP_PCT)
        if override is not None:
            return override / 100.0 if override > 1 else override
        try:
            limits = self._limits(data, self.store.et0_mm, month)
        except (KeyError, ValueError):
            return None
        return 1.0 - limits.p

    def _days_since(self, state: dict[str, Any], today: date) -> int | None:
        last = state.get("last_watered")
        if not last:
            return None
        return (today - date.fromisoformat(str(last)[:10])).days

    def _consider_learning(
        self,
        state: dict[str, Any],
        data: dict[str, Any],
        limits: Any,
        *,
        today: date,
        rain_mm: float,
    ) -> tuple[float, float, int] | None:
        """Compare sensor and model. The caller stores the result after the plan."""
        if state.get("learn_date") == today.isoformat():
            return None
        enabled = data.get(CONF_MOISTURE_LEARN)
        if enabled is None or enabled == "":
            enabled = True
        full = self._moisture_full(data)
        if not should_learn(
            enabled=bool(enabled),
            has_sensor=full is not None,
            rain_today_mm=rain_mm,
            last_watered=state.get("last_watered"),
            today=today,
        ):
            return None
        assert full is not None
        return update_awc_factor(
            float(state.get("learn_factor") or 1.0),
            full,
            float(state["deficit_mm"]),
            limits.taw_mm,
            int(state.get("learn_samples") or 0),
        )

    def _zone_request(
        self,
        *,
        zone_id: str,
        name: str,
        data: dict[str, Any],
        state: dict[str, Any],
        et0: float | None,
        month: int,
        now: datetime,
        temp_f: float | None,
        forecast_low_f: float | None,
        wind_mph: float | None,
        recent_mm: float,
        recent_hours: int,
        recent_limit: float,
        freeze_default: float,
        drip_ignores: bool,
        hub_wet: bool,
    ) -> ZoneRequest:
        factor = float(state.get("learn_factor") or 1.0)
        status = str(state.get("dormancy") or "active")
        etc_factor = {"slow": 0.5, "dormant": 0.0}.get(status, 1.0)
        days = self._days_since(state, now.date())
        plant = str(data.get(CONF_PLANT_TYPE, ""))
        interval = _optional_int(data, CONF_MIN_INTERVAL_DAYS)
        if interval is None:
            interval = min_interval_days(plant)
        target = _optional_float(data, CONF_TARGET_DEPTH_IN)
        freeze = _optional_float(data, CONF_FREEZE_SKIP_F)
        if freeze is None:
            freeze = freeze_default
        wind_limit = _optional_float(data, CONF_WIND_SKIP_MPH)
        if wind_limit is None:
            wind_limit = wind_skip_mph(
                str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE)
            )
        try:
            raw = self._limits(data, et0, month).raw_mm * factor
        except (KeyError, ValueError):
            raw = 0.0
        maint = maintenance_due(
            enabled=bool(data.get(CONF_MAINTENANCE_WATERING, False)),
            status=status,
            days_since=days,
            deficit_mm=float(state["deficit_mm"]),
            raw_mm=raw,
            recent_rain_mm=recent_mm,
            recent_rain_skip_mm=recent_limit,
        )
        built = build_zone_request(
            zone_id=zone_id,
            name=name,
            data=data,
            deficit_mm=float(state["deficit_mm"]),
            et0_mm=et0,
            month=month,
            enabled=bool(state.get("enabled", True)),
            rain_sensor_wet=_is_wet(self.hass, data.get(CONF_RAIN_SENSOR) or None),
            skipped_until=state.get("skipped_until"),
            adjustment_pct=float(state.get("adjustment_pct", DEFAULT_ADJUSTMENT_PCT)),
            drip_ignores_schedule=drip_ignores,
            awc_factor=factor,
            etc_factor=etc_factor,
            temp_f=temp_f,
            forecast_low_f=forecast_low_f,
            freeze_f=freeze,
            wind_mph=wind_mph,
            wind_limit_mph=wind_limit,
            recent_rain_mm=recent_mm,
            recent_rain_skip_mm=recent_limit,
            recent_rain_hours=recent_hours,
            moisture_full=self._moisture_full(data),
            moisture_skip_full=self._moisture_skip_full(data, month),
            days_since_water=days,
            min_interval_days=interval,
            dormancy=status,
            dormancy_detail=str(state.get("dormancy_detail") or ""),
            maintenance_due=maint,
            maintenance_mm=MAINTENANCE_MM,
            target_depth_mm=None if target is None else inches_to_mm(target),
            currently_raining=hub_wet,
            flow_locked=bool(state.get("flow_locked") or self.store.flow_locked),
        )
        return replace(
            built,
            max_run_min=self.zone_run_cap(data),
            forecast_defer_reason=self._defer_reason_for(state, float(state["deficit_mm"]), now),
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
        taw_mm: float = 0.0,
    ) -> dict[str, Any]:
        """Flow classification and the stored overrides for one zone snapshot."""
        delivered = float(state.get("flow_delivered_gal") or 0.0)
        expected = None
        status = "not_configured"
        hub_flow = bool(self._options().get(CONF_FLOW_SENSOR))
        has_volume = bool(
            hub_flow
            or _volume_gpm(state, data)
            or _optional_float(data, CONF_AREA_SQFT)
        )
        if has_volume:
            expected = expected_gallons(
                runtime_min=runtime_min,
                precipitation_rate_in_hr=precip,
                area_sqft=_optional_float(data, CONF_AREA_SQFT),
                flow_gpm=_volume_gpm(state, data),
            )
        # Area alone estimates gallons. Only a hub flow meter classifies a leak.
        if hub_flow:
            now = dt_util.now(self._timezone())
            run_finished = True
            if scheduled and next_run is not None:
                run_finished = now >= shift_minutes(next_run, float(runtime_min))
            status = classify_flow(
                expected_gal=expected,
                delivered_gal=delivered,
                scheduled=scheduled,
                run_finished=run_finished,
                low_ratio=float(data.get(CONF_FLOW_LOW_RATIO, DEFAULT_FLOW_LOW_RATIO)),
                leak_ratio=float(data.get(CONF_FLOW_LEAK_RATIO, DEFAULT_FLOW_LEAK_RATIO)),
            )
        alert = state.get("flow_alert")
        if alert:
            status = str(alert)
        elif hub_flow and state.get("last_run_gpm") and not state.get("learned_gpm"):
            status = "learning"
        today = dt_util.now(self._timezone()).date()
        week_gal = period_gallons(state.get("water_days"), today, span="week")
        baseline = self._baseline_for(data, state)
        return {
            "adjustment_pct": float(state.get("adjustment_pct", DEFAULT_ADJUSTMENT_PCT)),
            "sprinkler_type": str(data.get(CONF_SPRINKLER_TYPE, DEFAULT_SPRINKLER_TYPE)),
            "moisture_deficit_mm": state.get("moisture_deficit_mm"),
            "moisture_pct": state.get("moisture_pct"),
            "moisture_mode": str(data.get(CONF_MOISTURE_MODE, DEFAULT_MOISTURE_MODE)),
            "flow_status": status,
            "flow_delivered_gal": delivered,
            "flow_expected_gal": expected,
            "last_run_now": state.get("last_run_now"),
            "last_run": state.get("last_run"),
            "dormancy": str(state.get("dormancy") or "active"),
            "dormancy_mean_f": state.get("dormancy_mean_f"),
            "dormancy_detail": str(state.get("dormancy_detail") or ""),
            "learn_factor": float(state.get("learn_factor") or 1.0),
            "learn_confidence": float(state.get("learn_confidence") or 0.0),
            "learned_gpm": state.get("learned_gpm"),
            "last_run_gpm": state.get("last_run_gpm"),
            "water_total_gal": float(state.get("water_total_gal") or 0.0),
            "water_today_gal": period_gallons(state.get("water_days"), today, span="day"),
            "water_week_gal": week_gal,
            "water_month_gal": period_gallons(state.get("water_days"), today, span="month"),
            "baseline_week_gal": baseline,
            "saved_week_gal": saved_gallons(baseline, week_gal),
            **self._bucket_fields(state, data, taw_mm=taw_mm),
        }

    def _snapshot(
        self,
        *,
        et0: float | None,
        method: str | None,
        detail: str | None,
        et0_date: str | None,
        automatic: bool,
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
                        taw_mm=zone.taw_mm,
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
                        taw_mm=taw,
                    ),
                )
        self._apply_outlook(by_zone)
        blocked = plan.block_reason if plan is not None else "No plan yet."
        options = self._options()
        rules = rules_for(
            options.get(CONF_ALLOWED_WEEKDAYS),
            _optional_int(options, CONF_BLACKOUT_START_HOUR),
            _optional_int(options, CONF_BLACKOUT_END_HOUR),
        )
        week = self._week or {}
        watering = "Idle"
        if self.executor is not None and self.executor.current_name:
            watering = self.executor.current_name
        return HubSnapshot(
            et0_mm=et0,
            et0_method=method,
            et0_detail=detail,
            et0_date=et0_date,
            mode=mode,
            automatic=automatic,
            block_reason=blocked,
            would_execute=would_execute(automatic=automatic, mode=mode),
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
            schedule_markdown=str(week.get("markdown") or ""),
            schedule_days=list(week.get("days") or []),
            schedule_window=str(week.get("window") or ""),
            watering_now=watering,
            alerts=self._alert_lines(),
            outlook_summary=str((self._outlook or {}).get("summary") or ""),
        )

    def _apply_outlook(self, by_zone: dict[str, ZoneSnapshot]) -> None:
        """Fill a next-watering time from the year-long projection when this morning has none."""
        found = (self._outlook or {}).get("by_zone") or {}
        for zone_id, snap in by_zone.items():
            info = found.get(zone_id) or {}
            note = str(info.get("note") or "")
            if not snap.enabled:
                snap.next_run = None
                snap.next_estimated = False
                snap.next_note = note or "Zone is disabled"
                continue
            snap.next_note = note
            if snap.next_run is None and info.get("at") is not None:
                snap.next_run = info["at"]  # type: ignore[assignment]
                snap.next_estimated = bool(info.get("estimated"))
            elif snap.next_run is not None:
                snap.next_estimated = False

    def _et_factors(
        self, observation: Observation, today: date, et0: float | None
    ) -> list[float]:
        """Expected water loss on each future morning, relative to today.

        A forecast high and low use Hargreaves. Otherwise the recent average
        of stored daily water loss is used. With neither, later days repeat today.
        """
        horizon = OUTLOOK_DAYS
        factors = [1.0] * horizon
        if et0 is None or et0 <= 0:
            return factors
        by_day = {
            day: (high, low) for day, high, low in observation.forecast_days
        }
        samples: list[float] = []
        for item in self.store.et0_history:
            if not isinstance(item, dict):
                continue
            try:
                samples.append(float(item["mm"]))
            except (KeyError, TypeError, ValueError):
                continue
        recent = [value for value in samples[-14:] if value > 0]
        average = sum(recent) / len(recent) if recent else None
        latitude = observation.inputs.latitude_deg if observation.inputs else None
        if latitude is None:
            raw = self._options().get(CONF_LATITUDE, self.hass.config.latitude)
            latitude = None if raw is None else float(raw)
        for offset in range(1, horizon):
            day = today + timedelta(days=offset)
            high, low = by_day.get(day, (None, None))
            if (
                high is not None
                and low is not None
                and high - low >= 0.5
                and latitude is not None
            ):
                projected = hargreaves_et0_mm(
                    high,
                    low,
                    extraterrestrial_radiation_mj(float(latitude), day.timetuple().tm_yday),
                )
                if projected > 0:
                    factors[offset] = projected / et0
                    continue
            if average:
                factors[offset] = average / et0
        return factors

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
                    "title": "Smart Water",
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
                start_time=str(options.get(CONF_START_TIME, DEFAULT_START_TIME)),
                finish_time=str(options.get(CONF_FINISH_TIME, DEFAULT_FINISH_TIME)),
                earliest_start=str(
                    options.get(CONF_EARLIEST_START, DEFAULT_EARLIEST_START)
                ),
                plan_hour=int(options.get(CONF_PLAN_HOUR, DEFAULT_PLAN_HOUR)),
                forecast_skip_mm=_optional_float(options, CONF_FORECAST_SKIP_MM),
                max_daily_runtime_min=None if cap in (None, "") else int(cap),
                allowed_weekdays=(
                    tuple(options[CONF_ALLOWED_WEEKDAYS])
                    if options.get(CONF_ALLOWED_WEEKDAYS)
                    else None
                ),
                blackout_start_hour=_optional_int(options, CONF_BLACKOUT_START_HOUR),
                blackout_end_hour=_optional_int(options, CONF_BLACKOUT_END_HOUR),
                drip_ignores_schedule=bool(options.get(CONF_DRIP_IGNORES_SCHEDULE, False)),
                whole_minutes=bool(options.get(CONF_ROUND_MINUTES, DEFAULT_ROUND_MINUTES)),
                wind_height_m=float(options.get(CONF_WIND_HEIGHT_M, DEFAULT_WIND_HEIGHT_M)),
                mode=str(options.get(CONF_MODE, MODE_NOTIFY_ONLY)),
                dry_run=False,
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
        snapshot, _jobs = await self._async_build(force_balance=False, force_notify=False)
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
        forecast, forecast_error = await self._async_forecast(entity_id, "daily")
        hourly_rows, _hourly_error = await self._async_forecast(entity_id, "hourly")
        hourly_wind: list[tuple[datetime, float]] = []
        hourly_precip: list[tuple[datetime, float, float | None]] = []
        forecast_lows: list[tuple[datetime, float]] = []
        forecast_days: list[tuple[date, float | None, float | None]] = []
        for row in hourly_rows:
            stamp = row.get("datetime")
            parsed = dt_util.parse_datetime(str(stamp)) if stamp else None
            if parsed is None:
                continue
            local = dt_util.as_local(parsed)
            if row.get("wind_speed") is not None:
                hourly_wind.append(
                    (
                        local,
                        speed_mph(speed_m_s(float(row["wind_speed"]), wind_unit)),
                    )
                )
            if row.get("precipitation") is not None or row.get("precipitation_probability") is not None:
                hourly_precip.append(
                    (
                        local,
                        _row_precip(row, precip_unit),
                        _row_probability(row),
                    )
                )
            if row.get("temperature") is not None:
                low_f = _forecast_temperature_f(float(row["temperature"]), temp_unit)
                forecast_lows.append((local, low_f))
        daily_precip: list[tuple[datetime, float, float | None]] = []
        for row in forecast:
            stamp = row.get("datetime")
            parsed = dt_util.parse_datetime(str(stamp)) if stamp else None
            if parsed is None:
                continue
            local = dt_util.as_local(parsed)
            if row.get("precipitation") is not None or row.get("precipitation_probability") is not None:
                daily_precip.append((local, _row_precip(row, precip_unit), _row_probability(row)))
            if row.get("templow") is not None:
                forecast_lows.append(
                    (local, _forecast_temperature_f(float(row["templow"]), temp_unit))
                )
            high_c = _row_temp(row, "temperature", temp_unit)
            low_c = _row_temp(row, "templow", temp_unit)
            if high_c is not None or low_c is not None:
                forecast_days.append((local.date(), high_c, low_c))
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
        forecast_low = _row_temp(tomorrow_row, "templow", temp_unit)
        if forecast_low is None:
            forecast_low = _row_temp(today_row, "templow", temp_unit)
        return Observation(
            inputs=inputs,
            precip_today_mm=_row_precip(today_row, precip_unit),
            precip_tomorrow_mm=_row_precip(tomorrow_row, precip_unit),
            error=forecast_error,
            forecast_low_c=forecast_low,
            wind_m_s=wind,
            hourly_wind=tuple(hourly_wind),
            hourly_precip=tuple(hourly_precip),
            daily_precip=tuple(daily_precip),
            forecast_lows=tuple(forecast_lows),
            forecast_days=tuple(forecast_days),
        )

    async def _async_forecast(
        self, entity_id: str, forecast_type: str = "daily"
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": forecast_type},
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
    forecast_low_c: float | None = None
    wind_m_s: float | None = None
    hourly_wind: tuple[tuple[datetime, float], ...] = ()
    hourly_precip: tuple[tuple[datetime, float, float | None], ...] = ()
    daily_precip: tuple[tuple[datetime, float, float | None], ...] = ()
    forecast_lows: tuple[tuple[datetime, float], ...] = ()
    forecast_days: tuple[tuple[date, float | None, float | None], ...] = ()


def _volume_gpm(state: dict[str, Any], data: dict[str, Any]) -> float | None:
    """Configured GPM, otherwise the learned GPM once it exists."""
    configured = _optional_float(data, CONF_FLOW_GPM)
    if configured is not None and configured > 0:
        return configured
    learned = state.get("learned_gpm")
    if learned in (None, ""):
        return None
    try:
        value = float(learned)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _iso_week(day) -> str:
    year, week, _weekday = day.isocalendar()
    return f"{year}-W{week:02d}"


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


def _forecast_temperature_f(value: float, unit: str | None) -> float:
    """Convert a forecast temperature to Fahrenheit.

    ``temperature_f`` takes Celsius only. Forecast rows are in the weather
    entity's unit, so convert to Celsius first. Passing the unit straight
    into ``temperature_f`` raises TypeError and the hub never finishes setup.
    """
    return temperature_f(temperature_c(value, unit))


def _row_probability(row: dict[str, Any] | None) -> float | None:
    """Forecast chance of rain, already in percent. Missing is not 100%."""
    if not row or row.get("precipitation_probability") is None:
        return None
    try:
        return float(row["precipitation_probability"])
    except (TypeError, ValueError):
        return None


def _row_precip(row: dict[str, Any] | None, unit: str | None) -> float:
    if not row or row.get("precipitation") is None:
        return 0.0
    return depth_mm(float(row["precipitation"]), unit)


type SmartWaterConfigEntry = ConfigEntry[SmartWaterCoordinator]
