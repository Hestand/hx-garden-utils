"""Soil-moisture correction and flow classification. Neither module actuates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from smart_water.flow import classify_flow, expected_gallons, note_flow
from smart_water.moisture import apply_moisture, deficit_from_reading


def test_relative_moisture_and_a_fraction() -> None:
    assert deficit_from_reading(
        reading=50, kind="relative", taw_mm=40, zr_m=0.15, field_capacity_vwc=None
    ) == pytest.approx(20)
    assert deficit_from_reading(
        reading=0.25, kind="relative", taw_mm=40, zr_m=0.15, field_capacity_vwc=None
    ) == pytest.approx(30)


def test_volumetric_moisture_uses_field_capacity() -> None:
    # θFC 0.30, θ 0.20, Zr 0.1524 m → 15.24 mm.
    deficit = deficit_from_reading(
        reading=0.20,
        kind="vwc",
        taw_mm=40,
        zr_m=0.1524,
        field_capacity_vwc=0.30,
    )
    assert deficit == pytest.approx(15.24)
    percent = deficit_from_reading(
        reading=20,
        kind="vwc",
        taw_mm=40,
        zr_m=0.1524,
        field_capacity_vwc=30,
    )
    assert percent == pytest.approx(15.24)


def test_correct_blends_and_override_replaces() -> None:
    assert apply_moisture(10, 20, mode="correct", weight=0.5) == pytest.approx(15)
    assert apply_moisture(10, 20, mode="override", weight=0.5) == pytest.approx(20)
    assert apply_moisture(10, 20, mode="off", weight=1) == pytest.approx(10)


def test_expected_gallons_from_rate_and_from_gpm() -> None:
    # 60 min at 1 in/hr over 100 ft².
    assert expected_gallons(
        runtime_min=60,
        precipitation_rate_in_hr=1.0,
        area_sqft=100,
        flow_gpm=None,
    ) == pytest.approx(62.3)
    assert expected_gallons(
        runtime_min=10,
        precipitation_rate_in_hr=None,
        area_sqft=None,
        flow_gpm=2.0,
    ) == pytest.approx(20)


def test_flow_total_and_classification() -> None:
    state: dict[str, object] = {}
    start = datetime(2026, 10, 15, 6, tzinfo=timezone.utc)
    note_flow(state, kind="total", gallons=10, at=start, today="2026-10-15")
    note_flow(
        state,
        kind="total",
        gallons=12.5,
        at=start + timedelta(minutes=20),
        today="2026-10-15",
    )
    assert state["flow_delivered_gal"] == pytest.approx(2.5)
    assert (
        classify_flow(
            expected_gal=10,
            delivered_gal=2.5,
            scheduled=True,
            run_finished=True,
            low_ratio=0.5,
            leak_ratio=1.5,
        )
        == "low_flow"
    )
    assert (
        classify_flow(
            expected_gal=10,
            delivered_gal=20,
            scheduled=True,
            run_finished=False,
            low_ratio=0.5,
            leak_ratio=1.5,
        )
        == "leak"
    )
    assert (
        classify_flow(
            expected_gal=10,
            delivered_gal=1,
            scheduled=True,
            run_finished=False,
            low_ratio=0.5,
            leak_ratio=1.5,
        )
        == "pending"
    )
    assert (
        classify_flow(
            expected_gal=0,
            delivered_gal=2,
            scheduled=False,
            run_finished=True,
            low_ratio=0.5,
            leak_ratio=1.5,
        )
        == "leak"
    )
    assert (
        classify_flow(
            expected_gal=10,
            delivered_gal=10,
            scheduled=False,
            run_finished=True,
            low_ratio=0.5,
            leak_ratio=1.5,
        )
        == "ok"
    )
