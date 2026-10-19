"""Skip reasons: rain, freeze, wind, moisture, interval, and dormancy."""

from __future__ import annotations

from sprinklecast.skips import SkipInputs, safety_reason, skip_reason


def _inputs(**overrides: object) -> SkipInputs:
    base = dict(due=True, due_reason="Due.", finish_day="2026-07-14", allowed_day=True)
    base.update(overrides)
    return SkipInputs(**base)  # type: ignore[arg-type]


def test_freeze_wind_rain_and_moisture_skip_before_the_schedule() -> None:
    assert "rain sensor" in safety_reason(_inputs(hub_rain_wet=True))
    assert "raining" in safety_reason(_inputs(currently_raining=True))
    assert (
        safety_reason(
            _inputs(recent_rain_mm=20, recent_rain_skip_mm=2.5, recent_rain_hours=12)
        )
        is None
    )
    assert "40°F" in safety_reason(_inputs(temp_f=39, freeze_f=40))
    assert safety_reason(_inputs(temp_f=41, forecast_low_f=45, freeze_f=40)) is None
    assert "wind" in safety_reason(_inputs(wind_mph=10, wind_limit_mph=10))
    assert safety_reason(_inputs(wind_mph=9, wind_limit_mph=10)) is None
    assert safety_reason(_inputs(wind_mph=20, wind_limit_mph=None)) is None
    assert "moisture" in safety_reason(_inputs(moisture_full=0.8, moisture_skip_full=0.5))


def test_interval_and_dormancy_only_apply_to_the_plan() -> None:
    waited = skip_reason(_inputs(days_since_water=1, min_interval_days=3))
    assert waited is not None and "Minimum 3 days" in waited
    assert skip_reason(_inputs(days_since_water=None, min_interval_days=3)) is None
    dormant = skip_reason(_inputs(dormancy="dormant", dormancy_detail="Dormant."))
    assert dormant == "Dormant."
    assert (
        skip_reason(
            _inputs(dormancy="dormant", maintenance_due=True, dormancy_detail="Dormant.")
        )
        is None
    )
    manual = skip_reason(
        _inputs(
            include_schedule=False,
            days_since_water=0,
            min_interval_days=3,
            dormancy="dormant",
        )
    )
    assert manual is None
