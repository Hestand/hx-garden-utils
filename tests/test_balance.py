"""FAO-56 bucket, TAW/RAW, and the rain threshold."""

from __future__ import annotations

import pytest

from sprinklecast.balance import (
    adjusted_depletion_fraction,
    apply_daily_balance,
    days_to_balance,
    rewind_hand_set,
    root_zone,
    should_apply_balance,
    total_available_water_mm,
    zone_is_due,
)


def test_taw_uses_awc_midpoint_and_root_depth() -> None:
    # Sand 0.05–0.11, midpoint 0.08. Six inches is 0.1524 m.
    # TAW = 1000 × 0.08 × 0.1524 = 12.192 mm (Eq. 82).
    zone = root_zone(
        soil_type="sand",
        plant_type="cool_season_turf",
        sun_exposure="full_sun",
        root_depth_in=6,
        p_table=0.40,
        et0_mm=5.0,
    )
    assert zone.awc == pytest.approx(0.08)
    assert zone.taw_mm == pytest.approx(12.192, abs=0.001)
    assert total_available_water_mm(0.08, 6) == pytest.approx(12.192, abs=0.001)
    # ETc = 0.8 × 5 = 4. p = 0.40 + 0.04 × (5 − 4) = 0.44.
    assert zone.kc == pytest.approx(0.8)
    assert zone.etc_mm == pytest.approx(4.0)
    assert zone.p == pytest.approx(0.44)
    assert zone.raw_mm == pytest.approx(0.44 * 12.192, abs=0.001)


def test_depletion_fraction_is_clamped() -> None:
    # FAO limits the adjusted p to 0.1–0.8.
    assert adjusted_depletion_fraction(0.70, 0.0) == pytest.approx(0.8)
    assert adjusted_depletion_fraction(0.30, 12.0) == pytest.approx(0.1)
    assert adjusted_depletion_fraction(0.40, None) == pytest.approx(0.40)


def test_warm_season_turf_kc_is_0_6() -> None:
    zone = root_zone(
        soil_type="loam",
        plant_type="warm_season_turf",
        sun_exposure="full_sun",
        root_depth_in=6,
        p_table=None,
        et0_mm=5.0,
    )
    # Loam midpoint of FAO-56 Table 19 (0.13–0.18) is 0.155.
    # TAW = 1000 × 0.155 × 0.1524 = 23.622 mm.
    assert zone.kc == pytest.approx(0.6)
    assert zone.awc == pytest.approx(0.155)
    assert zone.taw_mm == pytest.approx(23.622, abs=0.001)
    # Table p 0.50, ETc 3.0 → p = 0.50 + 0.04 × (5 − 3) = 0.58.
    assert zone.p == pytest.approx(0.58)
    assert zone.raw_mm == pytest.approx(0.58 * 23.622, abs=0.001)


def test_kc_override_replaces_sun_factor() -> None:
    zone = root_zone(
        soil_type="loam",
        plant_type="warm_season_turf",
        sun_exposure="shade",
        root_depth_in=6,
        p_table=0.5,
        kc_override=0.7,
        et0_mm=10,
    )
    assert zone.kc == pytest.approx(0.7)
    assert zone.etc_mm == pytest.approx(7.0)


def test_daily_balance_adds_et_and_ignores_small_rain() -> None:
    # Rain below 0.2 × ET0 is ignored. 0.9 < 0.2 × 5.
    update = apply_daily_balance(
        10.0, 40.0, etc_mm=3.0, precip_mm=0.9, et0_mm=5.0
    )
    assert update.rain_ignored is True
    assert update.effective_precip_mm == 0
    assert update.deficit_mm == pytest.approx(13.0)
    assert update.deep_percolation_mm == 0


def test_daily_balance_deep_percolation_and_runoff() -> None:
    # Dr 2 − (8 − 3) + 1 = −2 → deficit 0, DP 2.
    update = apply_daily_balance(
        2.0, 40.0, etc_mm=1.0, precip_mm=8.0, et0_mm=5.0, runoff_mm=3.0
    )
    assert update.rain_ignored is False
    assert update.effective_precip_mm == pytest.approx(5.0)
    assert update.deficit_mm == 0
    assert update.deep_percolation_mm == pytest.approx(2.0)


def test_deficit_cannot_exceed_taw() -> None:
    update = apply_daily_balance(38.0, 40.0, etc_mm=5.0, precip_mm=0.0, et0_mm=5.0)
    assert update.deficit_mm == pytest.approx(40.0)


def test_zone_is_due_at_raw_and_on_projection() -> None:
    due, reason = zone_is_due(14.2, 14.1, 24.0, 3.0)
    assert due is True
    assert "has reached the watering point" in reason
    projected, projected_reason = zone_is_due(10.0, 12.0, 24.0, 3.0)
    assert projected is True
    assert "would reach" in projected_reason
    below, below_reason = zone_is_due(2.0, 12.0, 24.0, 3.0)
    assert below is False
    assert "Not dry enough" in below_reason


def test_balance_is_applied_once_per_date() -> None:
    assert should_apply_balance(None, "2026-10-15", 10, 23, force=False) is False
    assert should_apply_balance(None, "2026-10-15", 23, 23, force=False) is True
    assert should_apply_balance("2026-10-15", "2026-10-15", 23, 23, force=True) is False
    assert should_apply_balance(None, "2026-10-15", 10, 23, force=True) is True


def test_days_to_balance_does_not_backfill_a_new_bucket() -> None:
    assert days_to_balance(None, "2026-10-19", 15, 23, force=False) == []
    assert days_to_balance(None, "2026-10-19", 23, 23, force=False) == ["2026-10-19"]
    assert days_to_balance(
        None,
        "2026-10-20",
        8,
        23,
        force=False,
        finished_et0_days={"2026-10-19"},
    ) == ["2026-10-19"]
    assert days_to_balance("2026-10-19", "2026-10-20", 8, 23, force=False) == []
    assert days_to_balance("2026-10-17", "2026-10-19", 8, 23, force=False) == [
        "2026-10-18"
    ]
    assert days_to_balance("2026-10-19", "2026-10-19", 23, 23, force=False) == []
    assert days_to_balance("2026-10-18", "2026-10-19", 10, 23, force=True) == [
        "2026-10-19"
    ]


def test_days_to_balance_caps_a_long_gap() -> None:
    days = days_to_balance("2026-09-01", "2026-10-20", 8, 23, force=False)
    assert days[0] == "2026-10-06"
    assert days[-1] == "2026-10-19"
    assert len(days) == 14


def test_rewind_hand_set_steps_back_once() -> None:
    state = {
        "balance_date": "2026-10-19",
        "bucket_history": [{"date": "2026-10-19", "full_pct": 75, "set": True}],
    }
    rewind_hand_set(state)
    assert state["balance_date"] == "2026-10-18"
    assert state["balance_rewound"] is True
    state["balance_date"] = "2026-10-19"
    rewind_hand_set(state)
    assert state["balance_date"] == "2026-10-19"

    unmarked = {"balance_date": "2026-10-19", "bucket_history": [{"date": "2026-10-19"}]}
    rewind_hand_set(unmarked)
    assert unmarked["balance_date"] == "2026-10-19"
    assert unmarked["balance_rewound"] is True
