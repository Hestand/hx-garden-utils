"""Config and options flows for Sprinklecast.

The first step chooses a live hub or a simulation hub. A live hub asks for
a name and either a weather entity or a temperature sensor. A simulation
hub asks for a name, an example week, and a starting soil, and its zones
have no on/off entity. The hub form then asks how many zones to add. Each
zone is the quick form (name, on/off entity, plant, soil, sprinkler, sun).
After the first zone, those four dropdowns start with the previous zone's
choices. What is submitted is what is saved. Advanced stays on the zone after
the hub exists. Every derived number stays blank unless the user types an
override; blank means the preset in ``presets.py``.

Automatic watering is a switch, default off. It is not a config option.
The executor calls each zone's stored on/off entity and does not call Hydrawise.
"""

from __future__ import annotations

from typing import Any, Literal

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .unit_guard import rain_sensor_problem, sensor_problem, weather_problems
from .const import (
    CONF_ALLOWED_WEEKDAYS,
    CONF_AREA_SQFT,
    CONF_AWC_OVERRIDE,
    CONF_BASELINE_DAYS,
    CONF_BASELINE_MINUTES,
    CONF_COST_PER_1000_GAL,
    CONF_BLACKOUT_END_HOUR,
    CONF_BLACKOUT_START_HOUR,
    CONF_BUCKET,
    CONF_DEPLETION,
    CONF_DORMANT_BELOW_F,
    CONF_DRIP_IGNORES_SCHEDULE,
    CONF_DYNAMIC_START,
    CONF_EARLIEST_START,
    CONF_EFFICIENCY,
    CONF_ELEVATION_M,
    CONF_FIELD_CAPACITY,
    CONF_FLOW_GPM,
    CONF_FLOW_HIGH_ACTION,
    CONF_FLOW_HIGH_PCT,
    CONF_FLOW_IDLE_ACTION,
    CONF_FLOW_IDLE_GPM,
    CONF_FLOW_KIND,
    CONF_FLOW_LEARN_RUNS,
    CONF_FLOW_TREND_PCT,
    CONF_FLOW_TREND_RUNS,
    CONF_FLOW_LOW_ACTION,
    CONF_FLOW_LOW_PCT,
    CONF_FLOW_LEAK_RATIO,
    CONF_FLOW_LOW_RATIO,
    CONF_FLOW_SCOPE,
    CONF_FLOW_SENSOR,
    CONF_FORECAST_DEFER_DAYS,
    CONF_FORECAST_HOURS,
    CONF_FORECAST_PROBABILITY_PCT,
    CONF_FORECAST_SKIP_MM,
    CONF_FREEZE_ALERT,
    CONF_FREEZE_ALERT_F,
    CONF_FREEZE_SKIP_F,
    CONF_HARD_FREEZE_F,
    CONF_HUB_NIGHTLY_CAP_MIN,
    CONF_HEAT_ABOVE_F,
    CONF_HUMIDITY_SENSOR,
    CONF_INTAKE_IN_HR,
    CONF_KC_OVERRIDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MAINTENANCE_WATERING,
    CONF_MAX_CYCLE_MIN,
    CONF_MAX_DAILY_RUNTIME_MIN,
    CONF_MAX_RUN_MIN,
    CONF_MIN_INTERVAL_DAYS,
    CONF_MOISTURE_KIND,
    CONF_MOISTURE_LEARN,
    CONF_MOISTURE_MODE,
    CONF_MOISTURE_SENSOR,
    CONF_MOISTURE_SKIP_PCT,
    CONF_MOISTURE_WEIGHT,
    CONF_NOTIFY_TARGET,
    CONF_PLAN_HOUR,
    CONF_SEND_PLAN_NOTIFICATIONS,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRESSURE_SENSOR,
    CONF_PRIORITY,
    CONF_RAIN_AMOUNT_SENSOR,
    CONF_RAIN_KIND,
    CONF_RAIN_RATE_MIN,
    CONF_RAIN_SENSOR,
    CONF_ROUND_MINUTES,
    CONF_ROOT_DEPTH_IN,
    CONF_SCENARIO,
    CONF_SIMULATION,
    CONF_SLOW_BELOW_F,
    CONF_SLOPE_PCT,
    CONF_SOAK_MIN,
    CONF_SOIL_TYPE,
    CONF_SOLAR_SENSOR,
    CONF_SPRINKLER_TYPE,
    CONF_START_TIME,
    CONF_FINISH_TIME,
    CONF_SUN_EXPOSURE,
    CONF_TARGET_DEPTH_IN,
    CONF_TEMPERATURE_SENSOR,
    CONF_UV_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WEEKLY_BUDGET_GAL,
    CONF_WEEKLY_SUMMARY,
    CONF_WIND_HEIGHT_M,
    CONF_WIND_SENSOR,
    CONF_WIND_SKIP_MPH,
    CONF_ZONE_MAX_RUN_MIN,
    DEFAULT_ELEVATION_M,
    DEFAULT_FREEZE_SKIP_F,
    DEFAULT_MAX_RUN_MIN,
    DEFAULT_FLOW_KIND,
    FLOW_KIND_RATE,
    DEFAULT_FLOW_LEAK_RATIO,
    DEFAULT_FLOW_LOW_RATIO,
    DEFAULT_MOISTURE_KIND,
    DEFAULT_MOISTURE_MODE,
    DEFAULT_MOISTURE_WEIGHT,
    DEFAULT_PLAN_HOUR,
    DEFAULT_PRIORITY,
    DEFAULT_RAIN_KIND,
    DEFAULT_ROUND_MINUTES,
    DEFAULT_SPRINKLER_TYPE,
    DEFAULT_DYNAMIC_START,
    DEFAULT_EARLIEST_START,
    DEFAULT_FINISH_TIME,
    DEFAULT_START_TIME,
    DEFAULT_WIND_HEIGHT_M,
    DOMAIN,
    LEGACY_DOMAIN,
    FLOW_ACTION_NOTIFY,
    FLOW_ACTIONS,
    FLOW_KINDS,
    FLOW_SCOPE_IRRIGATION,
    FLOW_SCOPES,
    MOISTURE_KINDS,
    MOISTURE_MODES,
    RAIN_KINDS,
    SPRINKLER_BUBBLER,
    SPRINKLER_TYPES,
    SUBENTRY_ZONE,
    WEEKDAYS,
)
from .discover import EntityHint, discover
from .forecast_rain import (
    DEFAULT_FORECAST_DEFER_DAYS,
    DEFAULT_FORECAST_HOURS,
    DEFAULT_FORECAST_PROBABILITY_PCT,
    DEFAULT_FREEZE_ALERT_F,
    DEFAULT_HARD_FREEZE_F,
)
from .flow_learn import (
    DEFAULT_HIGH_PCT,
    DEFAULT_IDLE_GPM,
    DEFAULT_LEARN_RUNS,
    DEFAULT_LOW_PCT,
    DEFAULT_TREND_PCT,
    DEFAULT_TREND_RUNS,
)
from .presets import preset_placeholders
from .simulate import BUCKETS, DEFAULT_BUCKET, DEFAULT_SCENARIO, SCENARIOS
from .soil import PLANT_TYPES, SOIL_TYPES, SUN_EXPOSURES

_SECTION_SENSORS = "sensors"
_SECTION_LOCATION = "location"
_SECTION_MORNING = "morning"
_SECTION_FLOW = "flow_meter"
_SECTION_PLANT = "plant_overrides"
_SECTION_HARDWARE = "hardware_overrides"
_SECTION_MEASURE = "measurement_overrides"

_HUB_SECTIONS = frozenset(
    {_SECTION_SENSORS, _SECTION_LOCATION, _SECTION_FLOW, _SECTION_MORNING}
)
_ZONE_SECTIONS = frozenset({_SECTION_PLANT, _SECTION_HARDWARE, _SECTION_MEASURE})

_PLANT_KEYS = (
    CONF_ROOT_DEPTH_IN,
    CONF_AWC_OVERRIDE,
    CONF_INTAKE_IN_HR,
    CONF_DEPLETION,
    CONF_KC_OVERRIDE,
    CONF_MIN_INTERVAL_DAYS,
    CONF_TARGET_DEPTH_IN,
    CONF_FREEZE_SKIP_F,
    CONF_WIND_SKIP_MPH,
    CONF_MOISTURE_SKIP_PCT,
    CONF_DORMANT_BELOW_F,
    CONF_SLOW_BELOW_F,
    CONF_HEAT_ABOVE_F,
    CONF_MAINTENANCE_WATERING,
    CONF_MOISTURE_LEARN,
)
_HARDWARE_KEYS = (
    CONF_PRECIPITATION_RATE,
    CONF_EFFICIENCY,
    CONF_SLOPE_PCT,
    CONF_MAX_CYCLE_MIN,
    CONF_SOAK_MIN,
    CONF_FLOW_GPM,
    CONF_AREA_SQFT,
    CONF_BASELINE_MINUTES,
    CONF_BASELINE_DAYS,
    CONF_MAX_RUN_MIN,
)
_MEASURE_KEYS = (
    CONF_PRIORITY,
    CONF_MOISTURE_SENSOR,
    CONF_MOISTURE_MODE,
    CONF_MOISTURE_KIND,
    CONF_MOISTURE_WEIGHT,
    CONF_FIELD_CAPACITY,
    CONF_FLOW_LOW_RATIO,
    CONF_FLOW_LEAK_RATIO,
    CONF_RAIN_RATE_MIN,
    CONF_RAIN_SENSOR,
)
_SENSOR_KEYS = (
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_WIND_SENSOR,
    CONF_PRESSURE_SENSOR,
    CONF_SOLAR_SENSOR,
    CONF_UV_SENSOR,
    CONF_RAIN_AMOUNT_SENSOR,
    CONF_RAIN_KIND,
    CONF_WIND_HEIGHT_M,
)
_LOCATION_KEYS = (
    CONF_ELEVATION_M,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NOTIFY_TARGET,
    CONF_RAIN_RATE_MIN,
    CONF_RAIN_SENSOR,
    CONF_PLAN_HOUR,
    CONF_FORECAST_SKIP_MM,
    CONF_MAX_DAILY_RUNTIME_MIN,
    CONF_ROUND_MINUTES,
    CONF_ALLOWED_WEEKDAYS,
    CONF_FREEZE_SKIP_F,
    CONF_ZONE_MAX_RUN_MIN,
    CONF_HUB_NIGHTLY_CAP_MIN,
    CONF_FORECAST_PROBABILITY_PCT,
    CONF_FORECAST_DEFER_DAYS,
    CONF_FORECAST_HOURS,
    CONF_FREEZE_ALERT,
    CONF_FREEZE_ALERT_F,
    CONF_HARD_FREEZE_F,
    CONF_BLACKOUT_START_HOUR,
    CONF_BLACKOUT_END_HOUR,
    CONF_DRIP_IGNORES_SCHEDULE,
    CONF_FLOW_HIGH_PCT,
    CONF_FLOW_LOW_PCT,
    CONF_FLOW_LEARN_RUNS,
    CONF_FLOW_TREND_PCT,
    CONF_FLOW_TREND_RUNS,
    CONF_FLOW_HIGH_ACTION,
    CONF_FLOW_LOW_ACTION,
    CONF_COST_PER_1000_GAL,
    CONF_WEEKLY_BUDGET_GAL,
    CONF_WEEKLY_SUMMARY,
)
_MORNING_KEYS = (
    CONF_DYNAMIC_START,
    CONF_EARLIEST_START,
    CONF_FINISH_TIME,
    CONF_START_TIME,
)

_WEATHER = selector.EntitySelector(selector.EntitySelectorConfig(domain="weather"))
_SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
_RAIN = selector.EntitySelector(
    selector.EntitySelectorConfig(
        domain=["binary_sensor", "switch", "input_boolean", "sensor"]
    )
)
_ON_OFF = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["switch", "valve", "input_boolean"])
)
_TEXT = selector.TextSelector()
_BOOL = selector.BooleanSelector()


def _select(
    options: tuple[str, ...] | list[str],
    key: str,
    *,
    multiple: bool = False,
) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options),
            multiple=multiple,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=key,
        )
    )


def _number(
    min_value: float,
    max_value: float,
    step: float | Literal["any"],
    unit: str | None = None,
) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=min_value,
        max=max_value,
        step=step,
        mode=selector.NumberSelectorMode.BOX,
    )
    if unit is not None:
        config = selector.NumberSelectorConfig(
            min=min_value,
            max=max_value,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    return selector.NumberSelector(config)


def _unit_detail(
    hass: HomeAssistant,
    flat: dict[str, Any],
    *,
    weather: str | None = None,
) -> str | None:
    """Sentences for selected entities whose units are missing or unknown."""
    sentences: list[str] = []
    if weather and not _blank(weather):
        sentences.extend(weather_problems(hass, str(weather)))
    fields = (
        (CONF_TEMPERATURE_SENSOR, "temperature", "Temperature sensor"),
        (CONF_HUMIDITY_SENSOR, "humidity", "Humidity sensor"),
        (CONF_WIND_SENSOR, "wind", "Wind sensor"),
        (CONF_PRESSURE_SENSOR, "pressure", "Pressure sensor"),
        (CONF_SOLAR_SENSOR, "solar", "Solar radiation sensor"),
        (CONF_UV_SENSOR, "uv", "UV index sensor"),
        (CONF_RAIN_AMOUNT_SENSOR, "depth", "Rain amount sensor"),
        (CONF_MOISTURE_SENSOR, "moisture", "Soil moisture sensor"),
    )
    for key, kind, label in fields:
        entity_id = flat.get(key)
        if _blank(entity_id):
            continue
        sentence = sensor_problem(hass, str(entity_id), kind, label)
        if sentence:
            sentences.append(sentence)
    flow_entity = flat.get(CONF_FLOW_SENSOR)
    if not _blank(flow_entity):
        kind = "rate" if flat.get(CONF_FLOW_KIND) == FLOW_KIND_RATE else "volume"
        sentence = sensor_problem(hass, str(flow_entity), kind, "Flow sensor")
        if sentence:
            sentences.append(sentence)
    rain_entity = flat.get(CONF_RAIN_SENSOR)
    if not _blank(rain_entity):
        sentence = rain_sensor_problem(hass, str(rain_entity))
        if sentence:
            sentences.append(sentence)
    if not sentences:
        return None
    return " ".join(sentences)


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _drop_blanks(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not _blank(value)}


def _flatten(data: dict[str, Any], sections: frozenset[str]) -> dict[str, Any]:
    """Lift collapsible sections into one dict. Blank fields stay blank."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if key in sections and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    return flat


def _present(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Copy stored values only. Missing keys stay missing so presets apply."""
    return {key: data[key] for key in keys if key in data and not _blank(data[key])}


def _zone_slug(name: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in name.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "zone"


def _entity_hints(hass: HomeAssistant) -> list[EntityHint]:
    """Read states and registries. Discovery itself does not import HA."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    hints: list[EntityHint] = []
    for state in hass.states.async_all():
        registered = entities.async_get(state.entity_id)
        device_id = None
        device_name = ""
        device_class = state.attributes.get("device_class")
        if registered is not None:
            device_id = registered.device_id
            if not device_class:
                device_class = registered.device_class or registered.original_device_class
            if device_id:
                device = devices.async_get(device_id)
                if device is not None:
                    device_name = device.name_by_user or device.name or ""
        hints.append(
            EntityHint(
                entity_id=state.entity_id,
                device_class=str(device_class) if device_class else None,
                name=state.name or "",
                unit=state.attributes.get("unit_of_measurement"),
                device_id=device_id,
                device_name=device_name,
            )
        )
    return hints


def _sensor_fields() -> dict[Any, Any]:
    return {
        vol.Optional(CONF_TEMPERATURE_SENSOR): _SENSOR,
        vol.Optional(CONF_HUMIDITY_SENSOR): _SENSOR,
        vol.Optional(CONF_WIND_SENSOR): _SENSOR,
        vol.Optional(CONF_PRESSURE_SENSOR): _SENSOR,
        vol.Optional(CONF_SOLAR_SENSOR): _SENSOR,
        vol.Optional(CONF_UV_SENSOR): _SENSOR,
        vol.Optional(CONF_RAIN_AMOUNT_SENSOR): _SENSOR,
        vol.Required(CONF_RAIN_KIND, default=DEFAULT_RAIN_KIND): _select(
            RAIN_KINDS, "rain_kind"
        ),
        vol.Required(CONF_WIND_HEIGHT_M, default=DEFAULT_WIND_HEIGHT_M): _number(
            0.5, 30, 0.1, "m"
        ),
    }


def _location_fields() -> dict[Any, Any]:
    return {
        vol.Required(CONF_ELEVATION_M, default=DEFAULT_ELEVATION_M): _number(
            0, 5000, 0.1, "m"
        ),
        # NumberSelector rejects steps below 0.001. "any" keeps full
        # coordinate precision on Home Assistant 2026.10.
        vol.Optional(CONF_LATITUDE): _number(-90, 90, "any"),
        vol.Optional(CONF_LONGITUDE): _number(-180, 180, "any"),
        vol.Optional(CONF_NOTIFY_TARGET): _TEXT,
        vol.Optional(CONF_RAIN_SENSOR): _RAIN,
        vol.Optional(CONF_RAIN_RATE_MIN): _number(0, 1000, 0.001),
        vol.Required(CONF_PLAN_HOUR, default=DEFAULT_PLAN_HOUR): _number(0, 23, 1),
        vol.Optional(CONF_FORECAST_SKIP_MM): _number(0, 100, 0.1, "mm"),
        vol.Optional(CONF_MAX_DAILY_RUNTIME_MIN): _number(1, 600, 1, "min"),
        vol.Required(CONF_ROUND_MINUTES, default=DEFAULT_ROUND_MINUTES): _BOOL,
        vol.Required(CONF_ALLOWED_WEEKDAYS, default=list(WEEKDAYS)): _select(
            WEEKDAYS, "weekday", multiple=True
        ),
        vol.Required(CONF_FREEZE_SKIP_F, default=DEFAULT_FREEZE_SKIP_F): _number(
            20, 50, 1, "°F"
        ),
        vol.Required(CONF_ZONE_MAX_RUN_MIN, default=DEFAULT_MAX_RUN_MIN): _number(
            1, 240, 1, "min"
        ),
        vol.Optional(CONF_HUB_NIGHTLY_CAP_MIN): _number(1, 600, 1, "min"),
        vol.Required(
            CONF_FORECAST_PROBABILITY_PCT, default=DEFAULT_FORECAST_PROBABILITY_PCT
        ): _number(0, 100, 1, "%"),
        vol.Required(
            CONF_FORECAST_DEFER_DAYS, default=DEFAULT_FORECAST_DEFER_DAYS
        ): _number(0, 7, 1, "d"),
        vol.Required(CONF_FORECAST_HOURS, default=DEFAULT_FORECAST_HOURS): _number(
            1, 72, 1, "h"
        ),
        vol.Required(CONF_FREEZE_ALERT, default=True): _BOOL,
        vol.Required(CONF_FREEZE_ALERT_F, default=DEFAULT_FREEZE_ALERT_F): _number(
            0, 50, 1, "°F"
        ),
        vol.Required(CONF_HARD_FREEZE_F, default=DEFAULT_HARD_FREEZE_F): _number(
            0, 40, 1, "°F"
        ),
        vol.Optional(CONF_BLACKOUT_START_HOUR): _number(0, 23, 1),
        vol.Optional(CONF_BLACKOUT_END_HOUR): _number(0, 23, 1),
        vol.Required(CONF_DRIP_IGNORES_SCHEDULE, default=False): _BOOL,
        vol.Required(CONF_FLOW_HIGH_PCT, default=DEFAULT_HIGH_PCT): _number(5, 200, 1, "%"),
        vol.Required(CONF_FLOW_LOW_PCT, default=DEFAULT_LOW_PCT): _number(5, 90, 1, "%"),
        vol.Required(CONF_FLOW_LEARN_RUNS, default=DEFAULT_LEARN_RUNS): _number(1, 30, 1),
        vol.Required(CONF_FLOW_TREND_PCT, default=DEFAULT_TREND_PCT): _number(1, 50, 1, "%"),
        vol.Required(CONF_FLOW_TREND_RUNS, default=DEFAULT_TREND_RUNS): _number(3, 30, 1),
        vol.Required(CONF_FLOW_HIGH_ACTION, default=FLOW_ACTION_NOTIFY): _select(
            FLOW_ACTIONS, "flow_action"
        ),
        vol.Required(CONF_FLOW_LOW_ACTION, default=FLOW_ACTION_NOTIFY): _select(
            FLOW_ACTIONS, "flow_action"
        ),
        vol.Optional(CONF_COST_PER_1000_GAL): _number(0, 100, 0.01, "USD"),
        vol.Optional(CONF_WEEKLY_BUDGET_GAL): _number(1, 100_000, 1, "gal"),
        vol.Required(CONF_WEEKLY_SUMMARY, default=False): _BOOL,
    }


_FLOW_KEYS = (CONF_FLOW_SENSOR, CONF_FLOW_KIND, CONF_FLOW_SCOPE)
_FLOW_IDLE_KEYS = (CONF_FLOW_IDLE_GPM, CONF_FLOW_IDLE_ACTION)


def _show_idle(source: dict[str, Any] | None) -> bool:
    """Idle-flow settings belong only to an irrigation-only meter."""
    if not source:
        return False
    nested = source.get(_SECTION_FLOW)
    flat = nested if isinstance(nested, dict) else source
    return (
        not _blank(flat.get(CONF_FLOW_SENSOR))
        and flat.get(CONF_FLOW_SCOPE) == FLOW_SCOPE_IRRIGATION
    )


def _flow_choice_missing(flat: dict[str, Any]) -> bool:
    return not _blank(flat.get(CONF_FLOW_SENSOR)) and flat.get(CONF_FLOW_SCOPE) not in FLOW_SCOPES


def _apply_flow_options(data: dict[str, Any]) -> None:
    """Drop idle-flow settings unless this is an irrigation-only meter."""
    if _blank(data.get(CONF_FLOW_SENSOR)):
        data.pop(CONF_FLOW_SENSOR, None)
        data.pop(CONF_FLOW_KIND, None)
        data.pop(CONF_FLOW_SCOPE, None)
        data.pop(CONF_FLOW_IDLE_GPM, None)
        data.pop(CONF_FLOW_IDLE_ACTION, None)
        return
    data.setdefault(CONF_FLOW_KIND, DEFAULT_FLOW_KIND)
    if data.get(CONF_FLOW_SCOPE) != FLOW_SCOPE_IRRIGATION:
        data.pop(CONF_FLOW_IDLE_GPM, None)
        data.pop(CONF_FLOW_IDLE_ACTION, None)


def _flow_fields(*, show_idle: bool) -> dict[Any, Any]:
    fields: dict[Any, Any] = {
        vol.Optional(CONF_FLOW_SENSOR): _SENSOR,
        vol.Required(CONF_FLOW_KIND, default=DEFAULT_FLOW_KIND): _select(
            FLOW_KINDS, "flow_kind"
        ),
        vol.Optional(CONF_FLOW_SCOPE): _select(FLOW_SCOPES, "flow_scope"),
    }
    if show_idle:
        fields[vol.Required(CONF_FLOW_IDLE_GPM, default=DEFAULT_IDLE_GPM)] = _number(
            0, 20, 0.1, "gal/min"
        )
        fields[vol.Required(CONF_FLOW_IDLE_ACTION, default=FLOW_ACTION_NOTIFY)] = _select(
            FLOW_ACTIONS, "flow_action"
        )
    return fields


def _dynamic_enabled(source: dict[str, Any] | None, *, default: bool) -> bool:
    """True when this form, or the stored options, turn dynamic start on."""
    if not source:
        return default
    nested = source.get(_SECTION_MORNING)
    if isinstance(nested, dict) and CONF_DYNAMIC_START in nested:
        return bool(nested[CONF_DYNAMIC_START])
    if CONF_DYNAMIC_START in source:
        return bool(source[CONF_DYNAMIC_START])
    return default


def _morning_fields(*, show_start: bool) -> dict[Any, Any]:
    """Dynamic start, Don't start before, and the finish time.

    The fixed start time is hidden while dynamic start is on. A stored
    start time is kept so turning the option off later still has a clock.
    """
    fields: dict[Any, Any] = {
        vol.Required(CONF_DYNAMIC_START, default=DEFAULT_DYNAMIC_START): _BOOL,
        vol.Required(
            CONF_EARLIEST_START, default=DEFAULT_EARLIEST_START
        ): selector.TimeSelector(),
        vol.Required(CONF_FINISH_TIME, default=DEFAULT_FINISH_TIME): selector.TimeSelector(),
    }
    if show_start:
        fields[vol.Required(CONF_START_TIME, default=DEFAULT_START_TIME)] = (
            selector.TimeSelector()
        )
    return fields


def _keep_start_time(data: dict[str, Any], previous: dict[str, Any] | None) -> None:
    """Leave a start time stored even when the field was hidden."""
    if CONF_START_TIME in data and not _blank(data.get(CONF_START_TIME)):
        return
    stored = None if previous is None else previous.get(CONF_START_TIME)
    data[CONF_START_TIME] = stored or DEFAULT_START_TIME


def _hub_schema(
    *, sensors_collapsed: bool, show_idle: bool = False, show_start: bool = False
) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name"): _TEXT,
            vol.Optional(CONF_WEATHER_ENTITY): _WEATHER,
            vol.Required(CONF_SEND_PLAN_NOTIFICATIONS, default=True): _BOOL,
            vol.Required(_SECTION_MORNING): section(
                vol.Schema(_morning_fields(show_start=show_start)),
                {"collapsed": False},
            ),
            vol.Required(_SECTION_SENSORS): section(
                vol.Schema(_sensor_fields()),
                {"collapsed": sensors_collapsed},
            ),
            vol.Optional(_SECTION_FLOW): section(
                vol.Schema(_flow_fields(show_idle=show_idle)),
                {"collapsed": False},
            ),
            vol.Required(_SECTION_LOCATION): section(
                vol.Schema(_location_fields()),
                {"collapsed": True},
            ),
        }
    )


def _options_schema(
    *,
    sensors_collapsed: bool,
    simulation: bool = False,
    show_idle: bool = False,
    show_start: bool = True,
) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(CONF_SEND_PLAN_NOTIFICATIONS, default=True): _BOOL,
    }
    if simulation:
        fields[vol.Required(CONF_SCENARIO, default=DEFAULT_SCENARIO)] = _select(
            SCENARIOS, "scenario"
        )
        fields[vol.Required(CONF_BUCKET, default=DEFAULT_BUCKET)] = _select(
            BUCKETS, "bucket"
        )
    fields[vol.Required(_SECTION_SENSORS)] = section(
        vol.Schema(_sensor_fields()),
        {"collapsed": sensors_collapsed},
    )
    fields[vol.Optional(_SECTION_FLOW)] = section(
        vol.Schema(_flow_fields(show_idle=show_idle)),
        {"collapsed": False},
    )
    fields[vol.Required(_SECTION_MORNING)] = section(
        vol.Schema(_morning_fields(show_start=show_start)),
        {"collapsed": False},
    )
    fields[vol.Required(_SECTION_LOCATION)] = section(
        vol.Schema(_location_fields()),
        {"collapsed": True},
    )
    return vol.Schema(fields)


def _simulation_schema(*, show_start: bool = False) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name"): _TEXT,
            vol.Required(CONF_SCENARIO, default=DEFAULT_SCENARIO): _select(
                SCENARIOS, "scenario"
            ),
            vol.Required(CONF_BUCKET, default=DEFAULT_BUCKET): _select(BUCKETS, "bucket"),
            vol.Required(CONF_SEND_PLAN_NOTIFICATIONS, default=True): _BOOL,
            vol.Required(_SECTION_MORNING): section(
                vol.Schema(_morning_fields(show_start=show_start)),
                {"collapsed": False},
            ),
            vol.Required(_SECTION_LOCATION): section(
                vol.Schema(_location_fields()),
                {"collapsed": True},
            ),
        }
    )


_MAX_SETUP_ZONES = 24


def _zone_quick_schema(
    *, simulation: bool, previous: dict[str, Any] | None = None
) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required("name"): _TEXT,
    }
    if not simulation:
        fields[vol.Required(CONF_VALVE_ENTITY)] = _ON_OFF
    plant = previous.get(CONF_PLANT_TYPE) if previous else None
    soil = previous.get(CONF_SOIL_TYPE) if previous else None
    sprinkler = (
        previous.get(CONF_SPRINKLER_TYPE, DEFAULT_SPRINKLER_TYPE)
        if previous
        else DEFAULT_SPRINKLER_TYPE
    )
    sun = previous.get(CONF_SUN_EXPOSURE, "full_sun") if previous else "full_sun"
    plant_field = (
        vol.Required(CONF_PLANT_TYPE)
        if plant is None
        else vol.Required(CONF_PLANT_TYPE, default=plant)
    )
    soil_field = (
        vol.Required(CONF_SOIL_TYPE)
        if soil is None
        else vol.Required(CONF_SOIL_TYPE, default=soil)
    )
    fields.update(
        {
            plant_field: _select(PLANT_TYPES, "plant_type"),
            soil_field: _select(SOIL_TYPES, "soil_type"),
            vol.Required(CONF_SPRINKLER_TYPE, default=sprinkler): _select(
                SPRINKLER_TYPES, "sprinkler_type"
            ),
            vol.Required(CONF_SUN_EXPOSURE, default=sun): _select(
                SUN_EXPOSURES, "sun_exposure"
            ),
        }
    )
    if simulation:
        fields[vol.Optional(CONF_AREA_SQFT)] = _number(1, 1_000_000, 1, "ft²")
        fields[vol.Optional(CONF_SLOPE_PCT)] = _number(0, 100, 0.1, "%")
    return vol.Schema(fields)


def _advanced_schema() -> vol.Schema:
    """Overrides only. No suggested preset numbers, or a save would store them."""
    return vol.Schema(
        {
            vol.Required(_SECTION_PLANT): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_ROOT_DEPTH_IN): _number(1, 120, 0.5, "in"),
                        vol.Optional(CONF_AWC_OVERRIDE): _number(0.01, 0.6, 0.01),
                        vol.Optional(CONF_INTAKE_IN_HR): _number(0.01, 5, 0.01, "in/h"),
                        vol.Optional(CONF_DEPLETION): _number(0.1, 0.8, 0.01),
                        vol.Optional(CONF_KC_OVERRIDE): _number(0, 1.5, 0.01),
                        vol.Optional(CONF_MIN_INTERVAL_DAYS): _number(0, 60, 1, "d"),
                        vol.Optional(CONF_TARGET_DEPTH_IN): _number(0.1, 12, 0.1, "in"),
                        vol.Optional(CONF_FREEZE_SKIP_F): _number(20, 50, 1, "°F"),
                        vol.Optional(CONF_WIND_SKIP_MPH): _number(0, 40, 1, "mph"),
                        vol.Optional(CONF_MOISTURE_SKIP_PCT): _number(0, 100, 1, "%"),
                        vol.Optional(CONF_DORMANT_BELOW_F): _number(20, 80, 1, "°F"),
                        vol.Optional(CONF_SLOW_BELOW_F): _number(20, 90, 1, "°F"),
                        vol.Optional(CONF_HEAT_ABOVE_F): _number(60, 110, 1, "°F"),
                        vol.Optional(CONF_MAINTENANCE_WATERING): _BOOL,
                        vol.Optional(CONF_MOISTURE_LEARN): _BOOL,
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required(_SECTION_HARDWARE): section(
                vol.Schema(
                    {
                        vol.Optional(CONF_PRECIPITATION_RATE): _number(
                            0.01, 10, 0.01, "in/h"
                        ),
                        vol.Optional(CONF_EFFICIENCY): _number(0.1, 1, 0.01),
                        vol.Optional(CONF_SLOPE_PCT): _number(0, 100, 0.1, "%"),
                        vol.Optional(CONF_MAX_CYCLE_MIN): _number(1, 180, 1, "min"),
                        vol.Optional(CONF_SOAK_MIN): _number(0, 180, 1, "min"),
                        vol.Optional(CONF_FLOW_GPM): _number(0.1, 200, 0.1, "gal/min"),
                        vol.Optional(CONF_AREA_SQFT): _number(1, 1_000_000, 1, "ft²"),
                        vol.Optional(CONF_BASELINE_MINUTES): _number(1, 180, 1, "min"),
                        vol.Optional(CONF_BASELINE_DAYS): _number(0, 7, 1, "d"),
                        vol.Optional(CONF_MAX_RUN_MIN): _number(1, 240, 1, "min"),
                    }
                ),
                {"collapsed": True},
            ),
            vol.Required(_SECTION_MEASURE): section(
                vol.Schema(
                    {
                        vol.Required(CONF_PRIORITY, default=DEFAULT_PRIORITY): _number(
                            1, 99, 1
                        ),
                        vol.Optional(CONF_MOISTURE_SENSOR): _SENSOR,
                        vol.Required(
                            CONF_MOISTURE_MODE, default=DEFAULT_MOISTURE_MODE
                        ): _select(MOISTURE_MODES, "moisture_mode"),
                        vol.Required(
                            CONF_MOISTURE_KIND, default=DEFAULT_MOISTURE_KIND
                        ): _select(MOISTURE_KINDS, "moisture_kind"),
                        vol.Required(
                            CONF_MOISTURE_WEIGHT, default=DEFAULT_MOISTURE_WEIGHT
                        ): _number(0, 1, 0.05),
                        vol.Optional(CONF_FIELD_CAPACITY): _number(0.01, 0.6, 0.01),
                        vol.Required(
                            CONF_FLOW_LOW_RATIO, default=DEFAULT_FLOW_LOW_RATIO
                        ): _number(0, 1, 0.05),
                        vol.Required(
                            CONF_FLOW_LEAK_RATIO, default=DEFAULT_FLOW_LEAK_RATIO
                        ): _number(1, 5, 0.05),
                        vol.Optional(CONF_RAIN_SENSOR): _RAIN,
                        vol.Optional(CONF_RAIN_RATE_MIN): _number(0, 1000, 0.001),
                    }
                ),
                {"collapsed": True},
            ),
        }
    )


def _rate_errors(sprinkler: str, data: dict[str, Any]) -> dict[str, str]:
    """Bubblers have no published rate. A half-entered GPM/area pair is rejected."""
    has_rate = not _blank(data.get(CONF_PRECIPITATION_RATE))
    has_flow = not _blank(data.get(CONF_FLOW_GPM))
    has_area = not _blank(data.get(CONF_AREA_SQFT))
    if has_flow != has_area and not has_rate:
        return {"base": "precipitation_rate"}
    if sprinkler == SPRINKLER_BUBBLER and not has_rate and not (has_flow and has_area):
        return {"base": "precipitation_rate"}
    return {}


def _has_climate(weather: Any, temperature: Any) -> bool:
    return not _blank(weather) or not _blank(temperature)


class SmartWaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Sprinklecast hub."""

    VERSION = 10
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Hold the hub draft while the zone forms run."""
        self._hub_title = ""
        self._hub_data: dict[str, Any] = {}
        self._hub_options: dict[str, Any] = {}
        self._hub_simulation = False
        self._zone_total = 0
        self._pending_zones: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmartWaterOptionsFlow:
        """Return the options flow."""
        return SmartWaterOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Zones are added from the hub's device page."""
        return {SUBENTRY_ZONE: ZoneSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a live hub, a simulation, or a Smart Water import."""
        menu = ["live", "simulation"]
        if self.hass.config_entries.async_entries(LEGACY_DOMAIN):
            menu.append("import_legacy")
        return self.async_show_menu(step_id="user", menu_options=menu)

    async def async_step_import_legacy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Copy leftover Smart Water hubs. No YAML key is required.

        A still-loaded Smart Water component owns the entities, so this step
        only removes the old folder and asks for a restart.
        """
        from .legacy import async_import_smart_water, legacy_folder, remove_legacy_folder

        if LEGACY_DOMAIN in self.hass.config.components:
            if user_input is None:
                return self.async_show_form(
                    step_id="import_legacy",
                    data_schema=vol.Schema({}),
                )
            await self.hass.async_add_executor_job(remove_legacy_folder, self.hass)
            folder = legacy_folder(self.hass)
            if folder.exists() or folder.is_symlink():
                return self.async_abort(reason="import_failed")
            return self.async_abort(reason="restart_to_import")
        await async_import_smart_water(self.hass)
        if self.hass.config_entries.async_entries(LEGACY_DOMAIN):
            return self.async_abort(reason="import_failed")
        if not self.hass.config_entries.async_entries(DOMAIN):
            return self.async_abort(reason="import_failed")
        return self.async_abort(reason="imported")

    async def async_step_live(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name, optional weather, and collapsed sensor and schedule sections."""
        found = discover(_entity_hints(self.hass))
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            flat = _flatten(user_input, _HUB_SECTIONS)
            if _blank(flat.get(CONF_LATITUDE)) != _blank(flat.get(CONF_LONGITUDE)):
                errors["base"] = "latitude_pair"
            elif not _has_climate(
                flat.get(CONF_WEATHER_ENTITY), flat.get(CONF_TEMPERATURE_SENSOR)
            ):
                errors["base"] = "need_weather"
            elif _flow_choice_missing(flat):
                errors["base"] = "flow_scope"
            else:
                detail = _unit_detail(
                    self.hass, flat, weather=flat.get(CONF_WEATHER_ENTITY)
                ) or ""
                if detail:
                    errors["base"] = "bad_unit"
                else:
                    return self._create(flat)
        suggested: dict[str, Any] = dict(user_input or {})
        if not suggested:
            if found.weather:
                suggested[CONF_WEATHER_ENTITY] = found.weather
            sensors = _present(
                {
                    CONF_TEMPERATURE_SENSOR: found.temperature,
                    CONF_HUMIDITY_SENSOR: found.humidity,
                    CONF_WIND_SENSOR: found.wind,
                    CONF_PRESSURE_SENSOR: found.pressure,
                    CONF_SOLAR_SENSOR: found.solar,
                    CONF_UV_SENSOR: found.uv,
                    CONF_RAIN_AMOUNT_SENSOR: found.rain,
                    CONF_RAIN_KIND: found.rain_kind,
                },
                _SENSOR_KEYS,
            )
            if sensors:
                suggested[_SECTION_SENSORS] = sensors
        sensors_open = any(
            (
                found.temperature,
                found.humidity,
                found.wind,
                found.pressure,
                found.solar,
                found.uv,
                found.rain,
            )
        )
        return self.async_show_form(
            step_id="live",
            data_schema=self.add_suggested_values_to_schema(
                _hub_schema(
                    sensors_collapsed=not sensors_open,
                    show_idle=_show_idle(user_input),
                    show_start=not _dynamic_enabled(user_input, default=True),
                ),
                suggested,
            ),
            errors=errors,
            description_placeholders={"detail": detail},
            last_step=False,
        )

    async def async_step_simulation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name only. Weather, sensors, and valves are not required."""
        errors: dict[str, str] = {}
        if user_input is not None:
            flat = _flatten(
                user_input, frozenset({_SECTION_LOCATION, _SECTION_MORNING})
            )
            if _blank(flat.get(CONF_LATITUDE)) != _blank(flat.get(CONF_LONGITUDE)):
                errors["base"] = "latitude_pair"
            else:
                return self._create_simulation(flat)
        return self.async_show_form(
            step_id="simulation",
            data_schema=self.add_suggested_values_to_schema(
                _simulation_schema(
                    show_start=not _dynamic_enabled(user_input, default=True)
                ),
                user_input or {},
            ),
            errors=errors,
            last_step=False,
        )

    def _create_simulation(self, flat: dict[str, Any]) -> ConfigFlowResult:
        draft = _drop_blanks(flat)
        name = str(draft.pop("name"))
        scenario = str(draft.pop(CONF_SCENARIO, DEFAULT_SCENARIO))
        bucket = str(draft.pop(CONF_BUCKET, DEFAULT_BUCKET))
        draft.pop("dry_run", None)
        draft.pop("schedule_preset", None)
        draft.setdefault(CONF_SEND_PLAN_NOTIFICATIONS, True)
        draft.setdefault(CONF_DYNAMIC_START, DEFAULT_DYNAMIC_START)
        _keep_start_time(draft, None)
        draft[CONF_SCENARIO] = scenario
        draft[CONF_BUCKET] = bucket
        return self._queue_zones(
            title=name,
            data={CONF_SIMULATION: True},
            options=draft,
            simulation=True,
        )

    def _create(self, flat: dict[str, Any]) -> ConfigFlowResult:
        draft = _drop_blanks(flat)
        name = str(draft.pop("name"))
        weather = draft.pop(CONF_WEATHER_ENTITY, None)
        draft.pop("dry_run", None)
        draft.pop("schedule_preset", None)
        draft.setdefault(CONF_SEND_PLAN_NOTIFICATIONS, True)
        draft.setdefault(CONF_DYNAMIC_START, DEFAULT_DYNAMIC_START)
        _keep_start_time(draft, None)
        _apply_flow_options(draft)
        data: dict[str, Any] = {}
        if weather:
            data[CONF_WEATHER_ENTITY] = weather
        return self._queue_zones(
            title=name, data=data, options=draft, simulation=False
        )

    def _queue_zones(
        self,
        *,
        title: str,
        data: dict[str, Any],
        options: dict[str, Any],
        simulation: bool,
    ) -> ConfigFlowResult:
        """Ask how many zones, then collect them before the hub is created."""
        self._hub_title = title
        self._hub_data = data
        self._hub_options = options
        self._hub_simulation = simulation
        self._zone_total = 0
        self._pending_zones = []
        return self.async_show_form(
            step_id="zone_count",
            data_schema=vol.Schema(
                {
                    vol.Required("zones", default=1): _number(0, _MAX_SETUP_ZONES, 1),
                }
            ),
        )

    async def async_step_zone_count(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """How many zones to add with the hub. Zero creates the hub alone."""
        if user_input is not None:
            self._zone_total = int(user_input["zones"])
            self._pending_zones = []
            if self._zone_total <= 0:
                return self._finish_hub()
            return await self.async_step_zone()
        return self.async_show_form(
            step_id="zone_count",
            data_schema=vol.Schema(
                {
                    vol.Required("zones", default=1): _number(0, _MAX_SETUP_ZONES, 1),
                }
            ),
        )

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One quick zone. Advanced is edited on the zone after setup."""
        errors: dict[str, str] = {}
        previous = self._previous_zone()
        if user_input is not None:
            errors = self._accept_zone(user_input)
            if not errors:
                if len(self._pending_zones) >= self._zone_total:
                    return self._finish_hub()
                previous = self._previous_zone()
                user_input = None
        return self.async_show_form(
            step_id="zone",
            data_schema=self.add_suggested_values_to_schema(
                _zone_quick_schema(
                    simulation=self._hub_simulation, previous=previous
                ),
                user_input or {},
            ),
            description_placeholders={
                "index": str(len(self._pending_zones) + 1),
                "total": str(self._zone_total),
            },
            errors=errors,
            last_step=len(self._pending_zones) + 1 >= self._zone_total,
        )

    def _previous_zone(self) -> dict[str, Any] | None:
        if not self._pending_zones:
            return None
        return dict(self._pending_zones[-1]["data"])

    def _accept_zone(self, user_input: dict[str, Any]) -> dict[str, str]:
        name = str(user_input["name"]).strip()
        slug = _zone_slug(name)
        for zone in self._pending_zones:
            if (
                zone["title"].casefold() == name.casefold()
                or zone["unique_id"] == slug
            ):
                return {"name": "name_exists"}
        data = dict(user_input)
        data.pop("same_as_previous", None)
        data.pop("name", None)
        stored = _drop_blanks(data)
        if self._hub_simulation:
            stored[CONF_VALVE_ENTITY] = f"simulation.{slug}"
        self._pending_zones.append(
            {
                "data": stored,
                "subentry_type": SUBENTRY_ZONE,
                "title": name,
                "unique_id": slug,
            }
        )
        return {}

    def _finish_hub(self) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._hub_title,
            data=self._hub_data,
            options=self._hub_options,
            subentries=list(self._pending_zones),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the hub name. Weather can be cleared when a temperature sensor exists."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        detail = ""
        simulating = bool(entry.data.get(CONF_SIMULATION))
        if user_input is not None:
            weather = user_input.get(CONF_WEATHER_ENTITY)
            if not simulating and not _has_climate(
                weather, entry.options.get(CONF_TEMPERATURE_SENSOR)
            ):
                errors["base"] = "need_weather"
            elif not _blank(weather):
                detail = _unit_detail(self.hass, {}, weather=weather) or ""
                if detail:
                    errors["base"] = "bad_unit"
            if not errors:
                data = {
                    key: value
                    for key, value in entry.data.items()
                    if key != CONF_WEATHER_ENTITY
                }
                if not _blank(weather):
                    data[CONF_WEATHER_ENTITY] = weather
                return self.async_update_and_abort(
                    entry,
                    title=str(user_input["name"]).strip(),
                    data=data,
                )
        suggested: dict[str, Any] = {"name": entry.title}
        if entry.data.get(CONF_WEATHER_ENTITY):
            suggested[CONF_WEATHER_ENTITY] = entry.data[CONF_WEATHER_ENTITY]
        if user_input:
            suggested.update(user_input)
        schema: dict[Any, Any] = {vol.Required("name"): _TEXT}
        if not simulating:
            schema[vol.Optional(CONF_WEATHER_ENTITY)] = _WEATHER
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(schema), suggested),
            errors=errors,
            description_placeholders={"detail": detail},
        )


class SmartWaterOptionsFlow(OptionsFlow):
    """Edit hub options. A listener reloads the entry when this finishes."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sensors and the schedule, in two collapsed sections."""
        current = dict(self.config_entry.options)
        simulating = bool(self.config_entry.data.get(CONF_SIMULATION))
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            flat = _flatten(user_input, _HUB_SECTIONS)
            if _blank(flat.get(CONF_LATITUDE)) != _blank(flat.get(CONF_LONGITUDE)):
                errors["base"] = "latitude_pair"
            elif not simulating and not _has_climate(
                self.config_entry.data.get(CONF_WEATHER_ENTITY),
                flat.get(CONF_TEMPERATURE_SENSOR),
            ):
                errors["base"] = "need_weather"
            elif _flow_choice_missing(flat):
                errors["base"] = "flow_scope"
            else:
                detail = _unit_detail(self.hass, flat) or ""
                if detail:
                    errors["base"] = "bad_unit"
            if not errors:
                data = _drop_blanks(flat)
                data.pop("dry_run", None)
                data.pop("schedule_preset", None)
                data.setdefault(CONF_SEND_PLAN_NOTIFICATIONS, True)
                data.setdefault(CONF_DYNAMIC_START, DEFAULT_DYNAMIC_START)
                _keep_start_time(data, current)
                _apply_flow_options(data)
                return self.async_create_entry(data=data)
        show_idle = _show_idle(user_input) if user_input else _show_idle(current)
        show_start = not _dynamic_enabled(
            user_input if user_input is not None else current, default=False
        )
        flow_keys = _FLOW_KEYS + (_FLOW_IDLE_KEYS if show_idle else ())
        suggested = user_input or {
            CONF_SEND_PLAN_NOTIFICATIONS: current.get(
                CONF_SEND_PLAN_NOTIFICATIONS,
                bool(str(current.get(CONF_NOTIFY_TARGET) or "").strip()),
            ),
            CONF_SCENARIO: current.get(CONF_SCENARIO, DEFAULT_SCENARIO),
            CONF_BUCKET: current.get(CONF_BUCKET, DEFAULT_BUCKET),
            _SECTION_SENSORS: _present(current, _SENSOR_KEYS),
            _SECTION_FLOW: _present(current, flow_keys),
            _SECTION_MORNING: _present(current, _MORNING_KEYS),
            _SECTION_LOCATION: _present(current, _LOCATION_KEYS),
        }
        sensors_open = bool(current.get(CONF_TEMPERATURE_SENSOR)) or bool(
            current.get(CONF_RAIN_AMOUNT_SENSOR)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _options_schema(
                    sensors_collapsed=not sensors_open,
                    simulation=simulating,
                    show_idle=show_idle,
                    show_start=show_start,
                ),
                suggested,
            ),
            errors=errors,
            description_placeholders={"detail": detail},
            last_step=True,
        )


class ZoneSubentryFlow(ConfigSubentryFlow):
    """Add or edit one irrigation zone."""

    def __init__(self) -> None:
        """Start with the short form. Advanced is a second step."""
        self._quick: dict[str, Any] = {}
        self._editing = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name, on/off entity, plant, soil, sprinkler, and sun."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._name_errors(str(user_input["name"]))
            if not errors:
                self._quick = dict(user_input)
                return await self.async_step_advanced()
        suggested = dict(user_input or {})
        if self._editing and not suggested:
            subentry = self._get_reconfigure_subentry()
            suggested = {
                "name": subentry.title,
                **_present(
                    dict(subentry.data),
                    (
                        CONF_VALVE_ENTITY,
                        CONF_PLANT_TYPE,
                        CONF_SOIL_TYPE,
                        CONF_SPRINKLER_TYPE,
                        CONF_SUN_EXPOSURE,
                        CONF_AREA_SQFT,
                        CONF_SLOPE_PCT,
                    ),
                ),
            }
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _zone_quick_schema(simulation=self._simulation()),
                suggested,
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing zone, starting from its saved values."""
        self._editing = True
        return await self.async_step_user(user_input)

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Collapsed overrides. An empty section keeps the preset."""
        errors: dict[str, str] = {}
        detail = ""
        if user_input is not None:
            flat = _flatten(user_input, _ZONE_SECTIONS)
            errors = _rate_errors(str(self._quick[CONF_SPRINKLER_TYPE]), flat)
            if not errors:
                detail = _unit_detail(self.hass, flat) or ""
                if detail:
                    errors["base"] = "bad_unit"
            if not errors:
                self._quick.update(flat)
                return self._finish()
        stored: dict[str, Any] = {}
        if self._editing:
            stored = dict(self._get_reconfigure_subentry().data)
        suggested: dict[str, Any] = {
            _SECTION_PLANT: _present(stored, _PLANT_KEYS),
            _SECTION_HARDWARE: _present(stored, _HARDWARE_KEYS),
            _SECTION_MEASURE: _present(stored, _MEASURE_KEYS),
        }
        if user_input:
            suggested.update(user_input)
        context = dict(stored)
        context.update(self._quick)
        slope = context.get(CONF_SLOPE_PCT)
        placeholders = preset_placeholders(
            plant_type=str(context[CONF_PLANT_TYPE]),
            soil_type=str(context[CONF_SOIL_TYPE]),
            sprinkler_type=str(
                context.get(CONF_SPRINKLER_TYPE, DEFAULT_SPRINKLER_TYPE)
            ),
            slope_pct=0.0 if _blank(slope) else float(slope),
            month=dt_util.now().month,
            sun_exposure=str(context.get(CONF_SUN_EXPOSURE, "full_sun")),
        )
        placeholders["detail"] = detail
        return self.async_show_form(
            step_id="advanced",
            data_schema=self.add_suggested_values_to_schema(
                _advanced_schema(), suggested
            ),
            description_placeholders=placeholders,
            errors=errors,
            last_step=True,
        )

    def _name_errors(self, name: str) -> dict[str, str]:
        entry = self._get_entry()
        current_id = (
            self._get_reconfigure_subentry().subentry_id if self._editing else None
        )
        slug = _zone_slug(name)
        for subentry in entry.subentries.values():
            if subentry.subentry_id == current_id:
                continue
            if subentry.title.casefold() == name.strip().casefold() or (
                subentry.unique_id == slug
            ):
                return {"name": "name_exists"}
        return {}

    def _simulation(self) -> bool:
        return bool(self._get_entry().data.get(CONF_SIMULATION))

    def _finish(self) -> SubentryFlowResult:
        name = str(self._quick.pop("name")).strip()
        data = _drop_blanks(self._quick)
        if self._simulation():
            data[CONF_VALVE_ENTITY] = f"simulation.{_zone_slug(name)}"
        if self._editing:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=name,
                unique_id=_zone_slug(name),
                data=data,
            )
        return self.async_create_entry(
            title=name, data=data, unique_id=_zone_slug(name)
        )
