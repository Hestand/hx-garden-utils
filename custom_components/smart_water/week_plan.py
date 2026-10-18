"""Project the next seven mornings with the live planner.

Day 0 uses the deficit already stored (today's ET is already in it when the
evening balance has run). Each later day adds one more day of the same crop
ET and no rain. Future rain is not assumed. A scheduled day refills by the
planned net depth and resets the days-since-watering counter.

Each row is dated by the morning the valves open: the first cycle's start,
or the target start time when nothing is scheduled. A sequence that starts
before midnight is dated that evening, and any later cycle shows its own date.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .balance import apply_daily_balance
from .flow import expected_gallons
from .forecast_rain import defer_reason
from .planner import NightPlan, PlanRequest, ZoneRequest, build_plan
from .schedule import morning_window
from .units import mm_to_inches


def project_week(
    zones: tuple[ZoneRequest, ...],
    *,
    now: datetime,
    timezone: str,
    earliest_start: str = "04:00:00",
    start_time: str = "05:00:00",
    finish_time: str = "09:00:00",
    forecast_precip_mm: float,
    forecast_skip_mm: float | None,
    hub_rain_wet: bool,
    mode: str,
    automatic: bool,
    allowed_weekdays: tuple[str, ...] | None,
    blackout_start_hour: int | None,
    blackout_end_hour: int | None,
    whole_minutes: bool,
    max_daily_runtime_min: int | None,
    areas: dict[str, float | None],
    days: int = 7,
    max_run_min: float | None = None,
    hourly_wind: tuple[tuple[datetime, float], ...] = (),
    forecast_expected_mm: float = 0.0,
    forecast_probability_pct: float | None = None,
    forecast_probability_min: float = 60.0,
    forecast_defer_max: int = 2,
    forecast_horizon_days: int = 0,
    forecast_threshold_mm: float | None = None,
    defer_days: dict[str, int] | None = None,
) -> dict[str, object]:
    """Return ``days``, a short ``summary``, and a markdown table."""
    tz = ZoneInfo(timezone)
    local_now = now.astimezone(tz)
    first_earliest, first_start, first_finish = morning_window(
        local_now, earliest_start, start_time, finish_time
    )
    deficits = {zone.zone_id: zone.deficit_mm for zone in zones}
    since = {zone.zone_id: zone.days_since_water for zone in zones}
    taw = {zone.zone_id: zone.taw_mm for zone in zones}
    etc = {zone.zone_id: zone.etc_mm for zone in zones}
    rows: list[dict[str, object]] = []
    waiting = {zone.zone_id: int((defer_days or {}).get(zone.zone_id, 0)) for zone in zones}

    for offset in range(days):
        if offset > 0:
            for zone in zones:
                updated = apply_daily_balance(
                    deficits[zone.zone_id],
                    taw[zone.zone_id],
                    etc_mm=etc[zone.zone_id],
                    precip_mm=0.0,
                    et0_mm=0.0,
                )
                deficits[zone.zone_id] = updated.deficit_mm
                if since[zone.zone_id] is not None:
                    since[zone.zone_id] = int(since[zone.zone_id]) + 1
        earliest = first_earliest + timedelta(days=offset)
        start_at = first_start + timedelta(days=offset)
        finish_by = first_finish + timedelta(days=offset)
        requests = []
        for zone in zones:
            current = replace(
                zone,
                deficit_mm=deficits[zone.zone_id],
                days_since_water=since[zone.zone_id],
            )
            if offset > 0:
                current = replace(
                    current,
                    rain_sensor_wet=False,
                    currently_raining=False,
                    recent_rain_mm=0.0,
                    temp_f=None,
                    forecast_low_f=None,
                    wind_mph=None,
                )
            if forecast_probability_pct is not None:
                if offset >= forecast_horizon_days:
                    reason = None
                else:
                    reason = defer_reason(
                        expected_mm=forecast_expected_mm,
                        probability_pct=forecast_probability_pct,
                        probability_min=forecast_probability_min,
                        deficit_mm=deficits[zone.zone_id],
                        threshold_mm=forecast_threshold_mm,
                        days_used=waiting.get(zone.zone_id, 0),
                        max_days=forecast_defer_max,
                    )
                current = replace(current, forecast_defer_reason=reason)
            requests.append(current)
        plan = build_plan(
            PlanRequest(
                zones=tuple(requests),
                start_at=start_at,
                finish_by=finish_by,
                earliest_start=earliest,
                forecast_precip_mm=forecast_precip_mm if offset == 0 else 0.0,
                forecast_skip_mm=forecast_skip_mm,
                hub_rain_wet=hub_rain_wet if offset == 0 else False,
                mode=mode,
                automatic=automatic,
                max_daily_runtime_min=max_daily_runtime_min,
                allowed_weekdays=allowed_weekdays,
                blackout_start_hour=blackout_start_hour,
                blackout_end_hour=blackout_end_hour,
                whole_minutes=whole_minutes,
                max_run_min=max_run_min,
                hourly_wind=hourly_wind if offset == 0 else (),
            )
        )
        rows.append(_day_row(plan, areas, tz))
        for zone_plan in plan.zones:
            if (zone_plan.reason or "").startswith("Deferred for forecast rain"):
                waiting[zone_plan.zone_id] = waiting.get(zone_plan.zone_id, 0) + 1
                continue
            if zone_plan.scheduled:
                waiting[zone_plan.zone_id] = 0
            if not zone_plan.scheduled:
                continue
            deficits[zone_plan.zone_id] = max(
                0.0, deficits[zone_plan.zone_id] - zone_plan.net_mm
            )
            remaining = deficits[zone_plan.zone_id]
            # A capped night that is still at RAW can finish on the next
            # allowed day. A finished night starts the minimum interval.
            if zone_plan.completed or remaining < zone_plan.raw_mm:
                since[zone_plan.zone_id] = 0

    summary = _summary(rows)
    window = (
        f"Start {first_start.strftime('%H:%M')}, finish by {first_finish.strftime('%H:%M')}, "
        f"earliest {first_earliest.strftime('%H:%M')}."
    )
    return {
        "summary": summary,
        "days": rows,
        "markdown": render_markdown(rows, window),
        "window": window,
        "note": (
            "Later days repeat today's crop ET and assume no rain. "
            "A skip on a later day can change when the real morning arrives."
        ),
    }


def render_markdown(days: list[dict[str, object]], window: str = "") -> str:
    """A table a markdown card can show as-is."""
    intro = "Next 7 days. Later days repeat today's crop ET and assume no rain."
    if window:
        intro = f"{intro} {window}"
    lines = [
        intro,
        "",
        "| Date | Zone | Starts | Minutes | Depth | Gallons | Note |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for day in days:
        for zone in list(day["zones"]):
            assert isinstance(zone, dict)
            if zone["scheduled"]:
                depth = f"{zone['inches']:.2f} in ({zone['mm']:.1f} mm)"
                gallons = "—" if zone["gallons"] is None else f"{zone['gallons']:.0f}"
                note = str(zone.get("note") or "")
            else:
                depth = "—"
                gallons = "—"
                note = str(zone.get("note") or zone["reason"])
            lines.append(
                "| {date} | {name} | {starts} | {minutes} | {depth} | {gallons} | {note} |".format(
                    date=day["date"],
                    name=zone["name"],
                    starts=zone["starts"] or "—",
                    minutes=zone["minutes"] if zone["scheduled"] else "—",
                    depth=depth,
                    gallons=gallons,
                    note=note,
                )
            )
    if len(lines) == 4:
        lines.append("| — | — | — | — | — | — | No zones. |")
    return "\n".join(lines)


def _label_moment(plan: NightPlan) -> datetime:
    """The calendar moment this row describes.

    A scheduled morning uses the first cycle. A skip still names the target
    start, which is ``run_on``.
    """
    if plan.timeline:
        return plan.timeline[0].start
    return plan.run_on


def _format_start(moment: datetime, row_day: str, tz: ZoneInfo) -> str:
    """Clock time, plus the date when this cycle is not on the row's day."""
    local = moment.astimezone(tz)
    clock = local.strftime("%H:%M")
    if local.date().isoformat() == row_day:
        return clock
    return f"{local.date().isoformat()} {clock}"


def _day_row(
    plan: NightPlan, areas: dict[str, float | None], tz: ZoneInfo
) -> dict[str, object]:
    day = _label_moment(plan).astimezone(tz).date().isoformat()
    by_zone: dict[str, list[str]] = {}
    for event in plan.timeline:
        by_zone.setdefault(event.zone_id, []).append(
            _format_start(event.start, day, tz)
        )
    zones = []
    for zone in plan.zones:
        gallons = None
        if zone.scheduled:
            gallons = expected_gallons(
                runtime_min=float(zone.runtime_min),
                precipitation_rate_in_hr=zone.precipitation_rate_in_hr,
                area_sqft=areas.get(zone.zone_id),
                flow_gpm=None,
            )
        zones.append(
            {
                "zone_id": zone.zone_id,
                "name": zone.name,
                "scheduled": zone.scheduled,
                "reason": zone.reason,
                "starts": ", ".join(by_zone.get(zone.zone_id, [])),
                "minutes": zone.runtime_min,
                "mm": round(zone.net_mm, 2),
                "inches": round(mm_to_inches(zone.net_mm), 3) if zone.scheduled else 0.0,
                "gallons": None if gallons is None else round(gallons, 1),
                "cycles": list(zone.cycles),
                "note": (
                    f"{zone.carried_min:.0f} min carries to the next allowed day."
                    if zone.scheduled and zone.carried_min >= 0.5
                    else ""
                ),
            }
        )
    return {"date": day, "zones": zones}


def _summary(days: list[dict[str, object]]) -> str:
    planned = [
        (str(day["date"]), zone)
        for day in days
        for zone in list(day["zones"])
        if isinstance(zone, dict) and zone["scheduled"]
    ]
    if not planned:
        return "No watering in the next 7 days"
    first_day, first = planned[0]
    assert isinstance(first, dict)
    start = str(first.get("starts") or "").split(",")[0].strip()
    clock = f" {start}" if start else ""
    text = f"{len(planned)} waterings · next {first_day}{clock} {first['name']}"
    return text[:255]
