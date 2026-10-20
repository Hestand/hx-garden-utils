"""Daily climate totals for reference evapotranspiration.

Penman-Monteith needs the day's high and low temperature, a humidity mean
(or the high and low), a wind mean, a pressure mean, and the solar total.
Those come from recorded sensor history for the local calendar day when Home
Assistant has it, so a restart reads the same series and gets the same total.
When the recorder has nothing yet, a running aggregate kept in storage is
updated from real samples and survives the restart.

A finished day is locked after it is computed once. Later restarts do not
build it again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .et import ETInputs

_LOGGER = logging.getLogger(__name__)

# Stored samples are taken about once an hour. A long hole is not a real hold.
_STORED_GAP_HOURS = 6.0
_KEEP_DAYS = 21


@dataclass(frozen=True)
class HistoryPoint:
    """One recorded state. ``unit`` is the state unit, not a weather attribute."""

    at: datetime
    state: str
    unit: str | None
    attributes: dict[str, Any]


def fresh_climate_day(day: str) -> dict[str, Any]:
    """Empty aggregate for one local date."""
    return {
        "date": day,
        "locked": False,
        "source": "stored",
        "t_max_c": None,
        "t_min_c": None,
        "rh_mean_pct": None,
        "rh_max_pct": None,
        "rh_min_pct": None,
        "rh_weighted": 0.0,
        "rh_seconds": 0.0,
        "wind_m_s": None,
        "wind_weighted": 0.0,
        "wind_seconds": 0.0,
        "pressure_kpa": None,
        "pressure_weighted": 0.0,
        "pressure_seconds": 0.0,
        "solar_mj": 0.0,
        "last": {},
        "et0_mm": None,
        "method": None,
        "detail": None,
    }


def has_temperature(day: dict[str, Any]) -> bool:
    """True once the day has both a high and a low."""
    return day.get("t_max_c") is not None and day.get("t_min_c") is not None


def inputs_from_day(
    day: dict[str, Any],
    *,
    latitude: float | None,
    elevation_m: float,
    wind_height_m: float,
) -> ETInputs | None:
    """ET inputs for this aggregate. Solar is the daily total, never one reading."""
    if not has_temperature(day):
        return None
    try:
        day_of_year = date.fromisoformat(str(day["date"])).timetuple().tm_yday
    except ValueError:
        return None
    solar = float(day.get("solar_mj") or 0.0)
    return ETInputs(
        t_max_c=float(day["t_max_c"]),
        t_min_c=float(day["t_min_c"]),
        latitude_deg=latitude,
        day_of_year=day_of_year,
        elevation_m=elevation_m,
        rh_mean_pct=_optional(day, "rh_mean_pct"),
        rh_max_pct=_optional(day, "rh_max_pct"),
        rh_min_pct=_optional(day, "rh_min_pct"),
        wind_m_s=_optional(day, "wind_m_s"),
        wind_height_m=wind_height_m,
        pressure_kpa=_optional(day, "pressure_kpa"),
        rs_mj_m2_day=solar if solar > 0 else None,
        solar_w_m2=None,
    )


def note_climate(day: dict[str, Any], kind: str, value: float, at: datetime) -> None:
    """Fold one live sample into a stored day. A repeated time adds nothing."""
    if day.get("locked"):
        return
    last = dict(day.get("last") or {})
    previous = last.get(kind)
    gap = 0.0
    if isinstance(previous, dict) and previous.get("at"):
        prev_at = datetime.fromisoformat(str(previous["at"]))
        if prev_at.tzinfo is None and at.tzinfo is not None:
            prev_at = prev_at.replace(tzinfo=at.tzinfo)
        if at <= prev_at:
            return
        gap = min((at - prev_at).total_seconds(), _STORED_GAP_HOURS * 3600.0)
    if kind == "temperature":
        _widen(day, "t_max_c", "t_min_c", value)
    elif kind == "solar_w":
        if isinstance(previous, dict) and gap > 0:
            average = (float(previous["v"]) + value) / 2.0
            day["solar_mj"] = float(day.get("solar_mj") or 0.0) + max(0.0, average) * (
                gap / 3600.0
            ) * 0.0036
    elif kind == "solar_mj":
        day["solar_mj"] = max(float(day.get("solar_mj") or 0.0), value)
    elif kind == "humidity":
        _note_mean(day, "rh", "rh_mean_pct", previous, gap, value)
        _widen(day, "rh_max_pct", "rh_min_pct", value)
    elif kind == "wind":
        _note_mean(day, "wind", "wind_m_s", previous, gap, value)
    elif kind == "pressure":
        _note_mean(day, "pressure", "pressure_kpa", previous, gap, value)
    else:
        raise ValueError(f"unknown climate kind {kind}")
    last[kind] = {"v": value, "at": at.isoformat()}
    day["last"] = last
    if day.get("source") != "recorder":
        day["source"] = "stored"


def apply_series(
    day: dict[str, Any],
    kind: str,
    points: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> bool:
    """Replace one field from a recorded series. The same series is the same total."""
    if day.get("locked") or not points:
        return False
    series = _window(points, start, end)
    if not series:
        return False
    if kind == "temperature":
        values = [value for _moment, value in series]
        day["t_max_c"] = max(values)
        day["t_min_c"] = min(values)
    elif kind == "solar_w":
        day["solar_mj"] = _integrate_solar(series)
    elif kind == "solar_mj":
        values = [value for _moment, value in series if value > 0]
        if not values:
            return False
        day["solar_mj"] = max(values)
    elif kind == "humidity":
        mean, high, low, weighted, seconds = _summarize(series)
        day["rh_mean_pct"] = mean
        day["rh_max_pct"] = high
        day["rh_min_pct"] = low
        day["rh_weighted"] = weighted
        day["rh_seconds"] = seconds
    elif kind == "wind":
        mean, _high, _low, weighted, seconds = _summarize(series)
        day["wind_m_s"] = mean
        day["wind_weighted"] = weighted
        day["wind_seconds"] = seconds
    elif kind == "pressure":
        mean, _high, _low, weighted, seconds = _summarize(series)
        day["pressure_kpa"] = mean
        day["pressure_weighted"] = weighted
        day["pressure_seconds"] = seconds
    else:
        raise ValueError(f"unknown climate kind {kind}")
    moment, value = series[-1]
    last = dict(day.get("last") or {})
    last[kind] = {"v": value, "at": moment.isoformat()}
    day["last"] = last
    day["source"] = "recorder"
    return True


def source_sentence(day: dict[str, Any]) -> str:
    """Tell the ET0 detail where the daily totals came from."""
    if day.get("source") == "recorder":
        return (
            "Daily totals come from recorded history for this calendar day, "
            "not from the live reading."
        )
    return (
        "Daily totals come from stored readings for this calendar day, "
        "not from the live reading."
    )


async def async_entity_histories(
    hass: HomeAssistant,
    entity_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[HistoryPoint]] | None:
    """Recorded states for these entities, or None when the recorder cannot be read."""
    wanted = [entity_id for entity_id in dict.fromkeys(entity_ids) if entity_id]
    if not wanted:
        return {}
    if "recorder" not in hass.config.components:
        return None
    try:
        from homeassistant.components.recorder import get_instance, history
    except ImportError:
        return None

    def _read() -> dict[str, list[Any]]:
        return history.get_significant_states(
            hass,
            start,
            end,
            wanted,
            None,
            True,
            True,
            False,
            False,
        )

    try:
        raw = await get_instance(hass).async_add_executor_job(_read)
    except Exception:  # noqa: BLE001 - a down recorder must not block the plan
        _LOGGER.debug("Sprinklecast could not read recorder history", exc_info=True)
        return None
    if not isinstance(raw, dict):
        return None
    found: dict[str, list[HistoryPoint]] = {}
    for entity_id in wanted:
        points: list[HistoryPoint] = []
        for state in raw.get(entity_id) or []:
            moment = getattr(state, "last_updated", None) or getattr(
                state, "last_changed", None
            )
            if moment is None:
                continue
            attributes = dict(getattr(state, "attributes", {}) or {})
            unit = attributes.get("unit_of_measurement")
            points.append(
                HistoryPoint(
                    at=moment,
                    state=str(getattr(state, "state", "")),
                    unit=None if unit is None else str(unit),
                    attributes=attributes,
                )
            )
        found[entity_id] = points
    return found


def _optional(day: dict[str, Any], key: str) -> float | None:
    value = day.get(key)
    if value is None:
        return None
    return float(value)


def _widen(day: dict[str, Any], high_key: str, low_key: str, value: float) -> None:
    high = day.get(high_key)
    low = day.get(low_key)
    day[high_key] = value if high is None else max(float(high), value)
    day[low_key] = value if low is None else min(float(low), value)


def _note_mean(
    day: dict[str, Any],
    prefix: str,
    mean_key: str,
    previous: object,
    gap: float,
    value: float,
) -> None:
    if isinstance(previous, dict) and gap > 0:
        weighted = float(day.get(f"{prefix}_weighted") or 0.0) + float(previous["v"]) * gap
        seconds = float(day.get(f"{prefix}_seconds") or 0.0) + gap
        day[f"{prefix}_weighted"] = weighted
        day[f"{prefix}_seconds"] = seconds
        day[mean_key] = weighted / seconds
    elif day.get(mean_key) is None:
        day[mean_key] = value


def _window(
    points: list[tuple[datetime, float]], start: datetime, end: datetime
) -> list[tuple[datetime, float]]:
    """Values in effect from ``start`` through ``end``, including the hold at the start."""
    holding: tuple[datetime, float] | None = None
    inside: list[tuple[datetime, float]] = []
    for moment, value in sorted(points, key=lambda item: item[0]):
        if moment <= start:
            holding = (start, value)
            continue
        if moment > end:
            break
        inside.append((moment, value))
    series: list[tuple[datetime, float]] = []
    if holding is not None:
        series.append(holding)
    series.extend(inside)
    return series


def _summarize(
    series: list[tuple[datetime, float]],
) -> tuple[float, float, float, float, float]:
    """Time-weighted mean plus high, low, weighted sum, and seconds.

    The value holds until the next recorded state. The last state is not
    extended, so two reads of the same series match even if the clock moved.
    """
    weighted = 0.0
    seconds = 0.0
    for (moment, value), (following, _next) in zip(series, series[1:]):
        gap = (following - moment).total_seconds()
        if gap <= 0:
            continue
        weighted += value * gap
        seconds += gap
    values = [value for _moment, value in series]
    if seconds <= 0:
        mean = sum(values) / len(values)
    else:
        mean = weighted / seconds
    return mean, max(values), min(values), weighted, seconds


def _integrate_solar(series: list[tuple[datetime, float]]) -> float:
    """Trapezoid W/m² to MJ/m². A single instantaneous reading adds nothing."""
    total = 0.0
    for (moment, watts), (following, next_watts) in zip(series, series[1:]):
        hours = (following - moment).total_seconds() / 3600.0
        if hours <= 0:
            continue
        average = (watts + next_watts) / 2.0
        total += max(0.0, average) * hours * 0.0036
    return total


def prune_days(days: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """Keep the recent days, including today."""
    kept = [day for day in days if str(day.get("date") or "") <= today]
    kept.sort(key=lambda day: str(day.get("date")))
    if len(kept) <= _KEEP_DAYS:
        return kept
    return kept[-_KEEP_DAYS:]


def midnight(moment: datetime, day: date) -> datetime:
    """Local midnight of ``day`` in ``moment``'s time zone."""
    return datetime(day.year, day.month, day.day, tzinfo=moment.tzinfo)


def next_midnight(start: datetime) -> datetime:
    """The following local midnight."""
    return start + timedelta(days=1)
