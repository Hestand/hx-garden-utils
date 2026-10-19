"""Temperature dormancy thresholds by grass type."""

from __future__ import annotations

from sprinklecast.dormancy import classify, maintenance_due


def _history(*temps: float) -> list[dict[str, object]]:
    return [
        {"date": f"2026-01-{day:02d}", "mean_f": temp}
        for day, temp in enumerate(temps, start=1)
    ]


def test_warm_season_and_st_augustine_use_different_lines() -> None:
    assert classify("bermuda", _history(70, 70, 70)).status == "active"
    assert classify("bermuda", _history(54, 54, 54)).status == "slow"
    assert classify("bermuda", _history(49, 49, 49)).status == "dormant"
    augustine = classify("st_augustine", _history(56, 56, 56))
    assert augustine.status == "slow"
    assert classify("st_augustine", _history(54, 54, 54)).status == "dormant"
    assert classify("bermuda", _history(60, 60)).status == "active"
    assert classify("shrub", _history(40, 40, 40)).status == "active"


def test_cool_season_slows_in_heat_and_maintenance_is_optional() -> None:
    assert classify("cool_season_turf", _history(81, 82, 83)).status == "slow"
    assert classify("cool_season_turf", _history(70, 70, 70)).status == "active"
    assert maintenance_due(
        enabled=False,
        status="dormant",
        days_since=30,
        deficit_mm=20,
        raw_mm=12,
    ) is False
    assert maintenance_due(
        enabled=True,
        status="dormant",
        days_since=21,
        deficit_mm=20,
        raw_mm=12,
    ) is True
    assert maintenance_due(
        enabled=True,
        status="dormant",
        days_since=10,
        deficit_mm=20,
        raw_mm=12,
    ) is False
