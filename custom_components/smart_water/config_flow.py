"""Config and options flows for Smart Water.

Zones are config subentries. Dry-run defaults off. v0.1 still will not open
a valve, because there is no executor.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    FlowType,
    OptionsFlow,
    SubentryFlowContext,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AREA_SQFT,
    CONF_AWC_OVERRIDE,
    CONF_DEPLETION,
    CONF_DRY_RUN,
    CONF_EARLIEST_HOUR,
    CONF_EFFICIENCY,
    CONF_ELEVATION_M,
    CONF_FLOW_GPM,
    CONF_FORECAST_SKIP_MM,
    CONF_HUMIDITY_SENSOR,
    CONF_KC_OVERRIDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MAX_CYCLE_MIN,
    CONF_MAX_DAILY_RUNTIME_MIN,
    CONF_MODE,
    CONF_NOTIFY_TARGET,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_PRESSURE_SENSOR,
    CONF_PRIORITY,
    CONF_RAIN_SENSOR,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOAK_MIN,
    CONF_SOIL_TYPE,
    CONF_SOLAR_SENSOR,
    CONF_SUNRISE_BUFFER_MIN,
    CONF_SUN_EXPOSURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WIND_HEIGHT_M,
    CONF_WIND_SENSOR,
    DEFAULT_DRY_RUN,
    DEFAULT_EFFICIENCY,
    DEFAULT_ELEVATION_M,
    DEFAULT_PLAN_HOUR,
    DEFAULT_PRIORITY,
    DEFAULT_SUNRISE_BUFFER_MIN,
    DEFAULT_WIND_HEIGHT_M,
    DOMAIN,
    MODE_NOTIFY_ONLY,
    MODES,
    SUBENTRY_ZONE,
)
from .soil import PLANT_TYPES, PLANTS, SOIL_TYPES, SUN_EXPOSURES

_WEATHER = selector.EntitySelector(selector.EntitySelectorConfig(domain="weather"))
_SENSOR = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
_BINARY = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="binary_sensor")
)
_VALVE = selector.EntitySelector(selector.EntitySelectorConfig(domain="valve"))


def _select(options: tuple[str, ...] | list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options),
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=key,
        )
    )


def _number(
    min_value: float,
    max_value: float,
    step: float,
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


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _drop_blanks(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if not _blank(value)}


def _zone_slug(name: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in name.strip())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "zone"


class SmartWaterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Smart Water hub."""

    VERSION = 1
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Start with an empty draft."""
        self._draft: dict[str, Any] = {}

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
        """Name, weather source, elevation, and optional coordinates."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if (user_input.get(CONF_LATITUDE) is None) ^ (
                user_input.get(CONF_LONGITUDE) is None
            ):
                errors["base"] = "latitude_pair"
            else:
                self._draft.update(user_input)
                return await self.async_step_behavior()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("name"): str,
                        vol.Required(CONF_WEATHER_ENTITY): _WEATHER,
                        vol.Required(
                            CONF_ELEVATION_M, default=DEFAULT_ELEVATION_M
                        ): _number(0, 5000, 0.1, "m"),
                        vol.Optional(CONF_LATITUDE): _number(-90, 90, 0.0001),
                        vol.Optional(CONF_LONGITUDE): _number(-180, 180, 0.0001),
                    }
                ),
                user_input or {},
            ),
            errors=errors,
        )

    async def async_step_behavior(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dry-run, mode, notify target, and the watering window."""
        if user_input is not None:
            self._draft.update(user_input)
            return await self.async_step_sensors()
        return self.async_show_form(
            step_id="behavior",
            data_schema=self.add_suggested_values_to_schema(
                _behavior_schema(),
                {
                    CONF_DRY_RUN: DEFAULT_DRY_RUN,
                    CONF_MODE: MODE_NOTIFY_ONLY,
                    CONF_SUNRISE_BUFFER_MIN: DEFAULT_SUNRISE_BUFFER_MIN,
                    CONF_PLAN_HOUR: DEFAULT_PLAN_HOUR,
                },
            ),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optional Tempest-style sensors. All of them can be left empty."""
        if user_input is not None:
            self._draft.update(user_input)
            return self._create()
        return self.async_show_form(
            step_id="sensors",
            data_schema=_sensor_schema(),
            last_step=True,
        )

    def _create(self) -> ConfigFlowResult:
        draft = _drop_blanks(self._draft)
        name = str(draft.pop("name"))
        weather = draft.pop(CONF_WEATHER_ENTITY)
        draft.setdefault(CONF_DRY_RUN, DEFAULT_DRY_RUN)
        draft.setdefault(CONF_MODE, MODE_NOTIFY_ONLY)
        return self.async_create_entry(
            title=name,
            data={CONF_WEATHER_ENTITY: weather},
            options=draft,
        )

    async def async_on_create_entry(
        self, result: ConfigFlowResult
    ) -> ConfigFlowResult:
        """Open the add-zone flow as soon as the hub exists."""
        created = result.get("result")
        if created is None:
            return result
        subentry_result = await self.hass.config_entries.subentries.async_init(
            (created.entry_id, SUBENTRY_ZONE),
            context=SubentryFlowContext(source=SOURCE_USER),
        )
        result["next_flow"] = (
            FlowType.CONFIG_SUBENTRIES_FLOW,
            subentry_result["flow_id"],
        )
        return result

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the hub name or weather entity."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_and_abort(
                entry,
                title=user_input["name"],
                data_updates={CONF_WEATHER_ENTITY: user_input[CONF_WEATHER_ENTITY]},
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("name"): str,
                        vol.Required(CONF_WEATHER_ENTITY): _WEATHER,
                    }
                ),
                {"name": entry.title, CONF_WEATHER_ENTITY: entry.data.get(CONF_WEATHER_ENTITY)},
            ),
        )


def _behavior_fields() -> dict[Any, Any]:
    """Markers for dry-run, mode, and the watering window."""
    return {
        vol.Required(CONF_DRY_RUN, default=DEFAULT_DRY_RUN): bool,
        vol.Required(CONF_MODE, default=MODE_NOTIFY_ONLY): _select(MODES, "mode"),
        vol.Optional(CONF_NOTIFY_TARGET): str,
        vol.Optional(CONF_RAIN_SENSOR): _BINARY,
        vol.Required(
            CONF_SUNRISE_BUFFER_MIN, default=DEFAULT_SUNRISE_BUFFER_MIN
        ): _number(0, 180, 1, "min"),
        vol.Required(CONF_PLAN_HOUR, default=DEFAULT_PLAN_HOUR): _number(0, 23, 1),
        vol.Optional(CONF_EARLIEST_HOUR): _number(0, 23, 1),
        vol.Optional(CONF_FORECAST_SKIP_MM): _number(0, 100, 0.1, "mm"),
        vol.Optional(CONF_MAX_DAILY_RUNTIME_MIN): _number(1, 600, 1, "min"),
    }


def _behavior_schema() -> vol.Schema:
    return vol.Schema(_behavior_fields())


def _options_schema() -> vol.Schema:
    """Hub options, including the fields collected on the first behavior step."""
    fields: dict[Any, Any] = {
        vol.Required(CONF_ELEVATION_M, default=DEFAULT_ELEVATION_M): _number(
            0, 5000, 0.1, "m"
        ),
        vol.Optional(CONF_LATITUDE): _number(-90, 90, 0.0001),
        vol.Optional(CONF_LONGITUDE): _number(-180, 180, 0.0001),
    }
    fields.update(_behavior_fields())
    return vol.Schema(fields)


def _sensor_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_TEMPERATURE_SENSOR): _SENSOR,
            vol.Optional(CONF_HUMIDITY_SENSOR): _SENSOR,
            vol.Optional(CONF_WIND_SENSOR): _SENSOR,
            vol.Optional(CONF_PRESSURE_SENSOR): _SENSOR,
            vol.Optional(CONF_SOLAR_SENSOR): _SENSOR,
            vol.Required(CONF_WIND_HEIGHT_M, default=DEFAULT_WIND_HEIGHT_M): _number(
                0.5, 30, 0.1, "m"
            ),
        }
    )


class SmartWaterOptionsFlow(OptionsFlow):
    """Edit hub options. A listener reloads the entry when this finishes."""

    def __init__(self) -> None:
        """Hold the draft between steps."""
        self._draft: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Location, dry-run, mode, and the window."""
        if user_input is not None:
            self._draft.update(user_input)
            return await self.async_step_sensors()
        current = dict(self.config_entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _options_schema(),
                current,
            ),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Optional local sensors."""
        if user_input is not None:
            self._draft.update(user_input)
            return self._save()
        return self.async_show_form(
            step_id="sensors",
            data_schema=self.add_suggested_values_to_schema(
                _sensor_schema(), dict(self.config_entry.options)
            ),
            last_step=True,
        )

    def _save(self) -> ConfigFlowResult:
        # Keep the weather entity in entry data. Options replace the rest.
        data = _drop_blanks(self._draft)
        data.setdefault(CONF_DRY_RUN, DEFAULT_DRY_RUN)
        data.setdefault(CONF_MODE, MODE_NOTIFY_ONLY)
        return self.async_create_entry(data=data)


class ZoneSubentryFlow(ConfigSubentryFlow):
    """Add or edit one irrigation zone."""

    def __init__(self) -> None:
        """Start a two-step zone form."""
        self._zone: dict[str, Any] = {}
        self._editing = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name, plant, soil, slope, and sun."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._name_errors(str(user_input["name"]))
            if not errors:
                self._zone.update(user_input)
                return await self.async_step_hydraulics()
        suggested = dict(user_input or {})
        if self._editing and not suggested:
            subentry = self._get_reconfigure_subentry()
            suggested = {"name": subentry.title, **subentry.data}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("name"): str,
                        vol.Required(CONF_PLANT_TYPE): _select(PLANT_TYPES, "plant_type"),
                        vol.Required(CONF_SOIL_TYPE): _select(SOIL_TYPES, "soil_type"),
                        vol.Required(CONF_SLOPE_PCT, default=0): _number(0, 100, 0.1, "%"),
                        vol.Required(CONF_SUN_EXPOSURE, default="full_sun"): _select(
                            SUN_EXPOSURES, "sun_exposure"
                        ),
                    }
                ),
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

    async def async_step_hydraulics(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Precipitation rate, root zone, and the optional valve."""
        errors: dict[str, str] = {}
        profile = PLANTS[self._zone[CONF_PLANT_TYPE]]
        if user_input is not None:
            errors = _hydraulics_errors(user_input)
            if not errors:
                self._zone.update(user_input)
                return self._finish()
        suggested: dict[str, Any] = {
            CONF_ROOT_DEPTH_IN: profile.root_depth_in,
            CONF_DEPLETION: profile.p,
            CONF_EFFICIENCY: DEFAULT_EFFICIENCY,
            CONF_PRIORITY: DEFAULT_PRIORITY,
        }
        if self._editing:
            suggested.update(dict(self._get_reconfigure_subentry().data))
        if user_input:
            suggested.update(user_input)
        return self.async_show_form(
            step_id="hydraulics",
            data_schema=self.add_suggested_values_to_schema(
                _hydraulics_schema(), suggested
            ),
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

    def _finish(self) -> SubentryFlowResult:
        name = str(self._zone.pop("name")).strip()
        data = _drop_blanks(self._zone)
        if self._editing:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=name,
                unique_id=_zone_slug(name),
                data=data,
            )
        return self.async_create_entry(title=name, data=data, unique_id=_zone_slug(name))


def _hydraulics_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_PRECIPITATION_RATE): _number(0.01, 10, 0.01, "in/h"),
            vol.Optional(CONF_FLOW_GPM): _number(0.1, 200, 0.1, "gal/min"),
            vol.Optional(CONF_AREA_SQFT): _number(1, 1_000_000, 1, "ft²"),
            vol.Required(CONF_ROOT_DEPTH_IN): _number(1, 120, 0.5, "in"),
            vol.Required(CONF_DEPLETION): _number(0.1, 0.8, 0.01),
            vol.Required(CONF_EFFICIENCY, default=DEFAULT_EFFICIENCY): _number(0.1, 1, 0.01),
            vol.Optional(CONF_MAX_CYCLE_MIN): _number(1, 180, 1, "min"),
            vol.Optional(CONF_SOAK_MIN): _number(0, 180, 1, "min"),
            vol.Required(CONF_PRIORITY, default=DEFAULT_PRIORITY): _number(1, 99, 1),
            vol.Optional(CONF_VALVE_ENTITY): _VALVE,
            vol.Optional(CONF_RAIN_SENSOR): _BINARY,
            vol.Optional(CONF_KC_OVERRIDE): _number(0, 1.5, 0.01),
            vol.Optional(CONF_AWC_OVERRIDE): _number(0.01, 0.6, 0.01),
        }
    )


def _hydraulics_errors(user_input: dict[str, Any]) -> dict[str, str]:
    has_rate = not _blank(user_input.get(CONF_PRECIPITATION_RATE))
    has_flow = not _blank(user_input.get(CONF_FLOW_GPM))
    has_area = not _blank(user_input.get(CONF_AREA_SQFT))
    if has_rate:
        return {}
    if has_flow and has_area:
        return {}
    return {"base": "precipitation_rate"}
