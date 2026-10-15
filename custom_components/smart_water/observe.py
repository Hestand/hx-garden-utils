"""Daily accumulation of temperature, rain, and solar from Home Assistant entities.

Samples are folded into one local day. A new date starts a new total. The
weather entity remains the fallback when a sensor is absent. Instantaneous
W/m² (a Tempest solar reading, or a UV index converted with
``UV_INDEX_TO_W_M2``) is integrated to MJ/m²/day so Penman-Monteith can use
it. A sensor that already reports daily MJ is not integrated.
"""

from __future__ import annotations

from datetime import datetime

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
        track["rain_mm"] = max(0.0, value_mm)
        track["rain_cursor"] = value_mm
        track["rain_last_at"] = at.isoformat()
        return
    cursor = track["rain_cursor"]
    if kind == RAIN_KIND_CUMULATIVE:
        if cursor is None:
            track["rain_cursor"] = value_mm
        else:
            delta = value_mm - float(cursor)
            if delta >= 0:
                track["rain_mm"] = float(track["rain_mm"]) + delta
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
            track["rain_mm"] = float(track["rain_mm"]) + max(0.0, average) * hours
    track["rain_cursor"] = value_mm
    track["rain_last_at"] = at.isoformat()


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
