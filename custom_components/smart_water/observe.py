"""Daily accumulation of temperature, rain, and solar from Home Assistant entities.

Samples are folded into one local day. A new date starts a new total. The
weather entity remains the fallback when a sensor is absent. Instantaneous
W/m² (a Tempest solar reading, or a UV index converted with
``UV_INDEX_TO_W_M2``) is integrated to MJ/m²/day so Penman-Monteith can use
it. A sensor that already reports daily MJ is not integrated.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .const import (
    RAIN_KIND_CUMULATIVE,
    RAIN_KIND_DAILY,
    RAIN_KIND_RATE,
    UV_INDEX_TO_W_M2,
)

# Ignore rate gaps longer than this. An hourly coordinator is well inside it.
_MAX_GAP_HOURS = 6.0


def fresh_day(date: str) -> dict[str, object]:
    """Empty accumulation for one local date."""
    return {
        "date": date,
        "t_max_c": None,
        "t_min_c": None,
        "rain_mm": 0.0,
        "rain_cursor": None,
        "rain_last_at": None,
        "solar_mj": 0.0,
        "solar_last_w": None,
        "solar_last_at": None,
        "effective_rain_mm": 0.0,
        "rain_ignored": False,
        "precip_source": "none",
        "rain_events": [],
    }


def note_temperature(track: dict[str, object], temp_c: float) -> None:
    """Widen the day's observed high and low."""
    high = track["t_max_c"]
    low = track["t_min_c"]
    track["t_max_c"] = temp_c if high is None else max(float(high), temp_c)
    track["t_min_c"] = temp_c if low is None else min(float(low), temp_c)


def note_rain(
    track: dict[str, object],
    *,
    kind: str,
    value_mm: float,
    at: datetime,
) -> None:
    """Fold one rain reading into today's millimeters.

    ``daily_total`` replaces the total (Tempest "rain today"). ``cumulative``
    adds the increase of a monotonic counter and ignores the first sample so
    history before install is not credited. ``rate`` is mm/h, trapezoid-integrated
    between samples.
    """
    if kind == RAIN_KIND_DAILY:
        previous = track.get("rain_cursor")
        track["rain_mm"] = max(0.0, value_mm)
        if previous is None:
            _add_rain_event(track, at, float(track["rain_mm"]))
        else:
            delta = float(track["rain_mm"]) - max(0.0, float(previous))
            if delta > 0:
                _add_rain_event(track, at, delta)
            elif delta < 0:
                # A lower daily total is a correction of today's count, not a
                # deletion of rain that already fell on an earlier date.
                _reduce_rain_events(track, at, -delta, same_day=True)
        track["rain_cursor"] = value_mm
        track["rain_last_at"] = at.isoformat()
        return
    cursor = track["rain_cursor"]
    if kind == RAIN_KIND_CUMULATIVE:
        if cursor is None:
            track["rain_cursor"] = value_mm
        else:
            delta = value_mm - float(cursor)
            if delta > 0:
                track["rain_mm"] = float(track["rain_mm"]) + delta
                _add_rain_event(track, at, delta)
            track["rain_cursor"] = value_mm
        track["rain_last_at"] = at.isoformat()
        return
    if kind != RAIN_KIND_RATE:
        raise ValueError(f"unknown rain kind {kind}")
    last = track["rain_last_at"]
    if last is not None and cursor is not None:
        previous = datetime.fromisoformat(str(last))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=at.tzinfo)
        hours = (at - previous).total_seconds() / 3600.0
        if 0 < hours <= _MAX_GAP_HOURS:
            average = (float(cursor) + value_mm) / 2.0
            added = max(0.0, average) * hours
            track["rain_mm"] = float(track["rain_mm"]) + added
            _add_rain_event(track, at, added)
    track["rain_cursor"] = value_mm
    track["rain_last_at"] = at.isoformat()


def _event_time(event: dict[str, object], fallback: datetime) -> datetime:
    moment = datetime.fromisoformat(str(event["at"]))
    if moment.tzinfo is None and fallback.tzinfo is not None:
        moment = moment.replace(tzinfo=fallback.tzinfo)
    return moment


def _add_rain_event(track: dict[str, object], at: datetime, mm: float) -> None:
    """Record a positive amount and drop events older than 48 hours."""
    if mm <= 0:
        return
    events = [dict(event) for event in list(track.get("rain_events") or [])]
    events.append({"at": at.isoformat(), "mm": mm})
    track["rain_events"] = _prune_events(events, at)


def _reduce_rain_events(
    track: dict[str, object], at: datetime, mm: float, *, same_day: bool
) -> None:
    """Shrink the newest matching events by ``mm``."""
    events = [dict(event) for event in list(track.get("rain_events") or [])]
    remaining = mm
    day = at.date().isoformat()
    for event in reversed(events):
        if remaining <= 0:
            break
        moment = _event_time(event, at)
        if same_day and moment.date().isoformat() != day:
            continue
        take = min(float(event["mm"]), remaining)
        event["mm"] = float(event["mm"]) - take
        remaining -= take
    track["rain_events"] = _prune_events(
        [event for event in events if float(event["mm"]) > 0], at
    )


def _prune_events(events: list[dict[str, object]], at: datetime) -> list[dict[str, object]]:
    cutoff = at - timedelta(hours=48)
    kept = []
    for event in events:
        if _event_time(event, at) >= cutoff:
            kept.append(event)
    return kept


def rain_between(
    track: dict[str, object], since: datetime, until: datetime
) -> float:
    """Sum recorded rain with timestamps in ``[since, until]``."""
    total = 0.0
    for event in list(track.get("rain_events") or []):
        moment = _event_time(dict(event), until)
        if since <= moment <= until:
            total += float(event["mm"])
    return total


def rain_in_hours(track: dict[str, object], hours: float, at: datetime) -> float:
    """Sum recorded rain in the last ``hours`` ending at ``at``."""
    return rain_between(track, at - timedelta(hours=hours), at)


def note_solar_w(track: dict[str, object], watts_m2: float, at: datetime) -> None:
    """Integrate W/m² into MJ/m² with the trapezoid rule."""
    last = track["solar_last_at"]
    previous_w = track["solar_last_w"]
    if last is not None and previous_w is not None:
        previous = datetime.fromisoformat(str(last))
        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=at.tzinfo)
        hours = (at - previous).total_seconds() / 3600.0
        if 0 < hours <= _MAX_GAP_HOURS:
            average = (float(previous_w) + watts_m2) / 2.0
            # W/m² × hours × 3600 J/Wh / 1e6 = MJ/m².
            track["solar_mj"] = float(track["solar_mj"]) + max(0.0, average) * hours * 0.0036
    track["solar_last_w"] = watts_m2
    track["solar_last_at"] = at.isoformat()


def uv_index_to_w_m2(uv_index: float) -> float:
    """Estimate broadband irradiance from a UV index. Not an FAO equation."""
    return max(0.0, uv_index) * UV_INDEX_TO_W_M2


def observed_temperature_range(track: dict[str, object]) -> tuple[float, float] | None:
    """Return (high, low) once the sensor has seen a real daily range.

    A single reading makes high and low equal, which zeros the Hargreaves
    radiation estimate. Callers should keep the weather-entity forecast until
    the range is at least half a degree.
    """
    high = track["t_max_c"]
    low = track["t_min_c"]
    if high is None or low is None:
        return None
    if float(high) - float(low) < 0.5:
        return None
    return float(high), float(low)
