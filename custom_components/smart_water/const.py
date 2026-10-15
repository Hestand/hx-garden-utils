"""Constants for the Smart Water integration."""

from __future__ import annotations

DOMAIN = "smart_water"
NAME = "Smart Water"
VERSION = "0.1.0"

# Stored on the hub. v0.1 never waters; clearing this only records intent.
CONF_DRY_RUN = "dry_run"
CONF_MODE = "mode"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_ELEVATION_M = "elevation_m"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_NOTIFY_TARGET = "notify_target"
CONF_RAIN_SENSOR = "rain_sensor"
CONF_SUNRISE_BUFFER_MIN = "sunrise_buffer_min"
CONF_PLAN_HOUR = "plan_hour"
CONF_EARLIEST_HOUR = "earliest_hour"
CONF_FORECAST_SKIP_MM = "forecast_skip_mm"
CONF_MAX_DAILY_RUNTIME_MIN = "max_daily_runtime_min"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_WIND_SENSOR = "wind_sensor"
CONF_PRESSURE_SENSOR = "pressure_sensor"
CONF_SOLAR_SENSOR = "solar_radiation_sensor"
CONF_WIND_HEIGHT_M = "wind_height_m"

CONF_PLANT_TYPE = "plant_type"
CONF_SOIL_TYPE = "soil_type"
CONF_SLOPE_PCT = "slope_pct"
CONF_SUN_EXPOSURE = "sun_exposure"
CONF_PRECIPITATION_RATE = "precipitation_rate_in_hr"
CONF_FLOW_GPM = "flow_gpm"
CONF_AREA_SQFT = "area_sqft"
CONF_ROOT_DEPTH_IN = "root_depth_in"
CONF_DEPLETION = "depletion_fraction"
CONF_EFFICIENCY = "efficiency"
CONF_MAX_CYCLE_MIN = "max_cycle_min"
CONF_SOAK_MIN = "soak_min"
CONF_PRIORITY = "priority"
CONF_VALVE_ENTITY = "valve_entity"
CONF_KC_OVERRIDE = "kc_override"
CONF_AWC_OVERRIDE = "awc_override"

MODE_AUTO = "auto"
MODE_NOTIFY_ONLY = "notify_only"
MODE_OFF = "off"
MODES = (MODE_AUTO, MODE_NOTIFY_ONLY, MODE_OFF)

SUBENTRY_ZONE = "zone"

# Typed by the user to store dry_run=False. v0.1 still will not open a valve.
ARM_PHRASE = "ENABLE WATERING"

DEFAULT_ELEVATION_M = 219.0
DEFAULT_SUNRISE_BUFFER_MIN = 30
DEFAULT_PLAN_HOUR = 23
DEFAULT_WIND_HEIGHT_M = 2.0
DEFAULT_EFFICIENCY = 1.0
DEFAULT_PRIORITY = 10

SERVICE_CALCULATE_PLAN = "calculate_plan"
SERVICE_RESET_BUCKET = "reset_bucket"
SERVICE_SET_BUCKET = "set_bucket"
SERVICE_MARK_WATERED = "mark_watered"
SERVICE_SKIP_ZONE = "skip_zone"

SERVICES = (
    SERVICE_CALCULATE_PLAN,
    SERVICE_RESET_BUCKET,
    SERVICE_SET_BUCKET,
    SERVICE_MARK_WATERED,
    SERVICE_SKIP_ZONE,
)

PLATFORMS: list[str] = ["sensor", "switch"]

# FAO-56 ignores daily rain below about 0.2 × ET0 (Chapter 8).
RAIN_IGNORE_FRACTION_OF_ET0 = 0.2
