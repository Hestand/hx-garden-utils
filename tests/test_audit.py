"""Catch-cup math: rate, low-quarter uniformity, and scheduling efficiency."""

from __future__ import annotations

import pytest

from smart_water.audit import audit_result, du_lq


def test_uniformity_uses_the_lowest_quarter() -> None:
    # 16 cups. Lowest four average 0.2, overall average 0.4, DU_lq = 0.5.
    depths = [0.2] * 4 + [0.4] * 8 + [0.6] * 4
    assert du_lq(depths) == pytest.approx(0.5)


def test_inches_over_fifteen_minutes_become_a_rate() -> None:
    result = audit_result([0.25] * 8, minutes=15, unit="in", cup_diameter_in=None)
    assert result.precipitation_rate_in_hr == pytest.approx(1.0)
    assert result.du_lq == pytest.approx(1.0)
    assert result.scheduling_efficiency == pytest.approx(1.0)


def test_millilitres_use_the_cup_diameter() -> None:
    # A 4 inch cup has area 12.566 sq in. 100 mL is about 6.102 cubic inches,
    # so the depth is about 0.486 in. Over 30 minutes that is about 0.97 in/hr.
    result = audit_result(
        [100.0] * 4,
        minutes=30,
        unit="ml",
        cup_diameter_in=4,
    )
    assert result.average_in == pytest.approx(0.486, abs=0.002)
    assert result.precipitation_rate_in_hr == pytest.approx(0.971, abs=0.01)


def test_empty_cups_count_and_a_short_list_is_rejected() -> None:
    with pytest.raises(ValueError):
        audit_result([0.2, 0.2, 0.2], minutes=10, unit="in", cup_diameter_in=None)
    # A dry low quarter cannot become an efficiency the planner can divide by.
    with pytest.raises(ValueError):
        audit_result([0.0, 0.0, 0.4, 0.4], minutes=15, unit="in", cup_diameter_in=None)
