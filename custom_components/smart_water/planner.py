"""Nightly watering plan.

The planner decides which zones are due, splits each run with cycle-and-soak,
and lays the cycles on one shared timeline so only one valve is open.
While one zone soaks, another zone may run. The timeline is then shifted so
the last cycle ends at sunrise minus the buffer. This module does not call
a service. The executor applies the timeline when automatic watering is on.

If the timeline is longer than the allowed window, cycle lengths are scaled
down and a warning is attached. Soak times are kept, because shortening them
is what the intake table is trying to avoid. A plan that still cannot finish
by sunrise keeps the warning rather than pretending it fits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .balance import root_zone, zone_is_due
from .const import (
    CONF_AREA_SQFT,
    CONF_AWC_OVERRIDE,
    CONF_DEPLETION,
    CONF_FLOW_GPM,
    CONF_INTAKE_IN_HR,
    CONF_KC_OVERRIDE,
    CONF_MAX_CYCLE_MIN,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRIORITY,
    CONF_SOAK_MIN,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    DEFAULT_ADJUSTMENT_PCT,
    DEFAULT_PRIORITY,
    DEFAULT_SPRINKLER_TYPE,
    SPRINKLER_DRIP,
)
from .cycle_soak import plan_cycles, resolve_precipitation_rate
from .presets import (
    resolved_efficiency,
    resolved_root_depth_in,
    resolved_slope_pct,
    sprinkler_precip,
    stored_float,
)
from .safety import block_reason, would_execute
from .schedule import clip_blackout, day_allowed, weekday_name
from .skips import SkipInputs, skip_reason


@dataclass(frozen=True)
class ZoneRequest:
    """One zone handed to the planner. Agronomy is already resolved."""

    zone_id: str
    name: str
    soil_type: str
    slope_pct: float
    precipitation_rate_in_hr: float
    efficiency: float
    deficit_mm: float
    taw_mm: float
    raw_mm: float
    etc_mm: float
    kc: float
    p: float
    enabled: bool
    rain_sensor_wet: bool
    skipped_until: str | None
    priority: int
    max_cycle_override_min: int | None = None
    soak_override_min: int | None = None
    adjustment_pct: float = 100.0
    sprinkler_type: str = "spray"
    ignores_schedule: bool = False
    intake_override_in_hr: float | None = None
    temp_f: float | None = None
    forecast_low_f: float | None = None
    freeze_f: float | None = None
    wind_mph: float | None = None
    wind_limit_mph: float | None = None
    recent_rain_mm: float = 0.0
    recent_rain_skip_mm: float | None = None
    recent_rain_hours: int = 12
    moisture_full: float | None = None
    moisture_skip_full: float | None = None
    days_since_water: int | None = None
    min_interval_days: int | None = None
    dormancy: str = "active"
    dormancy_detail: str = ""
    maintenance_due: bool = False
    maintenance_mm: float = 0.0
    target_depth_mm: float | None = None
    currently_raining: bool = False


def build_zone_request(
    *,
    zone_id: str,
    name: str,
    data: dict[str, object],
    deficit_mm: float,
    et0_mm: float | None,
    month: int | None,
    enabled: bool = True,
    rain_sensor_wet: bool = False,
    skipped_until: str | None = None,
    adjustment_pct: float = DEFAULT_ADJUSTMENT_PCT,
    drip_ignores_schedule: bool = False,
    awc_factor: float = 1.0,
    etc_factor: float = 1.0,
    temp_f: float | None = None,
    forecast_low_f: float | None = None,
    freeze_f: float | None = None,
    wind_mph: float | None = None,
    wind_limit_mph: float | None = None,
    recent_rain_mm: float = 0.0,
    recent_rain_skip_mm: float | None = None,
    recent_rain_hours: int = 12,
    moisture_full: float | None = None,
    moisture_skip_full: float | None = None,
    days_since_water: int | None = None,
    min_interval_days: int | None = None,
    dormancy: str = "active",
    dormancy_detail: str = "",
    maintenance_due: bool = False,
    maintenance_mm: float = 0.0,
    target_depth_mm: float | None = None,
    currently_raining: bool = False,
) -> ZoneRequest:
    """Resolve one zone the way the nightly plan does.

    The coordinator and the week simulation both call this, then
    :func:`build_plan`, so a simulated week uses the same presets, overrides,
    and runtime rules as a live hub.
    """
    sprinkler = str(data.get(CONF_SPRINKLER_TYPE) or DEFAULT_SPRINKLER_TYPE)
    limits = root_zone(
        soil_type=str(data[CONF_SOIL_TYPE]),
        plant_type=str(data[CONF_PLANT_TYPE]),
        sun_exposure=str(data[CONF_SUN_EXPOSURE]),
        root_depth_in=resolved_root_depth_in(data),
        p_table=stored_float(data, CONF_DEPLETION),
        kc_override=stored_float(data, CONF_KC_OVERRIDE),
        awc_override=stored_float(data, CONF_AWC_OVERRIDE),
        et0_mm=et0_mm,
        month=month,
    )
    max_cycle = stored_float(data, CONF_MAX_CYCLE_MIN)
    soak = stored_float(data, CONF_SOAK_MIN)
    return ZoneRequest(
        zone_id=zone_id,
        name=name,
        soil_type=str(data[CONF_SOIL_TYPE]),
        slope_pct=resolved_slope_pct(data),
        precipitation_rate_in_hr=resolve_precipitation_rate(
            stored_float(data, CONF_PRECIPITATION_RATE),
            stored_float(data, CONF_FLOW_GPM),
            stored_float(data, CONF_AREA_SQFT),
            sprinkler_precip(sprinkler),
        ),
        efficiency=resolved_efficiency(data),
        deficit_mm=deficit_mm,
        taw_mm=limits.taw_mm * awc_factor,
        raw_mm=limits.raw_mm * awc_factor,
        etc_mm=(0.0 if limits.etc_mm is None else limits.etc_mm) * etc_factor,
        kc=limits.kc,
        p=limits.p,
        enabled=enabled,
        rain_sensor_wet=rain_sensor_wet,
        skipped_until=skipped_until,
        priority=int(data.get(CONF_PRIORITY) or DEFAULT_PRIORITY),
        max_cycle_override_min=None if max_cycle is None else int(max_cycle),
        soak_override_min=None if soak is None else int(soak),
        intake_override_in_hr=stored_float(data, CONF_INTAKE_IN_HR),
        adjustment_pct=adjustment_pct,
        sprinkler_type=sprinkler,
        ignores_schedule=drip_ignores_schedule and sprinkler == SPRINKLER_DRIP,
        temp_f=temp_f,
        forecast_low_f=forecast_low_f,
        freeze_f=freeze_f,
        wind_mph=wind_mph,
        wind_limit_mph=wind_limit_mph,
        recent_rain_mm=recent_rain_mm,
        recent_rain_skip_mm=recent_rain_skip_mm,
        recent_rain_hours=recent_rain_hours,
        moisture_full=moisture_full,
        moisture_skip_full=moisture_skip_full,
        days_since_water=days_since_water,
        min_interval_days=min_interval_days,
        dormancy=dormancy,
        dormancy_detail=dormancy_detail,
        maintenance_due=maintenance_due,
        maintenance_mm=maintenance_mm,
        target_depth_mm=target_depth_mm,
        currently_raining=currently_raining,
    )


@dataclass(frozen=True)
class PlanRequest:
    """Everything the nightly plan needs. Times are timezone-aware."""

    zones: tuple[ZoneRequest, ...]
    finish_by: datetime
    earliest_start: datetime | None
    forecast_precip_mm: float
    forecast_skip_mm: float | None
    hub_rain_wet: bool
    mode: str
    automatic: bool = False
    max_daily_runtime_min: int | None = None
    days_ahead: int = 0
    allowed_weekdays: tuple[str, ...] | None = None
    blackout_start_hour: int | None = None
    blackout_end_hour: int | None = None
    whole_minutes: bool = True


@dataclass(frozen=True)
class ZonePlan:
    """Per-zone result, whether or not a run was placed on the timeline."""

    zone_id: str
    name: str
    due: bool
    scheduled: bool
    reason: str
    deficit_mm: float
    raw_mm: float
    taw_mm: float
    etc_mm: float
    kc: float
    p: float
    net_mm: float
    runtime_min: int | float
    max_cycle_min: int
    soak_min: int
    cycles: tuple[int | float, ...]
    precipitation_rate_in_hr: float


@dataclass(frozen=True)
class TimelineEvent:
    """One cycle on the shared one-valve timeline."""

    zone_id: str
    zone_name: str
    cycle_index: int
    cycle_count: int
    duration_min: int | float
    start: datetime
    end: datetime


@dataclass(frozen=True)
class NightPlan:
    """A complete plan. ``would_execute`` is true only when automatic watering may run."""

    finish_by: datetime
    earliest_start: datetime | None
    automatic: bool
    mode: str
    would_execute: bool
    block_reason: str
    warning: str | None
    summary: str
    zones: tuple[ZonePlan, ...]
    timeline: tuple[TimelineEvent, ...]

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly view for entity attributes and the saved plan."""
        return {
            "finish_by": self.finish_by.isoformat(),
            "earliest_start": (
                None
                if self.earliest_start is None
                else self.earliest_start.isoformat()
            ),
            "automatic": self.automatic,
            "mode": self.mode,
            "would_execute": self.would_execute,
            "block_reason": self.block_reason,
            "warning": self.warning,
            "summary": self.summary,
            "zones": [
                {
                    "zone_id": zone.zone_id,
                    "name": zone.name,
                    "due": zone.due,
                    "scheduled": zone.scheduled,
                    "reason": zone.reason,
                    "deficit_mm": zone.deficit_mm,
                    "raw_mm": zone.raw_mm,
                    "taw_mm": zone.taw_mm,
                    "etc_mm": zone.etc_mm,
                    "runtime_min": zone.runtime_min,
                    "cycles": list(zone.cycles),
                    "soak_min": zone.soak_min,
                    "max_cycle_min": zone.max_cycle_min,
                }
                for zone in self.zones
            ],
            "timeline": [
                {
                    "zone": event.zone_name,
                    "zone_id": event.zone_id,
                    "cycle": event.cycle_index,
                    "of": event.cycle_count,
                    "minutes": event.duration_min,
                    "start": event.start.isoformat(),
                    "end": event.end.isoformat(),
                }
                for event in self.timeline
            ],
        }


@dataclass
class _Job:
    zone: ZonePlan
    cycles: list[int]
    soak_min: int
    priority: int
    next_index: int = 0
    ready_min: int = 0


def _scale_cycles(
    cycles: tuple[int | float, ...], scale: float, *, whole: bool
) -> tuple[int | float, ...]:
    if whole:
        return tuple(
            max(1, int(round(minutes * scale))) for minutes in cycles if minutes > 0
        )
    return tuple(max(0.1, round(minutes * scale, 1)) for minutes in cycles if minutes > 0)


def _schedule(jobs: list[_Job]) -> list[tuple[_Job, int, int, int]]:
    """Return (job, cycle_index, start_min, end_min) with one valve at a time.

    A zone's next cycle cannot start until its soak has elapsed. Another
    zone can use that gap. Times are minutes from an arbitrary zero.
    """
    events: list[tuple[_Job, int, int, int]] = []
    valve_free = 0
    guard = 0
    while any(job.next_index < len(job.cycles) for job in jobs):
        guard += 1
        if guard > 10000:
            raise RuntimeError("cycle schedule did not finish")
        ready = [
            job
            for job in jobs
            if job.next_index < len(job.cycles) and job.ready_min <= valve_free
        ]
        if not ready:
            valve_free = min(
                job.ready_min for job in jobs if job.next_index < len(job.cycles)
            )
            continue
        ready.sort(key=lambda job: (job.priority, job.zone.name))
        job = ready[0]
        duration = job.cycles[job.next_index]
        start = valve_free
        end = start + duration
        cycle_index = job.next_index + 1
        job.next_index += 1
        events.append((job, cycle_index, start, end))
        valve_free = end
        if job.next_index < len(job.cycles):
            job.ready_min = end + job.soak_min
    return events


def _span_minutes(events: list[tuple[_Job, int, int, int]]) -> int:
    if not events:
        return 0
    return events[-1][3]


def _place(
    events: list[tuple[_Job, int, int, int]],
    finish_by: datetime,
) -> tuple[TimelineEvent, ...]:
    if not events:
        return ()
    last_end = events[-1][3]
    placed: list[TimelineEvent] = []
    for job, cycle_index, start_min, end_min in events:
        placed.append(
            TimelineEvent(
                zone_id=job.zone.zone_id,
                zone_name=job.zone.name,
                cycle_index=cycle_index,
                cycle_count=len(job.cycles),
                duration_min=end_min - start_min,
                start=finish_by - timedelta(minutes=last_end - start_min),
                end=finish_by - timedelta(minutes=last_end - end_min),
            )
        )
    return tuple(placed)


def short_status(plan: NightPlan | None) -> str:
    """One-line state for the hub sensor. Home Assistant states cap at 255."""
    if plan is None:
        return "No plan yet"
    scheduled = [zone for zone in plan.zones if zone.scheduled]
    minutes = sum(zone.runtime_min for zone in scheduled)
    prefix = "automatic" if plan.would_execute else "planned"
    text = f"{prefix} · {len(scheduled)} zones · {minutes} min"
    if plan.warning:
        text += " · warning"
    return text[:255]


def _summary(
    plan_zones: list[ZonePlan],
    timeline: tuple[TimelineEvent, ...],
    warning: str | None,
    blocked: str,
    *,
    automatic: bool,
) -> str:
    label = "AUTOMATIC" if automatic and not blocked else "PLANNED"
    lines = [f"{label} — {blocked}."] if blocked else [f"{label}."]
    if warning:
        lines.append(f"Warning: {warning}")
    scheduled = [zone for zone in plan_zones if zone.scheduled]
    if not scheduled:
        lines.append("No zones scheduled.")
    for zone in plan_zones:
        if zone.scheduled:
            cycles = "+".join(str(minutes) for minutes in zone.cycles)
            lines.append(
                f"{zone.name}: {cycles} min, soak {zone.soak_min} min "
                f"(deficit {zone.deficit_mm:.1f} mm, RAW {zone.raw_mm:.1f} mm)."
            )
        else:
            lines.append(f"{zone.name}: not scheduled — {zone.reason}")
    if timeline:
        lines.append(
            "Finish by "
            f"{timeline[-1].end.strftime('%Y-%m-%d %H:%M')}."
        )
    return "\n".join(lines)


def build_plan(request: PlanRequest) -> NightPlan:
    """Build tonight's plan. ``would_execute`` follows :func:`would_execute`."""
    if request.finish_by.tzinfo is None:
        raise ValueError("finish_by must be timezone-aware")
    if request.earliest_start is not None and request.earliest_start.tzinfo is None:
        raise ValueError("earliest_start must be timezone-aware")

    blocked = block_reason(automatic=request.automatic, mode=request.mode)
    warnings: list[str] = []
    finish_by, earliest, blackout_note = clip_blackout(
        request.finish_by,
        request.earliest_start,
        request.blackout_start_hour,
        request.blackout_end_hour,
    )
    if blackout_note:
        warnings.append(blackout_note)
    finish_day = finish_by.date().isoformat()
    zone_plans: list[ZonePlan] = []
    jobs: list[_Job] = []

    window_closed = earliest is not None and earliest >= finish_by
    if window_closed:
        warnings.append(
            "The earliest start is at or after the sunrise deadline, "
            "so nothing was scheduled."
        )

    forecast_skip = (
        request.forecast_skip_mm is not None
        and request.forecast_precip_mm >= request.forecast_skip_mm
    )

    for zone in sorted(request.zones, key=lambda item: (item.priority, item.name)):
        trigger = zone.raw_mm if zone.target_depth_mm is None else zone.target_depth_mm
        due, due_reason = zone_is_due(
            zone.deficit_mm,
            trigger,
            zone.taw_mm,
            zone.etc_mm,
            days_ahead=request.days_ahead,
        )
        if zone.target_depth_mm is not None:
            due_reason = due_reason.replace("RAW", "target depth")
        blocked_reason = skip_reason(
            SkipInputs(
                enabled=zone.enabled,
                skipped_until=zone.skipped_until,
                finish_day=finish_day,
                hub_rain_wet=request.hub_rain_wet,
                rain_sensor_wet=zone.rain_sensor_wet,
                currently_raining=zone.currently_raining,
                recent_rain_mm=zone.recent_rain_mm,
                recent_rain_skip_mm=zone.recent_rain_skip_mm,
                recent_rain_hours=zone.recent_rain_hours,
                temp_f=zone.temp_f,
                forecast_low_f=zone.forecast_low_f,
                freeze_f=zone.freeze_f,
                wind_mph=zone.wind_mph,
                wind_limit_mph=zone.wind_limit_mph,
                moisture_full=zone.moisture_full,
                moisture_skip_full=zone.moisture_skip_full,
                forecast_skip=forecast_skip,
                forecast_mm=request.forecast_precip_mm,
                allowed_day=day_allowed(finish_by, request.allowed_weekdays),
                ignores_schedule=zone.ignores_schedule,
                weekday=weekday_name(finish_by),
                window_closed=window_closed,
                due=due,
                due_reason=due_reason,
                days_since_water=zone.days_since_water,
                min_interval_days=zone.min_interval_days,
                dormancy=zone.dormancy,
                dormancy_detail=zone.dormancy_detail,
                maintenance_due=zone.maintenance_due,
            )
        )
        reason = due_reason if blocked_reason is None else blocked_reason
        scheduled_candidate = blocked_reason is None

        cycles: tuple[int | float, ...] = ()
        runtime: int | float = 0
        max_cycle = 0
        soak = 0
        net_mm = 0.0
        adjusted_mm = zone.deficit_mm * zone.adjustment_pct / 100.0
        if (
            scheduled_candidate
            and zone.dormancy == "dormant"
            and zone.maintenance_due
            and zone.maintenance_mm > 0
        ):
            adjusted_mm = min(adjusted_mm, zone.maintenance_mm)
        if scheduled_candidate and adjusted_mm <= 0:
            scheduled_candidate = False
            reason = "Adjustment percent is 0."
        if scheduled_candidate:
            # Refill the adjusted deficit and no more, so water stays in the root zone.
            cycle_plan = plan_cycles(
                net_mm=adjusted_mm,
                precipitation_rate_in_hr=zone.precipitation_rate_in_hr,
                efficiency=zone.efficiency,
                soil_type=zone.soil_type,
                slope_pct=zone.slope_pct,
                max_cycle_override_min=zone.max_cycle_override_min,
                soak_override_min=zone.soak_override_min,
                whole_minutes=request.whole_minutes,
                sprinkler_type=zone.sprinkler_type,
                intake_override_in_hr=zone.intake_override_in_hr,
            )
            cycles = cycle_plan.cycles_min
            runtime = cycle_plan.total_runtime_min
            max_cycle = cycle_plan.max_cycle_min
            soak = cycle_plan.soak_min
            net_mm = cycle_plan.net_mm
            if cycle_plan.note:
                warnings.append(f"{zone.name}: {cycle_plan.note}")
            if not cycles:
                scheduled_candidate = False
                reason = "Runtime rounds to 0 minutes."

        zone_plan = ZonePlan(
            zone_id=zone.zone_id,
            name=zone.name,
            due=due and zone.enabled,
            scheduled=False,
            reason=reason,
            deficit_mm=zone.deficit_mm,
            raw_mm=zone.raw_mm,
            taw_mm=zone.taw_mm,
            etc_mm=zone.etc_mm,
            kc=zone.kc,
            p=zone.p,
            net_mm=net_mm,
            runtime_min=runtime,
            max_cycle_min=max_cycle,
            soak_min=soak,
            cycles=cycles,
            precipitation_rate_in_hr=zone.precipitation_rate_in_hr,
        )
        zone_plans.append(zone_plan)
        if scheduled_candidate and cycles:
            jobs.append(
                _Job(
                    zone=zone_plan,
                    cycles=list(cycles),
                    soak_min=soak,
                    priority=zone.priority,
                )
            )

    if request.max_daily_runtime_min is not None and jobs:
        total = sum(sum(job.cycles) for job in jobs)
        cap = request.max_daily_runtime_min
        if total > cap and total > 0 and cap > 0:
            scale = cap / total
            for job in jobs:
                job.cycles = list(
                    _scale_cycles(tuple(job.cycles), scale, whole=request.whole_minutes)
                )
            warnings.append(
                f"Total runtime {total} min exceeds the daily cap of {cap} min "
                "and was trimmed."
            )

    events = _schedule(jobs) if jobs and not window_closed else []
    # The clipped deadline is what the timeline must finish by.
    request_finish = finish_by
    request_earliest = earliest
    if events and request_earliest is not None:
        window = (request_finish - request_earliest).total_seconds() / 60.0
        span = _span_minutes(events)
        if window <= 0:
            events = []
        elif span > window:
            scale = window / span
            for job in jobs:
                job.next_index = 0
                job.ready_min = 0
                job.cycles = list(
                    _scale_cycles(tuple(job.cycles), scale, whole=request.whole_minutes)
                )
            events = _schedule(jobs)
            span = _span_minutes(events)
            if span > window:
                warnings.append(
                    "Runtimes were trimmed and the plan still overruns the "
                    "window because soak time remains."
                )
            else:
                warnings.append("Runtimes were trimmed to fit the watering window.")

    timeline = _place(events, request_finish)
    if (
        timeline
        and request_earliest is not None
        and timeline[0].start < request_earliest
    ):
        warnings.append("The plan starts before the earliest allowed time.")

    scheduled_ids = {event.zone_id for event in timeline}
    final_zones: list[ZonePlan] = []
    for zone_plan, job in _zip_jobs(zone_plans, jobs):
        if zone_plan.zone_id not in scheduled_ids:
            final_zones.append(zone_plan)
            continue
        cycles = tuple(job.cycles) if job is not None else zone_plan.cycles
        final_zones.append(
            ZonePlan(
                zone_id=zone_plan.zone_id,
                name=zone_plan.name,
                due=zone_plan.due,
                scheduled=True,
                reason=zone_plan.reason,
                deficit_mm=zone_plan.deficit_mm,
                raw_mm=zone_plan.raw_mm,
                taw_mm=zone_plan.taw_mm,
                etc_mm=zone_plan.etc_mm,
                kc=zone_plan.kc,
                p=zone_plan.p,
                net_mm=zone_plan.net_mm,
                runtime_min=sum(cycles),
                max_cycle_min=zone_plan.max_cycle_min,
                soak_min=zone_plan.soak_min,
                cycles=cycles,
                precipitation_rate_in_hr=zone_plan.precipitation_rate_in_hr,
            )
        )

    warning = " ".join(warnings) if warnings else None
    executing = would_execute(automatic=request.automatic, mode=request.mode)
    summary = _summary(
        final_zones, timeline, warning, blocked, automatic=executing
    )
    return NightPlan(
        finish_by=request_finish,
        earliest_start=request_earliest,
        automatic=request.automatic,
        mode=request.mode,
        would_execute=executing,
        block_reason=blocked,
        warning=warning,
        summary=summary,
        zones=tuple(final_zones),
        timeline=timeline,
    )


def _zip_jobs(
    zones: list[ZonePlan], jobs: list[_Job]
) -> list[tuple[ZonePlan, _Job | None]]:
    by_id = {job.zone.zone_id: job for job in jobs}
    return [(zone, by_id.get(zone.zone_id)) for zone in zones]
