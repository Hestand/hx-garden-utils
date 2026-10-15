"""Constants for the Smart Water integration."""

from __future__ import annotations

DOMAIN = "smart_water"
NAME = "Smart Water"
VERSION = "0.2.0"

# Stored on the hub. v0.2 still never waters; clearing dry-run only records intent.
CONF_DRY_RUN = "dry_run"
CONF_MODE = "mode"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_ELEVATION_M = "elevation_m"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_NOTIFY_TARGET = "notify_target"
CONF_RAIN_SENSOR = "rain_sensor"
CONF_RAIN_AMOUNT_SENSOR = "rain_amount_sensor"
CONF_RAIN_KIND = "rain_kind"
CONF_UV_SENSOR = "uv_sensor"
CONF_ROUND_MINUTES = "round_minutes"
CONF_SCHEDULE_PRESET = "schedule_preset"
CONF_ALLOWED_WEEKDAYS = "allowed_weekdays"
CONF_BLACKOUT_START_HOUR = "blackout_start_hour"
CONF_BLACKOUT_END_HOUR = "blackout_end_hour"
CONF_DRIP_IGNORES_SCHEDULE = "drip_ignores_schedule"
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
CONF_SPRINKLER_TYPE = "sprinkler_type"
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
CONF_MOISTURE_SENSOR = "moisture_sensor"
CONF_MOISTURE_MODE = "moisture_mode"
CONF_MOISTURE_KIND = "moisture_kind"
CONF_MOISTURE_WEIGHT = "moisture_weight"
CONF_FIELD_CAPACITY = "field_capacity_vwc"
CONF_FLOW_SENSOR = "flow_sensor"
CONF_FLOW_KIND = "flow_kind"
CONF_FLOW_LOW_RATIO = "flow_low_ratio"
CONF_FLOW_LEAK_RATIO = "flow_leak_ratio"

MODE_AUTO = "auto"
MODE_NOTIFY_ONLY = "notify_only"
MODE_OFF = "off"
MODES = (MODE_AUTO, MODE_NOTIFY_ONLY, MODE_OFF)

SUBENTRY_ZONE = "zone"

# Off by default. v0.2 still will not open a valve: there is no executor.
DEFAULT_DRY_RUN = False

DEFAULT_ELEVATION_M = 219.0
DEFAULT_SUNRISE_BUFFER_MIN = 30
DEFAULT_PLAN_HOUR = 23
DEFAULT_WIND_HEIGHT_M = 2.0
DEFAULT_EFFICIENCY = 1.0
DEFAULT_PRIORITY = 10
DEFAULT_ROUND_MINUTES = True
DEFAULT_ADJUSTMENT_PCT = 100.0
DEFAULT_MOISTURE_WEIGHT = 0.5
DEFAULT_FLOW_LOW_RATIO = 0.5
DEFAULT_FLOW_LEAK_RATIO = 1.5
DEFAULT_SPRINKLER_TYPE = "spray"
DEFAULT_SCHEDULE_PRESET = "none"
DEFAULT_RAIN_KIND = "daily_total"
DEFAULT_MOISTURE_MODE = "off"
DEFAULT_MOISTURE_KIND = "relative"
DEFAULT_FLOW_KIND = "total"

# Rule of thumb, not FAO: about 100 W/m² of broadband sun per UV index.
# Tempest users should prefer the solar-radiation entity. UV is only a fallback.
UV_INDEX_TO_W_M2 = 100.0

RAIN_KIND_DAILY = "daily_total"
RAIN_KIND_CUMULATIVE = "cumulative"
RAIN_KIND_RATE = "rate"
RAIN_KINDS = (RAIN_KIND_DAILY, RAIN_KIND_CUMULATIVE, RAIN_KIND_RATE)

SCHEDULE_NONE = "none"
SCHEDULE_WACO_ODD = "waco_odd"
SCHEDULE_WACO_EVEN = "waco_even"
SCHEDULE_CUSTOM = "custom"
SCHEDULE_PRESETS = (
    SCHEDULE_NONE,
    SCHEDULE_WACO_ODD,
    SCHEDULE_WACO_EVEN,
    SCHEDULE_CUSTOM,
)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# City of Waco year-round outdoor rules, effective 1 July 2024.
# Odd addresses: Sun/Tue/Thu. Even: Mon/Wed/Sat. No Friday.
# No watering 10:00–19:00. https://www.waco-texas.com/Departments/Water-Treatment/Water-Conservation
WACO_ODD_DAYS = ("sun", "tue", "thu")
WACO_EVEN_DAYS = ("mon", "wed", "sat")
WACO_BLACKOUT_START = 10
WACO_BLACKOUT_END = 19

SPRINKLER_SPRAY = "spray"
SPRINKLER_ROTOR = "rotor"
SPRINKLER_MP = "mp_rotator"
SPRINKLER_DRIP = "drip"
SPRINKLER_BUBBLER = "bubbler"
SPRINKLER_TYPES = (
    SPRINKLER_SPRAY,
    SPRINKLER_ROTOR,
    SPRINKLER_MP,
    SPRINKLER_DRIP,
    SPRINKLER_BUBBLER,
)
SPRINKLERS_WITHOUT_SOAK = frozenset({SPRINKLER_DRIP, SPRINKLER_BUBBLER})

MOISTURE_OFF = "off"
MOISTURE_CORRECT = "correct"
MOISTURE_OVERRIDE = "override"
MOISTURE_MODES = (MOISTURE_OFF, MOISTURE_CORRECT, MOISTURE_OVERRIDE)
MOISTURE_KIND_RELATIVE = "relative"
MOISTURE_KIND_VWC = "vwc"
MOISTURE_KINDS = (MOISTURE_KIND_RELATIVE, MOISTURE_KIND_VWC)

FLOW_KIND_RATE = "rate"
FLOW_KIND_TOTAL = "total"
FLOW_KINDS = (FLOW_KIND_TOTAL, FLOW_KIND_RATE)

SERVICE_CALCULATE_PLAN = "calculate_plan"
SERVICE_RESET_BUCKET = "reset_bucket"
SERVICE_SET_BUCKET = "set_bucket"
SERVICE_MARK_WATERED = "mark_watered"
SERVICE_SKIP_ZONE = "skip_zone"
SERVICE_PAUSE_ZONE = "pause_zone"
SERVICE_SET_ADJUSTMENT = "set_adjustment"
SERVICE_RUN_NOW = "run_now"

SERVICES = (
    SERVICE_CALCULATE_PLAN,
    SERVICE_RESET_BUCKET,
    SERVICE_SET_BUCKET,
    SERVICE_MARK_WATERED,
    SERVICE_SKIP_ZONE,
    SERVICE_PAUSE_ZONE,
    SERVICE_SET_ADJUSTMENT,
    SERVICE_RUN_NOW,
)

PLATFORMS: list[str] = ["sensor", "switch", "number", "button"]

# FAO-56 ignores daily rain below about 0.2 × ET0 (Chapter 8).
RAIN_IGNORE_FRACTION_OF_ET0 = 0.2
