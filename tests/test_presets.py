"""Cited presets: every row has a source, and blank means the preset."""

from __future__ import annotations

import pytest

from sprinklecast.presets import (
    PLANTS,
    SOILS,
    SPRINKLERS,
    SUN,
    available_water_default,
    intake_default,
    plant_kc,
    preset_placeholders,
    resolved_efficiency,
    resolved_root_depth_in,
    resolved_slope_pct,
    sprinkler_efficiency,
    sprinkler_precip,
)
from sprinklecast.soil import crop_coefficient


def test_every_row_names_a_source() -> None:
    for key, soil in SOILS.items():
        assert soil.source.strip(), key
        assert soil.awc_low <= soil.awc <= soil.awc_high
    for key, plant in PLANTS.items():
        assert plant.source.strip(), key
        assert plant.kc_monthly is None or len(plant.kc_monthly) == 12
    for key, (factor, source) in SUN.items():
        assert source.strip(), key
        assert 0 < factor <= 1.4
    for key, sprinkler in SPRINKLERS.items():
        assert sprinkler.source.strip(), key
        assert 0 < sprinkler.efficiency <= 1


def test_soil_defaults_follow_the_cited_midpoints() -> None:
    assert available_water_default("loam") == pytest.approx(0.155)
    assert available_water_default("clay_loam") == pytest.approx(0.16)
    assert available_water_default("sand") == pytest.approx(0.08)
    # 5% stays in the 0–5% band. Clay loam there is 0.15 in/hr.
    assert intake_default("clay_loam", 5) == pytest.approx(0.15)
    assert intake_default("clay_loam", 6) == pytest.approx(0.10)
    assert intake_default("loam", 0) == pytest.approx(0.50)


def test_warm_season_uses_the_meyer_table() -> None:
    assert plant_kc("st_augustine", None) == pytest.approx(0.60)
    assert plant_kc("bermuda", None) == pytest.approx(0.60)
    assert plant_kc("buffalo", None) == pytest.approx(0.60)
    assert plant_kc("cool_season_turf", None) == pytest.approx(0.80)
    # July is month 7. Warm-season July in the UC ANR table is 0.71.
    assert plant_kc("zoysia", 7) == pytest.approx(0.71)
    assert plant_kc("warm_season_turf", 1) == pytest.approx(0.55)
    # Shade is the midpoint of the WUCOLS low range, 0.7, times July's 0.71.
    assert crop_coefficient("zoysia", "shade", month=7) == pytest.approx(0.71 * 0.7)
    assert crop_coefficient("zoysia", "part_sun", month=7) == pytest.approx(0.71 * 0.9)


def test_sprinkler_defaults() -> None:
    assert sprinkler_precip("spray") == pytest.approx(1.25)
    assert sprinkler_efficiency("spray") == pytest.approx(0.60)
    assert sprinkler_precip("rotor") == pytest.approx(0.50)
    assert sprinkler_efficiency("rotor") == pytest.approx(0.70)
    assert sprinkler_precip("mp_rotator") == pytest.approx(0.40)
    assert sprinkler_precip("drip") == pytest.approx(0.50)
    assert sprinkler_efficiency("drip") == pytest.approx(0.875)
    assert sprinkler_precip("bubbler") is None
    assert sprinkler_efficiency("bubbler") == pytest.approx(1.0)


def test_blank_uses_the_preset_and_a_stored_value_wins() -> None:
    blank = {"plant_type": "st_augustine", "sprinkler_type": "spray"}
    assert resolved_root_depth_in(blank) == pytest.approx(6)
    assert resolved_slope_pct(blank) == pytest.approx(0)
    assert resolved_efficiency(blank) == pytest.approx(0.60)
    stored = {
        "plant_type": "st_augustine",
        "sprinkler_type": "spray",
        "root_depth_in": 12,
        "slope_pct": 6,
        "efficiency": 1.0,
    }
    assert resolved_root_depth_in(stored) == pytest.approx(12)
    assert resolved_slope_pct(stored) == pytest.approx(6)
    assert resolved_efficiency(stored) == pytest.approx(1.0)


def test_placeholders_quote_the_preset_without_storing_it() -> None:
    text = preset_placeholders(
        plant_type="bermuda",
        soil_type="loam",
        sprinkler_type="spray",
        slope_pct=0,
        month=7,
        sun_exposure="full_sun",
    )
    assert text["root_depth"] == "6"
    assert text["awc"] == "0.155"
    assert text["precip"] == "1.25"
    assert text["efficiency"] == "0.6"
    assert text["kc"] == "0.71"
    bubbler = preset_placeholders(
        plant_type="tree",
        soil_type="clay",
        sprinkler_type="bubbler",
        slope_pct=0,
        month=7,
    )
    assert bubbler["precip"] == "none published"
    assert bubbler["efficiency"] == "1"
