"""Constants for the Smart Water integration."""

from __future__ import annotations

DOMAIN = "smart_water"
NAME = "Smart Water"
VERSION = "0.11.1"

# Retired option key. v0.5 stores the automatic-watering switch in the hub
# store (default off) and drops this option on migration.
CONF_DRY_RUN = "dry_run"
CONF_MODE = "mode"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_SIMULATION = "simulation"
CONF_SCENARIO = "scenario"
CONF_BUCKET = "bucket"
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
# Retired in 0.8. Migration drops them and writes the morning window.
CONF_SUNRISE_BUFFER_MIN = "sunrise_buffer_min"
CONF_EARLIEST_HOUR = "earliest_hour"
CONF_PLAN_HOUR = "plan_hour"
CONF_START_TIME = "start_time"
CONF_FINISH_TIME = "finish_time"
CONF_EARLIEST_START = "earliest_start"
CONF_DYNAMIC_START = "dynamic_start"
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
CONF_INTAKE_IN_HR = "intake_in_hr"
CONF_MOISTURE_SENSOR = "moisture_sensor"
CONF_MOISTURE_MODE = "moisture_mode"
CONF_MOISTURE_KIND = "moisture_kind"
CONF_MOISTURE_WEIGHT = "moisture_weight"
CONF_FIELD_CAPACITY = "field_capacity_vwc"
CONF_FLOW_SENSOR = "flow_sensor"
CONF_FLOW_KIND = "flow_kind"
CONF_FLOW_SCOPE = "flow_scope"
CONF_FLOW_LOW_RATIO = "flow_low_ratio"
CONF_FLOW_LEAK_RATIO = "flow_leak_ratio"
CONF_FREEZE_SKIP_F = "freeze_skip_f"
CONF_RECENT_RAIN_HOURS = "recent_rain_hours"
CONF_RECENT_RAIN_MM = "recent_rain_mm"
CONF_MAX_RUN_MIN = "max_run_min"
CONF_ZONE_MAX_RUN_MIN = "zone_max_run_min"
CONF_HUB_NIGHTLY_CAP_MIN = "hub_nightly_cap_min"
CONF_FORECAST_PROBABILITY_PCT = "forecast_probability_pct"
CONF_FORECAST_DEFER_DAYS = "forecast_defer_days"
CONF_FORECAST_HOURS = "forecast_hours"
CONF_FREEZE_ALERT = "freeze_alert"
CONF_FREEZE_ALERT_F = "freeze_alert_f"
CONF_HARD_FREEZE_F = "hard_freeze_f"
CONF_MIN_INTERVAL_DAYS = "min_interval_days"
CONF_TARGET_DEPTH_IN = "target_depth_in"
CONF_WIND_SKIP_MPH = "wind_skip_mph"
CONF_MOISTURE_SKIP_PCT = "moisture_skip_pct"
CONF_DORMANT_BELOW_F = "dormant_below_f"
CONF_SLOW_BELOW_F = "slow_below_f"
CONF_HEAT_ABOVE_F = "heat_above_f"
CONF_MAINTENANCE_WATERING = "maintenance_watering"
CONF_MOISTURE_LEARN = "moisture_learn"
CONF_FLOW_HIGH_PCT = "flow_high_pct"
CONF_FLOW_LOW_PCT = "flow_low_pct"
CONF_FLOW_LEARN_RUNS = "flow_learn_runs"
CONF_FLOW_IDLE_GPM = "flow_idle_gpm"
CONF_FLOW_HIGH_ACTION = "flow_high_action"
CONF_FLOW_LOW_ACTION = "flow_low_action"
CONF_FLOW_IDLE_ACTION = "flow_idle_action"
CONF_COST_PER_1000_GAL = "cost_per_1000_gal"
CONF_WEEKLY_BUDGET_GAL = "weekly_budget_gal"
CONF_WEEKLY_SUMMARY = "weekly_summary"
CONF_BASELINE_MINUTES = "baseline_minutes"
CONF_BASELINE_DAYS = "baseline_days"

MODE_AUTO = "auto"
MODE_NOTIFY_ONLY = "notify_only"
MODE_OFF = "off"
MODES = (MODE_AUTO, MODE_NOTIFY_ONLY, MODE_OFF)

SUBENTRY_ZONE = "zone"

# Kept so a stored v0.4 option still has a name. Migration discards it.
DEFAULT_DRY_RUN = False
# Inclusive freeze cutoff. Oklahoma State HLA-6610 says not to water below 40°F.
DEFAULT_FREEZE_SKIP_F = 40.0
# Practical recent-rain gate. Not a published hour or depth; both are overridable.
DEFAULT_RECENT_RAIN_HOURS = 12
DEFAULT_RECENT_RAIN_MM = 2.5
# Valve-on minutes for one zone on one night. Soak time does not count.
# The rest stays in the bucket. An optional hub total is off unless set.
DEFAULT_MAX_RUN_MIN = 60

DEFAULT_ELEVATION_M = 219.0
# Kept so a stored 0.7 option still has a name during migration.
DEFAULT_SUNRISE_BUFFER_MIN = 30
DEFAULT_PLAN_HOUR = 23
# Morning window. The plan is made the evening before; valves open at the start.
DEFAULT_START_TIME = "05:00:00"
DEFAULT_FINISH_TIME = "09:00:00"
DEFAULT_EARLIEST_START = "04:00:00"
# New hubs aim to finish at sunrise. An upgraded hub is migrated to off so
# it keeps the 0.10.1 fixed start until the user turns this on.
DEFAULT_DYNAMIC_START = True
DEFAULT_WIND_HEIGHT_M = 2.0
DEFAULT_EFFICIENCY = 1.0
DEFAULT_PRIORITY = 10
DEFAULT_ROUND_MINUTES = True
DEFAULT_ADJUSTMENT_PCT = 100.0
DEFAULT_MOISTURE_WEIGHT = 0.5
DEFAULT_FLOW_LOW_RATIO = 0.5
DEFAULT_FLOW_LEAK_RATIO = 1.5
DEFAULT_SPRINKLER_TYPE = "spray"
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

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

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
FLOW_SCOPE_WHOLE = "whole_home"
FLOW_SCOPE_IRRIGATION = "irrigation"
FLOW_SCOPES = (FLOW_SCOPE_WHOLE, FLOW_SCOPE_IRRIGATION)

SERVICE_CALCULATE_PLAN = "calculate_plan"
SERVICE_RESET_BUCKET = "reset_bucket"
SERVICE_SET_BUCKET = "set_bucket"
SERVICE_MARK_WATERED = "mark_watered"
SERVICE_SKIP_ZONE = "skip_zone"
SERVICE_PAUSE_ZONE = "pause_zone"
SERVICE_SET_ADJUSTMENT = "set_adjustment"
SERVICE_RUN_NOW = "run_now"
SERVICE_SIMULATE = "simulate"
SERVICE_STOP_ALL = "stop_all"
SERVICE_RESET_LEARNING = "reset_learning"
SERVICE_RESET_FLOW = "reset_flow_learning"
SERVICE_START_AUDIT = "start_audit"
SERVICE_SUBMIT_AUDIT = "submit_audit"

SERVICES = (
    SERVICE_CALCULATE_PLAN,
    SERVICE_RESET_BUCKET,
    SERVICE_SET_BUCKET,
    SERVICE_MARK_WATERED,
    SERVICE_SKIP_ZONE,
    SERVICE_PAUSE_ZONE,
    SERVICE_SET_ADJUSTMENT,
    SERVICE_RUN_NOW,
    SERVICE_SIMULATE,
    SERVICE_STOP_ALL,
    SERVICE_RESET_LEARNING,
    SERVICE_RESET_FLOW,
    SERVICE_START_AUDIT,
    SERVICE_SUBMIT_AUDIT,
)

FLOW_ACTION_NOTIFY = "notify"
FLOW_ACTION_STOP = "stop"
FLOW_ACTIONS = (FLOW_ACTION_NOTIFY, FLOW_ACTION_STOP)

EVENT_FLOW_ALERT = "smart_water_flow_alert"
EVENT_BUDGET_ALERT = "smart_water_budget_alert"
EVENT_WEEKLY_SUMMARY = "smart_water_weekly_summary"
EVENT_FREEZE_ALERT = "smart_water_freeze_alert"

PLATFORMS: list[str] = ["sensor", "switch", "number", "button"]

# FAO-56 ignores daily rain below about 0.2 × ET0 (Chapter 8).
RAIN_IGNORE_FRACTION_OF_ET0 = 0.2
