"""Daily, weekly, and monthly gallons, plus a fixed-timer comparison."""

from __future__ import annotations

from datetime import date

import pytest

from sprinklecast.usage import (
    add_use,
    baseline_week_gallons,
    cost_of,
    period_gallons,
    saved_gallons,
)


def test_week_sum_baseline_savings_and_cost() -> None:
    days = add_use({}, "2026-07-13", 10)
    days = add_use(days, "2026-07-15", 5)
    today = date(2026, 7, 15)
    assert period_gallons(days, today, span="day") == 5
    assert period_gallons(days, today, span="week") == 15
    assert period_gallons(days, today, span="month") == 15
    baseline = baseline_week_gallons(
        minutes=15,
        days_per_week=3,
        precipitation_rate_in_hr=1.25,
        area_sqft=1000,
        flow_gpm=None,
    )
    assert baseline == pytest.approx(584.062, abs=0.001)
    assert saved_gallons(baseline, 15) == pytest.approx(569.062, abs=0.001)
    assert cost_of(2000, 4.5) == 9.0
    assert cost_of(2000, None) is None


def test_learned_gpm_fills_gallons_when_area_is_missing() -> None:
    assert (
        baseline_week_gallons(
            minutes=15,
            days_per_week=3,
            precipitation_rate_in_hr=None,
            area_sqft=None,
            flow_gpm=4.0,
        )
        == pytest.approx(180.0)
    )
