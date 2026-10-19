"""Project upcoming mornings with the live planner.

Day 0 uses the deficit already stored (today's ET is already in it when the
evening balance has run). Each later day adds one more day of the same crop
ET and no rain. Future rain is not assumed. A scheduled day refills by the
planned net depth and resets the days-since-watering counter, so the next
watering day sees the bucket after this one.

The projection keeps every calendar day. The schedule the sensor shows keeps
only mornings when at least one zone waters, and only as many of those as the
user allowed weekdays (every day means seven). Each of those rows is the full
plan: local start and finish, and each zone's cycles, times, depth, gallons,
and soak.

Each row is dated by the morning the valves open: the first cycle's start,
or the target start time when nothing is scheduled. A sequence that starts
before midnight is dated that evening, and any later cycle shows its own date.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .balance import apply_daily_balance
from .const import WEEKDAYS
from .flow import expected_gallons
from .forecast_rain import defer_reason
from .planner import NightPlan, PlanRequest, ZoneRequest, build_plan
from .schedule import morning_window, parse_clock, wall_clock
from .solar import local_sunrise
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
    et_factors: list[float] | None = None,
    dynamic_start: bool = False,
    latitude: float | None = None,
    longitude: float | None = None,
    elevation_m: float = 0.0,
) -> dict[str, object]:
    """Return ``days``, a short ``summary``, and a markdown table."""
    tz = ZoneInfo(timezone)
    local_now = now.astimezone(tz)
    first_earliest, first_start, first_finish = morning_window(
        local_now, earliest_start, start_time, finish_time
    )
    earliest_hm = parse_clock(earliest_start, "04:00:00")
    start_hm = parse_clock(start_time, "05:00:00")
    finish_hm = parse_clock(finish_time, "09:00:00")
    first_day = first_start.date()
    deficits = {zone.zone_id: zone.deficit_mm for zone in zones}
    since = {zone.zone_id: zone.days_since_water for zone in zones}
    taw = {zone.zone_id: zone.taw_mm for zone in zones}
    etc = {zone.zone_id: zone.etc_mm for zone in zones}
    rows: list[dict[str, object]] = []
    waiting = {zone.zone_id: int((defer_days or {}).get(zone.zone_id, 0)) for zone in zones}

    for offset in range(days):
        if offset > 0:
            scale = 1.0
            if et_factors is not None and offset < len(et_factors):
                scale = max(0.0, float(et_factors[offset]))
            for zone in zones:
                updated = apply_daily_balance(
                    deficits[zone.zone_id],
                    taw[zone.zone_id],
                    etc_mm=etc[zone.zone_id] * scale,
                    precip_mm=0.0,
                    et0_mm=0.0,
                )
                deficits[zone.zone_id] = updated.deficit_mm
                if since[zone.zone_id] is not None:
                    since[zone.zone_id] = int(since[zone.zone_id]) + 1
        day = first_day + timedelta(days=offset)
        earliest = wall_clock(day, *earliest_hm, tz)
        start_at = wall_clock(day, *start_hm, tz)
        finish_by = wall_clock(day, *finish_hm, tz)
        sunrise = None
        if dynamic_start and latitude is not None and longitude is not None:
            try:
                sunrise = local_sunrise(
                    latitude, longitude, day, tz, elevation_m
                )
            except ValueError:
                sunrise = None
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
                dynamic_start=dynamic_start,
                sunrise_at=sunrise,
            )
        )
        row = _day_row(plan, areas, tz)
        row["offset"] = offset
        rows.append(row)
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
    if dynamic_start:
        window = (
            f"Dynamic start, aims to finish at sunrise, "
            f"finish by {first_finish.strftime('%H:%M')}, "
            f"don't start before {first_earliest.strftime('%H:%M')}."
        )
    else:
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
            "Later days use the forecast or the recent water-loss average and "
            "assume no rain. A skip on a later day can change when the real morning arrives."
        ),
    }


def render_markdown(days: list[dict[str, object]], window: str = "") -> str:
    """A table a markdown card can show as-is."""
    intro = (
        "Next 7 days. Later days use the forecast or the recent water-loss "
        "average and assume no rain."
    )
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
    events_by_zone: dict[str, list] = {}
    for event in plan.timeline:
        events_by_zone.setdefault(event.zone_id, []).append(event)
    start = ""
    finish = ""
    start_at = ""
    finish_at = ""
    if plan.timeline:
        first = plan.timeline[0].start.astimezone(tz)
        last = plan.timeline[-1].end.astimezone(tz)
        start = _format_start(first, day, tz)
        finish = _format_start(last, day, tz)
        start_at = first.isoformat()
        finish_at = last.isoformat()
    zones = []
    for zone in plan.zones:
        events = events_by_zone.get(zone.zone_id, [])
        bursts = []
        for event in events:
            last_cycle = event.cycle_index >= event.cycle_count
            bursts.append(
                {
                    "cycle": event.cycle_index,
                    "of": event.cycle_count,
                    "minutes": event.duration_min,
                    "start": _format_start(event.start, day, tz),
                    "end": _format_start(event.end, day, tz),
                    "soak_min": 0 if last_cycle else zone.soak_min,
                }
            )
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
                "starts": ", ".join(str(burst["start"]) for burst in bursts),
                "minutes": zone.runtime_min,
                "mm": round(zone.net_mm, 2),
                "inches": round(mm_to_inches(zone.net_mm), 3) if zone.scheduled else 0.0,
                "gallons": None if gallons is None else round(gallons, 1),
                "cycles": list(zone.cycles),
                "soak_min": zone.soak_min if zone.scheduled else 0,
                "bursts": bursts,
                "note": (
                    f"{zone.carried_min:.0f} min carries to the next allowed day."
                    if zone.scheduled and zone.carried_min >= 0.5
                    else ""
                ),
            }
        )
    return {
        "date": day,
        "start": start,
        "finish": finish,
        "start_at": start_at,
        "finish_at": finish_at,
        "zones": zones,
    }


def watering_day_limit(allowed_weekdays: tuple[str, ...] | None) -> int:
    """How many upcoming watering days the schedule lists.

    None means every day, which lists seven watering mornings. An empty
    selection lists none. Any other selection lists one watering morning
    per chosen weekday, however far apart those mornings are.
    """
    if allowed_weekdays is None:
        return len(WEEKDAYS)
    return len(allowed_weekdays)


def select_watering_days(
    days: list[dict[str, object]],
    *,
    limit: int,
    forecast_horizon_days: int,
) -> list[dict[str, object]]:
    """The next watering mornings, skipping days when nothing runs.

    ``estimated`` is set only when the morning is past the weather forecast.
    The date and clocks stay exact either way.
    """
    if limit <= 0:
        return []
    chosen: list[dict[str, object]] = []
    for day in days:
        zones = [
            zone
            for zone in list(day.get("zones") or [])
            if isinstance(zone, dict) and zone.get("scheduled")
        ]
        if not zones:
            continue
        offset = int(day.get("offset") or 0)  # type: ignore[arg-type]
        past_forecast = forecast_horizon_days > 0 and offset >= forecast_horizon_days
        chosen.append(
            {
                "date": day.get("date"),
                "start": day.get("start") or "",
                "finish": day.get("finish") or "",
                "start_at": day.get("start_at") or "",
                "finish_at": day.get("finish_at") or "",
                "estimated": past_forecast,
                "zones": zones,
            }
        )
        if len(chosen) >= limit:
            break
    return chosen


def render_watering_markdown(
    days: list[dict[str, object]], window: str = "", horizon: int | None = None
) -> str:
    """The watering-day list, with exact dates and times and no estimate wording."""
    if horizon is None:
        horizon = OUTLOOK_DAYS
    count = len(days)
    if count == 0:
        intro = f"No watering days in the next {horizon} days."
    elif count == 1:
        intro = "Next watering day."
    else:
        intro = f"Next {count} watering days."
    intro += (
        " Days with no watering are left out. Later days use the forecast "
        "or the recent water-loss average and assume no rain."
    )
    if window:
        intro = f"{intro} {window}"
    lines = [intro, ""]
    for day in days:
        start = str(day.get("start") or "—")
        finish = str(day.get("finish") or "—")
        lines.append(f"{day.get('date')} {start}–{finish}")
        zones = list(day.get("zones") or [])
        if not zones:
            lines.append("- No zones.")
            lines.append("")
            continue
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            gallons = zone.get("gallons")
            gal = "" if gallons is None else f", {float(gallons):.0f} gal"
            soak = int(zone.get("soak_min") or 0)
            lines.append(
                f"- {zone['name']}: {zone['minutes']} min, "
                f"{float(zone['inches']):.2f} in ({float(zone['mm']):.1f} mm){gal}, "
                f"soak {soak} min"
            )
            note = str(zone.get("note") or "")
            if note:
                lines.append(f"  {note}")
            for burst in list(zone.get("bursts") or []):
                if not isinstance(burst, dict):
                    continue
                soak_after = int(burst.get("soak_min") or 0)
                soak_text = f", soak {soak_after} min" if soak_after else ""
                lines.append(
                    f"  {burst['cycle']}/{burst['of']} {burst['start']}–{burst['end']} "
                    f"({burst['minutes']} min{soak_text})"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


FIRM_DAYS = 7
OUTLOOK_DAYS = 365


def split_outlook(
    full: dict[str, object],
    *,
    timezone: str,
    firm_days: int = FIRM_DAYS,
    horizon: int = OUTLOOK_DAYS,
    allowed_weekdays: tuple[str, ...] | None = None,
    forecast_horizon_days: int = 0,
    watering_days: int | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Keep the next watering days, and a year-long outlook for each zone.

    ``watering_days`` overrides the count. Otherwise the count is the number
    of allowed weekdays (seven when every day is allowed). Calendar days with
    no watering are left out. ``firm_days`` still decides which next-run
    dates count as this week's plan in the per-zone outlook.
    """
    days = [day for day in list(full.get("days") or []) if isinstance(day, dict)]
    limit = watering_day_limit(allowed_weekdays) if watering_days is None else watering_days
    shown = select_watering_days(
        days, limit=limit, forecast_horizon_days=forecast_horizon_days
    )
    window = str(full.get("window") or "")
    summary = ""
    if shown and shown[0].get("start_at"):
        summary = exact_next_text(datetime.fromisoformat(str(shown[0]["start_at"])))
    elif not shown:
        summary = f"No watering days in the next {horizon} days"
    week = {
        "summary": summary[:255],
        "days": shown,
        "markdown": render_watering_markdown(shown, window, horizon),
        "window": window,
        "note": full.get("note") or "",
    }
    return week, describe_outlook(
        days, timezone=timezone, firm_days=firm_days, horizon=horizon
    )


def describe_outlook(
    days: list[dict[str, object]],
    *,
    timezone: str,
    firm_days: int = 7,
    horizon: int = OUTLOOK_DAYS,
) -> dict[str, object]:
    """First morning each zone would water.

    A date inside ``firm_days`` is this week's plan. A later date still has
    an exact local time; ``estimated`` is true only as an attribute. A zone
    with no date inside ``horizon`` keeps a note that says why.
    """
    tz = ZoneInfo(timezone)
    found: dict[str, dict[str, object]] = {}
    pending: dict[str, str] = {}
    names: dict[str, str] = {}
    last_date = ""
    for index, day in enumerate(days):
        last_date = str(day.get("date") or last_date)
        for zone in list(day.get("zones") or []):
            if not isinstance(zone, dict):
                continue
            zone_id = str(zone["zone_id"])
            reason = str(zone.get("reason") or "")
            names[zone_id] = str(zone.get("name") or names.get(zone_id, ""))
            if zone.get("scheduled") and zone_id not in found:
                found[zone_id] = {
                    "at": _at(str(day["date"]), str(zone.get("starts") or ""), tz),
                    "estimated": index >= firm_days,
                    "note": "",
                    "name": names[zone_id],
                }
                continue
            if zone_id not in found:
                pending[zone_id] = reason
    before = date.fromisoformat(last_date) + timedelta(days=1) if last_date else None
    for zone_id, reason in pending.items():
        if zone_id in found:
            continue
        found[zone_id] = {
            "at": None,
            "estimated": False,
            "note": _no_date_note(reason, before, horizon),
            "name": names.get(zone_id, ""),
        }
    dated = [item for item in found.values() if item.get("at") is not None]
    if dated:
        earliest = min(dated, key=lambda item: item["at"])  # type: ignore[arg-type, return-value]
        if earliest["estimated"]:
            summary = exact_next_text(earliest["at"])  # type: ignore[arg-type]
        else:
            summary = ""
    elif found:
        summary = next(
            (str(item["note"]) for item in found.values() if item.get("note")),
            "",
        )
    else:
        summary = ""
    return {"by_zone": found, "summary": summary}


def exact_next_text(moment: datetime) -> str:
    """Exact local weekday, month, day, and clock. No estimate wording."""
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    return (
        f"Next watering {moment.strftime('%a')} {moment.strftime('%b')} {moment.day}, "
        f"{hour}:{moment.minute:02d} {suffix}"
    )


def _no_date_note(reason: str, before: date | None, horizon: int) -> str:
    """Why a zone has no next watering inside the projection."""
    if reason.startswith("Zone is disabled"):
        return "Zone is disabled"
    if reason.startswith("Dormant") or "Regular watering is off" in reason:
        if before is None:
            return "Dormant. Regular watering is off."
        return f"Dormant, no watering expected before {_long_date(before)}"
    return f"No watering projected in the next {horizon} days."


def _long_date(day: date) -> str:
    return f"{day.strftime('%b')} {day.day}, {day.year}"


def _at(date_text: str, starts: str, tz: ZoneInfo) -> datetime:
    clock = (starts or "05:00").split(",")[0].strip() or "05:00"
    if " " in clock:
        date_text, clock = clock.split()[:2]
    hour_text, minute_text = clock.split(":")[:2]
    year_text, month_text, day_text = date_text.split("-")
    return wall_clock(
        date(int(year_text), int(month_text), int(day_text)),
        int(hour_text),
        int(minute_text),
        tz,
    )


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
