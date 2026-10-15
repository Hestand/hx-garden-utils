"""Skip reasons shared by the nightly plan and the live executor.

The first match wins. Manual run-now uses only the safety checks (rain,
freeze, wind, and moisture). The planner also applies days, the window,
the minimum interval, and dormancy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkipInputs:
    """Facts for one zone at one decision."""

    enabled: bool = True
    skipped_until: str | None = None
    finish_day: str = ""
    hub_rain_wet: bool = False
    rain_sensor_wet: bool = False
    currently_raining: bool = False
    recent_rain_mm: float = 0.0
    recent_rain_skip_mm: float | None = None
    recent_rain_hours: int = 12
    temp_f: float | None = None
    forecast_low_f: float | None = None
    freeze_f: float | None = None
    wind_mph: float | None = None
    wind_limit_mph: float | None = None
    moisture_full: float | None = None
    moisture_skip_full: float | None = None
    forecast_skip: bool = False
    forecast_mm: float = 0.0
    allowed_day: bool = True
    ignores_schedule: bool = False
    weekday: str = ""
    window_closed: bool = False
    due: bool = False
    due_reason: str = ""
    days_since_water: int | None = None
    min_interval_days: int | None = None
    dormancy: str = "active"
    dormancy_detail: str = ""
    maintenance_due: bool = False
    include_schedule: bool = True


def safety_reason(inputs: SkipInputs) -> str | None:
    """Rain, freeze, wind, and moisture. None when watering is still allowed."""
    if inputs.hub_rain_wet or inputs.rain_sensor_wet:
        return "Skipped because the rain sensor is wet."
    if inputs.currently_raining:
        return "Skipped because it is raining."
    if (
        inputs.recent_rain_skip_mm is not None
        and inputs.recent_rain_mm >= inputs.recent_rain_skip_mm
    ):
        return (
            f"Skipped because {inputs.recent_rain_mm:.1f} mm of rain fell "
            f"in the last {inputs.recent_rain_hours} hours."
        )
    readings = [value for value in (inputs.temp_f, inputs.forecast_low_f) if value is not None]
    if inputs.freeze_f is not None and readings and min(readings) <= inputs.freeze_f:
        coldest = min(readings)
        return (
            f"Skipped because the temperature is {coldest:.0f}°F "
            f"(limit {inputs.freeze_f:.0f}°F)."
        )
    if (
        inputs.wind_limit_mph is not None
        and inputs.wind_mph is not None
        and inputs.wind_mph >= inputs.wind_limit_mph
    ):
        return (
            f"Skipped because the wind is {inputs.wind_mph:.0f} mph "
            f"(limit {inputs.wind_limit_mph:.0f} mph)."
        )
    if (
        inputs.moisture_full is not None
        and inputs.moisture_skip_full is not None
        and inputs.moisture_full > inputs.moisture_skip_full
    ):
        return (
            "Skipped because soil moisture is above the threshold "
            f"({inputs.moisture_full:.0%} full)."
        )
    return None


def skip_reason(inputs: SkipInputs) -> str | None:
    """First planner skip, or None when the zone should be scheduled.

    "Not due" is a reason. A dormant zone with maintenance due is not skipped
    here; the planner caps that run at the maintenance depth.
    """
    if not inputs.enabled:
        return "Zone is disabled."
    if inputs.skipped_until is not None and inputs.skipped_until >= inputs.finish_day:
        return f"Skipped until {inputs.skipped_until}."
    safety = safety_reason(inputs)
    if safety:
        return safety
    if inputs.forecast_skip:
        return f"Skipped because forecast rain is {inputs.forecast_mm:.1f} mm."
    if inputs.include_schedule:
        if not inputs.ignores_schedule and not inputs.allowed_day:
            day = inputs.weekday or "that day"
            return f"Not an allowed watering day ({day})."
        if inputs.window_closed and inputs.due:
            return f"{inputs.due_reason} The watering window is closed."
        if (
            inputs.due
            and inputs.min_interval_days
            and inputs.days_since_water is not None
            and inputs.days_since_water < inputs.min_interval_days
        ):
            return (
                f"Minimum {inputs.min_interval_days} days between waterings "
                f"({inputs.days_since_water} since the last run)."
            )
        if inputs.dormancy == "dormant" and not inputs.maintenance_due:
            return inputs.dormancy_detail or "Dormant. Regular watering is off."
    if not inputs.due:
        return inputs.due_reason
    return None
