"""Suggest a weather entity and Tempest-style sensors during setup.

Only a station that identifies itself (Tempest, WeatherFlow, or a device
whose name says so) is prefilled. A lone weather entity is suggested when
the home has exactly one. Other temperature sensors are left alone.
"""

from __future__ import annotations

from dataclasses import dataclass

_STATION_TOKENS = ("tempest", "weatherflow", "weather_flow", "wf_")


@dataclass(frozen=True)
class EntityHint:
    """The bits of an entity the detector needs. No Home Assistant import."""

    entity_id: str
    device_class: str | None = None
    name: str = ""
    unit: str | None = None
    device_id: str | None = None
    device_name: str = ""


@dataclass(frozen=True)
class Discovery:
    """Entities worth putting in the form. Missing pieces stay None."""

    weather: str | None = None
    temperature: str | None = None
    humidity: str | None = None
    wind: str | None = None
    pressure: str | None = None
    solar: str | None = None
    uv: str | None = None
    rain: str | None = None
    rain_kind: str | None = None


def _blob(entity: EntityHint) -> str:
    return f"{entity.entity_id} {entity.name} {entity.device_name}".casefold()


def _is_station(entity: EntityHint) -> bool:
    text = _blob(entity)
    return any(token in text for token in _STATION_TOKENS)


def _domain(entity: EntityHint) -> str:
    return entity.entity_id.split(".", 1)[0]


def _unit(entity: EntityHint) -> str:
    return (entity.unit or "").casefold().replace(" ", "").replace("²", "2")


def discover(entities: list[EntityHint]) -> Discovery:
    """Pick a weather entity and, when a station is present, its sensors."""
    weather_entities = [entity for entity in entities if _domain(entity) == "weather"]
    station_weather = [entity for entity in weather_entities if _is_station(entity)]
    if len(station_weather) == 1:
        weather = station_weather[0].entity_id
    elif len(weather_entities) == 1:
        weather = weather_entities[0].entity_id
    else:
        weather = None

    station_ids = {
        entity.device_id
        for entity in entities
        if entity.device_id and _is_station(entity)
    }
    pool = [
        entity
        for entity in entities
        if _is_station(entity) or (entity.device_id and entity.device_id in station_ids)
    ]
    if not pool:
        return Discovery(weather=weather)

    def only(matches: list[EntityHint]) -> str | None:
        if len(matches) == 1:
            return matches[0].entity_id
        return None

    def of_class(device_class: str) -> list[EntityHint]:
        return [entity for entity in pool if entity.device_class == device_class]

    temperature = only(of_class("temperature"))
    humidity = only(of_class("humidity"))
    wind = only(of_class("wind_speed"))
    pressure_rows = of_class("pressure") or of_class("atmospheric_pressure")
    station_pressure = [
        entity for entity in pressure_rows if "station" in _blob(entity)
    ]
    sea_level = [entity for entity in pressure_rows if "sea" in _blob(entity)]
    if station_pressure:
        pressure = station_pressure[0].entity_id
    elif sea_level and len(pressure_rows) > len(sea_level):
        pressure = next(
            entity.entity_id for entity in pressure_rows if entity not in sea_level
        )
    else:
        pressure = only(pressure_rows)

    solar_rows = [
        entity
        for entity in pool
        if entity.device_class in {"irradiance", "solar_irradiance"}
        or "solar" in _blob(entity)
        or _unit(entity) in {"w/m2", "wm2", "w/m^2"}
    ]
    solar = only(solar_rows)
    uv_rows = [
        entity
        for entity in pool
        if entity.device_class in {"uv_index"} or "uv" in _blob(entity)
    ]
    uv = only(uv_rows)
    rain_rows = [
        entity
        for entity in pool
        if entity.device_class == "precipitation" or "rain" in _blob(entity)
    ]
    # Prefer a daily total over an instantaneous rate when both exist.
    daily = [
        entity
        for entity in rain_rows
        if any(token in _blob(entity) for token in ("today", "daily", "local_day"))
    ]
    if len(daily) == 1:
        rain = daily[0].entity_id
    elif len(rain_rows) == 1:
        rain = rain_rows[0].entity_id
    else:
        rain = None
    rain_kind = None
    if rain is not None:
        chosen = next(entity for entity in rain_rows if entity.entity_id == rain)
        text = _blob(chosen)
        if "rate" in text or "/h" in _unit(chosen):
            rain_kind = "rate"
        elif "cumulative" in text or "lifetime" in text:
            rain_kind = "cumulative"
        else:
            rain_kind = "daily_total"
    return Discovery(
        weather=weather,
        temperature=temperature,
        humidity=humidity,
        wind=wind,
        pressure=pressure,
        solar=solar,
        uv=uv,
        rain=rain,
        rain_kind=rain_kind,
    )
