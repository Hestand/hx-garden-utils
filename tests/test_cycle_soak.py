"""NRCS intake table and the design-doc 4 minute cycle."""

from __future__ import annotations

import pytest

from smart_water.cycle_soak import (
    max_cycle_minutes,
    plan_cycles,
    precipitation_rate_in_per_hr,
    resolve_precipitation_rate,
    split_runtime,
)
from smart_water.soil import intake_rate_in_per_hr, slope_band


@pytest.mark.parametrize(
    ("soil", "slope", "expected"),
    [
        ("sand", 0, 2.0),
        ("sand", 5, 2.0),
        ("sand", 5.1, 1.5),
        ("sandy_loam", 6, 0.80),
        ("sandy_loam", 8, 0.80),
        ("loam", 9, 0.30),
        ("silt_loam", 12, 0.30),
        ("silt_loam_compact", 0, 0.30),
        ("clay_loam", 6, 0.10),
        ("clay_loam", 8, 0.10),
        ("clay", 13, 0.06),
        ("clay", 20, 0.06),
    ],
)
def test_nrcs_intake_table(soil: str, slope: float, expected: float) -> None:
    assert intake_rate_in_per_hr(soil, slope) == pytest.approx(expected)


def test_slope_band_edges() -> None:
    assert [slope_band(value) for value in (0, 5, 5.01, 8, 8.01, 12, 12.01)] == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
    ]


def test_design_doc_clay_loam_cycle_is_four_minutes() -> None:
    # Sprays at 1.5 in/hr on clay loam, 5–8% slope, intake 0.10 in/hr.
    # 60 × 0.10 / 1.5 = 4 minutes.
    assert intake_rate_in_per_hr("clay_loam", 6) == pytest.approx(0.10)
    assert max_cycle_minutes(0.10, 1.5) == 4
    plan = plan_cycles(
        net_mm=20.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soil_type="clay_loam",
        slope_pct=6,
    )
    assert plan.max_cycle_min == 4
    assert plan.soak_min == 60
    assert plan.total_runtime_min == 31
    assert sum(plan.cycles_min) == 31
    assert all(minutes <= 4 for minutes in plan.cycles_min)
    assert all(isinstance(minutes, int) for minutes in plan.cycles_min)


def test_sand_uses_the_shorter_soak() -> None:
    plan = plan_cycles(
        net_mm=5.0,
        precipitation_rate_in_hr=0.5,
        efficiency=1.0,
        soil_type="sand",
        slope_pct=0,
    )
    # 5 mm = 0.197 in. At 0.5 in/hr that is 23.6 minutes, rounded to 24.
    # Intake is 2.0 in/hr, so the 240 minute maximum is one cycle.
    assert plan.soak_min == 30
    assert plan.max_cycle_min == 240
    assert plan.cycles_min == (24,)


def test_pooling_override_replaces_the_table() -> None:
    plan = plan_cycles(
        net_mm=20.0,
        precipitation_rate_in_hr=1.5,
        efficiency=1.0,
        soil_type="clay_loam",
        slope_pct=6,
        max_cycle_override_min=6,
        soak_override_min=45,
    )
    assert plan.max_cycle_min == 6
    assert plan.soak_min == 45
    assert plan.note is not None


def test_precipitation_rate_prefers_the_entered_value() -> None:
    # 96.25 × 5 GPM / 1000 ft².
    assert precipitation_rate_in_per_hr(5, 1000) == pytest.approx(0.48125)
    assert resolve_precipitation_rate(1.5, 5, 1000) == pytest.approx(1.5)
    assert resolve_precipitation_rate(None, 5, 1000) == pytest.approx(0.48125)


def test_split_runtime_sums_to_the_total() -> None:
    assert split_runtime(10, 4) == (4, 3, 3)
    assert split_runtime(4, 4) == (4,)
    assert split_runtime(0, 4) == ()


def test_efficiency_increases_runtime_without_assuming_a_default_du() -> None:
    full = plan_cycles(
        net_mm=25.4,
        precipitation_rate_in_hr=1.0,
        efficiency=1.0,
        soil_type="sand",
        slope_pct=0,
    )
    # 1.00 in net at 1 in/hr is 60 minutes. Half efficiency doubles it.
    assert full.total_runtime_min == 60
    doubled = plan_cycles(
        net_mm=25.4,
        precipitation_rate_in_hr=1.0,
        efficiency=0.5,
        soil_type="sand",
        slope_pct=0,
    )
    assert doubled.total_runtime_min == 120
