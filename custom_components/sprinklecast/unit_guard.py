"""Decide whether a selected entity's unit can be used.

A repair is only for an entity that has a real state and a missing or
unrecognized unit. An entity that does not exist yet, or is unavailable or
unknown, is not ready. That is not a unit error: it does not open a repair,
and it does not clear one that is already open.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_FLOW_KIND,
    CONF_FLOW_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_MOISTURE_SENSOR,
    CONF_PRESSURE_SENSOR,
    CONF_RAIN_AMOUNT_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_SOLAR_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    CONF_UV_SENSOR,
    CONF_WEATHER_ENTITY,
    CONF_WIND_SENSOR,
    FLOW_KIND_RATE,
    SUBENTRY_ZONE,
)
from .units import accepted_units, unit_ok

# No reading yet. Restored and still-loading entities use these states.
_NOT_READY = {"unknown", "unavailable", "none", ""}

# On/off rain sensors. A valve's open state is not rain.
RAIN_ON_OFF_DOMAINS = frozenset({"binary_sensor", "switch", "input_boolean"})

# Hub option key, unit kind, label shown on the repair.
_SENSOR_FIELDS: tuple[tuple[str, str, str], ...] = (
    (CONF_TEMPERATURE_SENSOR, "temperature", "Temperature sensor"),
    (CONF_HUMIDITY_SENSOR, "humidity", "Humidity sensor"),
    (CONF_WIND_SENSOR, "wind", "Wind sensor"),
    (CONF_PRESSURE_SENSOR, "pressure", "Pressure sensor"),
    (CONF_SOLAR_SENSOR, "solar", "Solar radiation sensor"),
    (CONF_UV_SENSOR, "uv", "UV index sensor"),
    (CONF_RAIN_AMOUNT_SENSOR, "depth", "Rain amount sensor"),
)

_WEATHER_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("temperature_unit", "temperature", "Weather temperature"),
    ("precipitation_unit", "depth", "Weather precipitation"),
    ("wind_speed_unit", "wind", "Weather wind"),
)


@dataclass(frozen=True)
class UnitProblem:
    """One hub field whose unit cannot be used."""

    field: str
    entity_id: str
    reported: str
    accepted: str


def reported_unit(unit: str | None) -> str:
    """The unit text for an error. A blank unit is missing."""
    if unit is None or str(unit).strip() == "":
        return "missing"
    return str(unit)


def rejection_sentence(label: str, entity_id: str, unit: str | None, kind: str) -> str:
    """Form error: the entity, the unit it reported, and the accepted list."""
    return (
        f"{label} ({entity_id}) reports {reported_unit(unit)}. "
        f"Accepted units: {accepted_units(kind)}. "
        "Any other unit shows a warning and this reading is ignored."
    )


def _registry_unit(hass: HomeAssistant, entity_id: str) -> str | None:
    try:
        entry = er.async_get(hass).async_get(entity_id)
    except (KeyError, RuntimeError):
        return None
    if entry is None or not entry.unit_of_measurement:
        return None
    return str(entry.unit_of_measurement)


def sensor_unit(hass: HomeAssistant, entity_id: str) -> tuple[str | None, bool]:
    """Return ``(unit, decisive)``.

    ``decisive`` is false when the entity is not ready, so the caller neither
    opens nor clears a repair. A real state with a missing unit is decisive.
    """
    state = hass.states.get(entity_id)
    if state is None or state.state in _NOT_READY:
        return None, False
    raw = state.attributes.get("unit_of_measurement")
    if raw not in (None, ""):
        return str(raw), True
    stored = _registry_unit(hass, entity_id)
    if stored:
        return stored, True
    return None, True


def sensor_problem(hass: HomeAssistant, entity_id: str, kind: str, label: str) -> str | None:
    """A form sentence when this selection's unit is missing or not accepted."""
    state = hass.states.get(entity_id)
    unit: str | None = None
    if state is not None:
        raw = state.attributes.get("unit_of_measurement")
        unit = None if raw in (None, "") else str(raw)
    if unit is None:
        unit = _registry_unit(hass, entity_id)
    if unit_ok(kind, unit):
        return None
    return rejection_sentence(label, entity_id, unit, kind)


def _entity_known(hass: HomeAssistant, entity_id: str) -> bool:
    if hass.states.get(entity_id) is not None:
        return True
    try:
        return er.async_get(hass).async_get(entity_id) is not None
    except (KeyError, RuntimeError):
        return False


def rain_sensor_problem(hass: HomeAssistant, entity_id: str) -> str | None:
    """A form sentence when a rain sensor is missing or its rate unit is unusable.

    An on/off sensor has no unit. A numeric sensor must report a rain rate.
    """
    if not _entity_known(hass, entity_id):
        return (
            f"Rain sensor ({entity_id}) is missing, so it cannot be checked. "
            "An on/off sensor needs no unit. "
            f"A rain-rate sensor needs {accepted_units('rain_rate')}."
        )
    domain = entity_id.partition(".")[0]
    if domain in RAIN_ON_OFF_DOMAINS:
        return None
    if domain == "sensor":
        return sensor_problem(hass, entity_id, "rain_rate", "Rain sensor")
    return (
        f"Rain sensor ({entity_id}) must be an on/off sensor "
        "(binary_sensor, switch, or input_boolean) or a rain-rate sensor."
    )


def weather_problems(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Form sentences for a weather entity whose declared units are unusable."""
    state = hass.states.get(entity_id)
    if state is None:
        return [
            "Weather entity "
            f"({entity_id}) is missing, so its units cannot be read. "
            f"Temperature: {accepted_units('temperature')}. "
            f"Precipitation: {accepted_units('depth')}. "
            f"Wind: {accepted_units('wind')}."
        ]
    sentences: list[str] = []
    for attribute, kind, label in _WEATHER_FIELDS:
        raw = state.attributes.get(attribute)
        unit = None if raw in (None, "") else str(raw)
        if not unit_ok(kind, unit):
            sentences.append(rejection_sentence(label, entity_id, unit, kind))
    return sentences


def _consider(
    bad: dict[str, UnitProblem],
    leave: set[str],
    *,
    key: str,
    label: str,
    entity_id: str,
    kind: str,
    unit: str | None,
    decisive: bool,
) -> None:
    if not decisive:
        leave.add(key)
        return
    if unit_ok(kind, unit):
        return
    bad[key] = UnitProblem(
        field=label,
        entity_id=entity_id,
        reported=reported_unit(unit),
        accepted=accepted_units(kind),
    )


def audit_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> tuple[dict[str, UnitProblem], set[str]]:
    """Bad fields to repair, and fields to leave untouched.

    A field in neither set is fine, or no longer configured, and its repair
    should be cleared.
    """
    bad: dict[str, UnitProblem] = {}
    leave: set[str] = set()
    options = entry.options
    for key, kind, label in _SENSOR_FIELDS:
        entity_id = options.get(key)
        if not entity_id:
            continue
        unit, decisive = sensor_unit(hass, str(entity_id))
        _consider(
            bad,
            leave,
            key=key,
            label=label,
            entity_id=str(entity_id),
            kind=kind,
            unit=unit,
            decisive=decisive,
        )
    flow_entity = options.get(CONF_FLOW_SENSOR)
    if flow_entity:
        kind = "rate" if options.get(CONF_FLOW_KIND) == FLOW_KIND_RATE else "volume"
        label = "Flow sensor"
        unit, decisive = sensor_unit(hass, str(flow_entity))
        _consider(
            bad,
            leave,
            key=CONF_FLOW_SENSOR,
            label=label,
            entity_id=str(flow_entity),
            kind=kind,
            unit=unit,
            decisive=decisive,
        )
    weather_id = entry.data.get(CONF_WEATHER_ENTITY)
    if weather_id:
        state = hass.states.get(str(weather_id))
        not_ready = state is None or state.state in _NOT_READY
        for attribute, kind, label in _WEATHER_FIELDS:
            key = f"weather_{attribute}"
            if not_ready:
                leave.add(key)
                continue
            raw = state.attributes.get(attribute) if state is not None else None
            unit = None if raw in (None, "") else str(raw)
            _consider(
                bad,
                leave,
                key=key,
                label=label,
                entity_id=str(weather_id),
                kind=kind,
                unit=unit,
                decisive=True,
            )
    _audit_rain(
        bad,
        leave,
        hass,
        options.get(CONF_RAIN_SENSOR),
        key=CONF_RAIN_SENSOR,
        label="Rain sensor",
    )
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        entity_id = subentry.data.get(CONF_MOISTURE_SENSOR)
        if entity_id:
            key = f"moisture_{subentry.subentry_id}"
            unit, decisive = sensor_unit(hass, str(entity_id))
            _consider(
                bad,
                leave,
                key=key,
                label=f"Soil moisture sensor ({subentry.title})",
                entity_id=str(entity_id),
                kind="moisture",
                unit=unit,
                decisive=decisive,
            )
        _audit_rain(
            bad,
            leave,
            hass,
            subentry.data.get(CONF_RAIN_SENSOR),
            key=f"rain_{subentry.subentry_id}",
            label=f"Rain sensor ({subentry.title})",
        )
    return bad, leave


def configured_unit_entities(entry: ConfigEntry) -> list[str]:
    """Entity ids whose unit this hub checks."""
    found: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        if not value:
            return
        entity_id = str(value)
        if entity_id in seen:
            return
        seen.add(entity_id)
        found.append(entity_id)

    options = entry.options
    for key, _kind, _label in _SENSOR_FIELDS:
        add(options.get(key))
    add(options.get(CONF_FLOW_SENSOR))
    add(options.get(CONF_RAIN_SENSOR))
    add(entry.data.get(CONF_WEATHER_ENTITY))
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_ZONE:
            continue
        add(subentry.data.get(CONF_MOISTURE_SENSOR))
        add(subentry.data.get(CONF_RAIN_SENSOR))
    return found


def _audit_rain(
    bad: dict[str, UnitProblem],
    leave: set[str],
    hass: HomeAssistant,
    entity_id: str | None,
    *,
    key: str,
    label: str,
) -> None:
    """Check a numeric rain sensor. An on/off sensor has no unit to repair."""
    if not entity_id:
        return
    entity_id = str(entity_id)
    domain = entity_id.partition(".")[0]
    if domain in RAIN_ON_OFF_DOMAINS:
        return
    if domain != "sensor":
        return
    unit, decisive = sensor_unit(hass, str(entity_id))
    _consider(
        bad,
        leave,
        key=key,
        label=label,
        entity_id=str(entity_id),
        kind="rain_rate",
        unit=unit,
        decisive=decisive,
    )
