"""Play a week of weather through the same planner a live hub uses.

Nothing here calls a valve, a switch, or a controller. A simulation hub's
on/off id is a ``simulation.<name>`` label, not a Home Assistant entity.
After each night the planned net depth is credited to the bucket, which is
what a later executor would do, so the next day starts from that soil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .balance import apply_daily_balance, root_zone
from .const import (
    CONF_AREA_SQFT,
    CONF_DEPLETION,
    CONF_FLOW_GPM,
    CONF_PLANT_TYPE,
    CONF_SUN_EXPOSURE,
    DEFAULT_ADJUSTMENT_PCT,
    DEFAULT_ELEVATION_M,
    DEFAULT_EARLIEST_START,
    DEFAULT_FINISH_TIME,
    DEFAULT_PLAN_HOUR,
    DEFAULT_ROUND_MINUTES,
    DEFAULT_START_TIME,
    DEFAULT_WIND_HEIGHT_M,
)
from .et import daily_et0, extraterrestrial_radiation_mj, radiation_from_sunshine_mj
from .et import ETInputs
from .flow import expected_gallons
from .planner import NightPlan, PlanRequest, build_plan, build_zone_request
from .presets import resolved_root_depth_in, stored_float
from .schedule import morning_window, rules_for
from .units import inches_to_mm, mm_to_inches, speed_m_s, temperature_c

BUCKET_FULL = "full"
BUCKET_HALF = "half"
BUCKET_RAW = "raw"
BUCKETS = (BUCKET_FULL, BUCKET_HALF, BUCKET_RAW)

SCENARIO_HOT_DRY = "hot_dry"
SCENARIO_MILD_SPRING = "mild_spring"
SCENARIO_RAINY = "rainy"
SCENARIO_HEAT_STORM = "heat_then_storm"
SCENARIO_FALL = "fall_cooldown"
SCENARIOS = (
    SCENARIO_HOT_DRY,
    SCENARIO_MILD_SPRING,
    SCENARIO_RAINY,
    SCENARIO_HEAT_STORM,
    SCENARIO_FALL,
)
DEFAULT_SCENARIO = SCENARIO_HOT_DRY
DEFAULT_BUCKET = BUCKET_FULL

# Example weeks, not a forecast and not a climate normal. Temperatures are
# the kind of day the name describes in central Texas: a dry July stretch
# with highs around 100°F, a mild April week, a wet week, a heat spell that
# breaks, and a cooling fall week. Daily numbers are round on purpose.
_WeekRow = tuple[float, float, float, float, float, float]
# high °F, low °F, humidity %, wind mph, cloud 0–1, rain inches


def _rows(values: tuple[_WeekRow, ...]) -> tuple[_WeekRow, ...]:
    if len(values) != 7:
        raise ValueError("a preset week has 7 days")
    return values


_PRESET_ROWS: dict[str, tuple[_WeekRow, ...]] = {
    SCENARIO_HOT_DRY: _rows(
        (
            (99, 75, 40, 8, 0.10, 0.0),
            (101, 76, 38, 9, 0.10, 0.0),
            (102, 77, 35, 10, 0.05, 0.0),
            (103, 78, 32, 8, 0.10, 0.0),
            (101, 76, 36, 7, 0.15, 0.0),
            (100, 75, 40, 8, 0.20, 0.0),
            (98, 74, 45, 9, 0.25, 0.0),
        )
    ),
    SCENARIO_MILD_SPRING: _rows(
        (
            (76, 54, 65, 10, 0.40, 0.0),
            (78, 56, 62, 9, 0.35, 0.0),
            (74, 55, 70, 12, 0.55, 0.15),
            (72, 53, 68, 11, 0.50, 0.05),
            (77, 55, 60, 8, 0.30, 0.0),
            (80, 57, 58, 8, 0.25, 0.0),
            (79, 56, 60, 9, 0.35, 0.0),
        )
    ),
    SCENARIO_RAINY: _rows(
        (
            (80, 68, 85, 12, 0.85, 0.60),
            (78, 67, 88, 10, 0.90, 0.20),
            (76, 66, 90, 14, 0.95, 0.90),
            (79, 67, 86, 11, 0.80, 0.40),
            (82, 68, 80, 9, 0.70, 0.10),
            (77, 66, 92, 13, 0.95, 0.80),
            (81, 69, 84, 10, 0.75, 0.30),
        )
    ),
    SCENARIO_HEAT_STORM: _rows(
        (
            (102, 77, 35, 8, 0.10, 0.0),
            (104, 78, 32, 9, 0.05, 0.0),
            (103, 78, 34, 8, 0.10, 0.0),
            (100, 76, 40, 10, 0.20, 0.0),
            (90, 72, 75, 12, 0.70, 0.30),
            (84, 70, 88, 14, 0.95, 1.20),
            (86, 71, 80, 10, 0.80, 0.50),
        )
    ),
    SCENARIO_FALL: _rows(
        (
            (90, 68, 50, 8, 0.25, 0.0),
            (86, 64, 52, 8, 0.30, 0.0),
            (82, 60, 55, 9, 0.35, 0.0),
            (78, 56, 60, 10, 0.45, 0.20),
            (74, 52, 55, 9, 0.30, 0.0),
            (70, 48, 50, 8, 0.25, 0.0),
            (68, 46, 48, 7, 0.20, 0.0),
        )
    ),
}

SCENARIO_NAMES = {
    SCENARIO_HOT_DRY: "Hot dry Texas summer",
    SCENARIO_MILD_SPRING: "Mild spring",
    SCENARIO_RAINY: "Rainy week",
    SCENARIO_HEAT_STORM: "Heat wave then storm",
    SCENARIO_FALL: "Fall cooldown",
}


@dataclass(frozen=True)
class WeatherDay:
    """One day's weather in the units the ET function already accepts."""

    high_c: float
    low_c: float
    humidity_pct: float
    wind_m_s: float
    cloud: float
    rain_mm: float
    high_f: float
    low_f: float
    rain_in: float


@dataclass(frozen=True)
class SimZone:
    """A zone config dict plus the overrides the planner already understands."""

    zone_id: str
    name: str
    data: dict[str, Any]
    enabled: bool = True
    skipped_until: str | None = None
    adjustment_pct: float = DEFAULT_ADJUSTMENT_PCT


@dataclass(frozen=True)
class SimSettings:
    """Hub options that change the plan, copied from the live coordinator."""

    latitude: float
    longitude: float
    elevation_m: float = DEFAULT_ELEVATION_M
    timezone: str = "America/Chicago"
    start: date | None = None
    start_time: str = DEFAULT_START_TIME
    finish_time: str = DEFAULT_FINISH_TIME
    earliest_start: str = DEFAULT_EARLIEST_START
    plan_hour: int = DEFAULT_PLAN_HOUR
    forecast_skip_mm: float | None = None
    max_daily_runtime_min: int | None = None
    allowed_weekdays: tuple[str, ...] | None = None
    blackout_start_hour: int | None = None
    blackout_end_hour: int | None = None
    drip_ignores_schedule: bool = False
    whole_minutes: bool = DEFAULT_ROUND_MINUTES
    wind_height_m: float = DEFAULT_WIND_HEIGHT_M
    mode: str = "notify_only"
    dry_run: bool = False


def preset_week(scenario: str) -> tuple[WeatherDay, ...]:
    """Return the seven example days for a named scenario."""
    rows = _PRESET_ROWS.get(scenario)
    if rows is None:
        known = ", ".join(SCENARIOS)
        raise ValueError(f"Unknown scenario {scenario!r}. Choose one of: {known}.")
    return tuple(_row_to_day(row) for row in rows)


def _row_to_day(row: _WeekRow) -> WeatherDay:
    high_f, low_f, humidity, wind_mph, cloud, rain_in = row
    return WeatherDay(
        high_c=temperature_c(high_f, "°F"),
        low_c=temperature_c(low_f, "°F"),
        humidity_pct=humidity,
        wind_m_s=speed_m_s(wind_mph, "mph"),
        cloud=cloud,
        rain_mm=inches_to_mm(rain_in),
        high_f=high_f,
        low_f=low_f,
        rain_in=rain_in,
    )


def parse_day(raw: dict[str, Any]) -> WeatherDay:
    """Build one day from a service payload. Fahrenheit or Celsius, inches or mm."""
    if raw.get("high_c") is not None:
        high_c = float(raw["high_c"])
        high_f = high_c * 9.0 / 5.0 + 32.0
    elif raw.get("high_f") is not None:
        high_f = float(raw["high_f"])
        high_c = temperature_c(high_f, "°F")
    else:
        raise ValueError("Each day needs high_f or high_c.")
    if raw.get("low_c") is not None:
        low_c = float(raw["low_c"])
        low_f = low_c * 9.0 / 5.0 + 32.0
    elif raw.get("low_f") is not None:
        low_f = float(raw["low_f"])
        low_c = temperature_c(low_f, "°F")
    else:
        raise ValueError("Each day needs low_f or low_c.")
    if raw.get("rain_mm") is not None:
        rain_mm = float(raw["rain_mm"])
        rain_in = mm_to_inches(rain_mm)
    else:
        rain_in = float(raw.get("rain_in") or 0.0)
        rain_mm = inches_to_mm(rain_in)
    if raw.get("wind_m_s") is not None:
        wind = float(raw["wind_m_s"])
    else:
        wind = speed_m_s(float(raw.get("wind_mph") or 8.0), "mph")
    return WeatherDay(
        high_c=high_c,
        low_c=low_c,
        humidity_pct=float(raw.get("humidity") if raw.get("humidity") is not None else 50),
        wind_m_s=wind,
        cloud=float(raw.get("cloud") if raw.get("cloud") is not None else 0.2),
        rain_mm=rain_mm,
        high_f=high_f,
        low_f=low_f,
        rain_in=rain_in,
    )


def initial_deficit_mm(bucket: str, data: dict[str, Any], month: int) -> float:
    """Starting soil deficit. Full is field capacity. Raw is ready to water."""
    limits = root_zone(
        soil_type=str(data["soil_type"]),
        plant_type=str(data[CONF_PLANT_TYPE]),
        sun_exposure=str(data[CONF_SUN_EXPOSURE]),
        root_depth_in=resolved_root_depth_in(data),
        p_table=stored_float(data, CONF_DEPLETION),
        et0_mm=None,
        month=month,
    )
    if bucket == BUCKET_FULL:
        return 0.0
    if bucket == BUCKET_HALF:
        return 0.5 * limits.taw_mm
    if bucket == BUCKET_RAW:
        return limits.raw_mm
    raise ValueError(f"Unknown bucket {bucket!r}. Use full, half, or raw.")


def run_week(
    zones: tuple[SimZone, ...],
    weather: tuple[WeatherDay, ...],
    settings: SimSettings,
    *,
    bucket: str = DEFAULT_BUCKET,
    scenario: str | None = None,
) -> dict[str, Any]:
    """Run each day through ET, the bucket, and ``build_plan``.

    The returned dict is JSON-serializable. ``would_execute`` is false.
    """
    if not zones:
        raise ValueError("Add a zone before running a simulation.")
    if not weather:
        raise ValueError("A simulation needs at least one day of weather.")
    if bucket not in BUCKETS:
        raise ValueError(f"Unknown bucket {bucket!r}. Use full, half, or raw.")

    tz = ZoneInfo(settings.timezone)
    start = settings.start or datetime.now(tz).date()
    schedule = rules_for(
        settings.allowed_weekdays,
        settings.blackout_start_hour,
        settings.blackout_end_hour,
    )
    deficits = {
        zone.zone_id: initial_deficit_mm(bucket, zone.data, start.month) for zone in zones
    }
    day_rows: list[dict[str, Any]] = []
    total_runtime = 0.0

    for index, day in enumerate(weather):
        current = start + timedelta(days=index)
        et0, et_detail = _et0_mm(day, current, settings)
        tomorrow_rain = weather[index + 1].rain_mm if index + 1 < len(weather) else 0.0
        evening = datetime(
            current.year,
            current.month,
            current.day,
            settings.plan_hour,
            tzinfo=tz,
        )
        plan, balances = _plan_evening(
            zones=zones,
            deficits=deficits,
            et0=et0,
            month=current.month,
            rain_mm=day.rain_mm,
            evening=evening,
            tomorrow_rain_mm=tomorrow_rain,
            settings=settings,
            schedule_days=schedule.allowed_weekdays,
            blackout_start=schedule.blackout_start,
            blackout_end=schedule.blackout_end,
        )
        zone_rows = []
        for zone in zones:
            limits_rain = balances[zone.zone_id]
            planned = next(item for item in plan.zones if item.zone_id == zone.zone_id)
            starts = [
                event.start.astimezone(tz).strftime("%a %H:%M")
                for event in plan.timeline
                if event.zone_id == zone.zone_id
            ]
            gallons = expected_gallons(
                runtime_min=float(planned.runtime_min),
                precipitation_rate_in_hr=planned.precipitation_rate_in_hr,
                area_sqft=_area(zone.data),
                flow_gpm=stored_float(zone.data, CONF_FLOW_GPM),
            )
            zone_rows.append(
                {
                    "zone_id": zone.zone_id,
                    "name": zone.name,
                    "et0_mm": round(et0, 2),
                    "etc_mm": round(planned.etc_mm, 2),
                    "kc": round(planned.kc, 2),
                    "rain_mm": round(day.rain_mm, 2),
                    "effective_rain_mm": round(limits_rain.effective_precip_mm, 2),
                    "rain_ignored": limits_rain.rain_ignored,
                    "deficit_mm": round(planned.deficit_mm, 2),
                    "raw_mm": round(planned.raw_mm, 2),
                    "waters": planned.scheduled,
                    "runtime_min": planned.runtime_min,
                    "cycles": list(planned.cycles),
                    "soak_min": planned.soak_min,
                    "max_cycle_min": planned.max_cycle_min,
                    "starts": starts,
                    "gallons": None if gallons is None else round(gallons, 1),
                    "reason": planned.reason,
                    "valve": zone.data.get("valve_entity"),
                }
            )
            total_runtime += float(planned.runtime_min)
            # Credit the net depth the plan would have applied. Same subtraction
            # as mark_watered. The valve id is never called.
            if planned.scheduled:
                deficits[zone.zone_id] = max(0.0, planned.deficit_mm - planned.net_mm)
            else:
                deficits[zone.zone_id] = planned.deficit_mm
        day_rows.append(
            {
                "date": current.isoformat(),
                "weekday": current.strftime("%a"),
                "high_f": round(day.high_f, 1),
                "low_f": round(day.low_f, 1),
                "humidity_pct": day.humidity_pct,
                "wind_mph": round(day.wind_m_s / 0.44704, 1),
                "cloud": day.cloud,
                "rain_in": round(day.rain_in, 2),
                "et0_mm": round(et0, 2),
                "et_detail": et_detail,
                "zones": zone_rows,
            }
        )

    name = SCENARIO_NAMES.get(scenario or "", "Custom week")
    result = {
        "scenario": scenario,
        "scenario_name": name,
        "bucket": bucket,
        "start_date": start.isoformat(),
        "would_execute": False,
        "note": "Virtual run only. No valve, switch, or controller was called.",
        "total_runtime_min": total_runtime,
        "days": day_rows,
        "summary": plan.summary if day_rows else "",
    }
    result["markdown"] = render_markdown(result)
    return result


def render_markdown(result: dict[str, Any]) -> str:
    """A weekly table a markdown card can show."""
    lines = [
        f"## {result['scenario_name']}",
        "",
        result["note"],
        "Each row is that day's weather and soil. Start times are the next morning, at the start time.",
        f"Soil water at the start: {result['bucket']}.",
        "",
        "| Day | Zone | Water loss mm | Rain in | Rain counted in | Water needed mm | Water | Minutes | Cycles | Start | Gallons | Why |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- | ---: | --- |",
    ]
    for day in result["days"]:
        for zone in day["zones"]:
            cycles = "+".join(str(minutes) for minutes in zone["cycles"]) or "—"
            if zone["waters"] and zone["soak_min"]:
                cycles = f"{cycles}, soak {zone['soak_min']}"
            starts = ", ".join(zone["starts"]) or "—"
            gallons = "—" if zone["gallons"] is None else f"{zone['gallons']:.0f}"
            effective_in = mm_to_inches(zone["effective_rain_mm"])
            water = "yes" if zone["waters"] else "no"
            why = zone["reason"] if not zone["waters"] else "Due"
            lines.append(
                "| {day} | {name} | {et0:.1f} | {rain:.2f} | {eff:.2f} | {deficit:.1f} | {water} | {minutes} | {cycles} | {starts} | {gallons} | {why} |".format(
                    day=f"{day['weekday']} {day['date'][5:]}",
                    name=zone["name"],
                    et0=day["et0_mm"],
                    rain=day["rain_in"],
                    eff=effective_in,
                    deficit=zone["deficit_mm"],
                    water=water,
                    minutes=zone["runtime_min"],
                    cycles=cycles,
                    starts=starts,
                    gallons=gallons,
                    why=why,
                )
            )
    lines.append("")
    lines.append(f"Total runtime {result['total_runtime_min']:.0f} min.")
    return "\n".join(lines)


def _et0_mm(day: WeatherDay, current: date, settings: SimSettings) -> tuple[float, str]:
    ra = extraterrestrial_radiation_mj(settings.latitude, current.timetuple().tm_yday)
    sunshine = 1.0 - min(1.0, max(0.0, day.cloud))
    rs = radiation_from_sunshine_mj(ra, sunshine)
    result = daily_et0(
        ETInputs(
            t_max_c=day.high_c,
            t_min_c=day.low_c,
            latitude_deg=settings.latitude,
            day_of_year=current.timetuple().tm_yday,
            elevation_m=settings.elevation_m,
            rh_mean_pct=day.humidity_pct,
            wind_m_s=day.wind_m_s,
            wind_height_m=settings.wind_height_m,
            rs_mj_m2_day=rs,
        )
    )
    if result.et0_mm is None:
        raise ValueError(result.detail)
    return result.et0_mm, result.detail


def _area(data: dict[str, Any]) -> float | None:
    value = data.get(CONF_AREA_SQFT)
    if value in (None, ""):
        return None
    return float(value)


def _plan_evening(
    *,
    zones: tuple[SimZone, ...],
    deficits: dict[str, float],
    et0: float,
    month: int,
    rain_mm: float,
    evening: datetime,
    tomorrow_rain_mm: float,
    settings: SimSettings,
    schedule_days: tuple[str, ...] | None,
    blackout_start: int | None,
    blackout_end: int | None,
) -> tuple[NightPlan, dict[str, Any]]:
    """Commit the day's ET and rain, then call ``build_plan``.

    The deficit uses ``build_zone_request`` for crop ET and total available
    water, the same resolution the live coordinator stores before it plans.
    """
    requests = []
    balances: dict[str, Any] = {}
    for zone in zones:
        preview = build_zone_request(
            zone_id=zone.zone_id,
            name=zone.name,
            data=zone.data,
            deficit_mm=deficits[zone.zone_id],
            et0_mm=et0,
            month=month,
            enabled=zone.enabled,
            rain_sensor_wet=False,
            skipped_until=zone.skipped_until,
            adjustment_pct=zone.adjustment_pct,
            drip_ignores_schedule=settings.drip_ignores_schedule,
        )
        updated = apply_daily_balance(
            deficits[zone.zone_id],
            preview.taw_mm,
            etc_mm=preview.etc_mm,
            precip_mm=rain_mm,
            et0_mm=et0,
        )
        balances[zone.zone_id] = updated
        requests.append(
            build_zone_request(
                zone_id=zone.zone_id,
                name=zone.name,
                data=zone.data,
                deficit_mm=updated.deficit_mm,
                et0_mm=et0,
                month=month,
                enabled=zone.enabled,
                rain_sensor_wet=False,
                skipped_until=zone.skipped_until,
                adjustment_pct=zone.adjustment_pct,
                drip_ignores_schedule=settings.drip_ignores_schedule,
            )
        )
    earliest, start_at, finish_by = morning_window(
        evening,
        settings.earliest_start,
        settings.start_time,
        settings.finish_time,
    )
    plan = build_plan(
        PlanRequest(
            zones=tuple(requests),
            start_at=start_at,
            finish_by=finish_by,
            earliest_start=earliest,
            forecast_precip_mm=tomorrow_rain_mm,
            forecast_skip_mm=settings.forecast_skip_mm,
            hub_rain_wet=False,
            mode=settings.mode,
            automatic=False,
            max_daily_runtime_min=settings.max_daily_runtime_min,
            allowed_weekdays=schedule_days,
            blackout_start_hour=blackout_start,
            blackout_end_hour=blackout_end,
            whole_minutes=settings.whole_minutes,
        )
    )
    return plan, balances
