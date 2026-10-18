"""Project the next seven mornings with the live planner.

Day 0 uses the deficit already stored (today's ET is already in it when the
evening balance has run). Each later day adds one more day of the same crop
ET and no rain. Future rain is not assumed. A scheduled day refills by the
planned net depth and resets the days-since-watering counter.

Each row is dated by the morning the valves open: the first cycle's start,
or the sunrise deadline when nothing is scheduled. A sequence that starts
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
from .solar import next_sunrise
from .units import mm_to_inches


def project_week(
    zones: tuple[ZoneRequest, ...],
    *,
    now: datetime,
    latitude: float,
    longitude: float,
    timezone: str,
    sunrise_buffer_min: int,
    earliest_hour: int | None,
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
    deficits = {zone.zone_id: zone.deficit_mm for zone in zones}
    since = {zone.zone_id: zone.days_since_water for zone in zones}
    taw = {zone.zone_id: zone.taw_mm for zone in zones}
    etc = {zone.zone_id: zone.etc_mm for zone in zones}
    rows: list[dict[str, object]] = []
    waiting = {zone.zone_id: int((defer_days or {}).get(zone.zone_id, 0)) for zone in zones}

    for offset in range(days):
        moment = local_now + timedelta(days=offset)
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
        evening = moment.replace(hour=min(23, moment.hour), minute=0, second=0, microsecond=0)
        if offset > 0:
            evening = moment.replace(hour=23, minute=0, second=0, microsecond=0)
        rise = next_sunrise(latitude, longitude, evening)
        finish_by = rise.astimezone(tz) - timedelta(minutes=sunrise_buffer_min)
        earliest = None
        if earliest_hour is not None:
            earliest = finish_by.replace(
                hour=earliest_hour, minute=0, second=0, microsecond=0
            )
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
    return {
        "summary": summary,
        "days": rows,
        "markdown": render_markdown(rows),
        "note": (
            "Later days repeat today's crop ET and assume no rain. "
            "A skip on a later day can change when the real morning arrives."
        ),
    }


def render_markdown(days: list[dict[str, object]]) -> str:
    """A table a markdown card can show as-is."""
    lines = [
        "Next 7 days. Later days repeat today's crop ET and assume no rain.",
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

    A scheduled night uses the first cycle. A skip still names the morning
    the valves would have opened, which is ``run_on``.
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
    text = f"{len(planned)} waterings · next {first_day} {first['name']}"
    return text[:255]
