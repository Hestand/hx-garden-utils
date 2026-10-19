"""Next watering is projected past this week, onto an allowed morning."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from smart_water.week_plan import describe_outlook, split_outlook
from tests.test_planner import _zone
from tests.test_week_plan import _project

CHICAGO = ZoneInfo("America/Chicago")


def test_a_dry_zone_waits_for_the_next_allowed_monday() -> None:
    """Deficit 1 mm and 2 mm a day reaches 20 mm, then waits for Monday."""
    zone = _zone(
        name="Front",
        deficit_mm=1.0,
        raw_mm=20.0,
        etc_mm=2.0,
        taw_mm=200.0,
        min_interval_days=None,
        soak_override_min=0,
        max_cycle_override_min=30,
    )
    result = _project(zone, days=60, allowed_weekdays=("mon",))
    week, outlook = split_outlook(result, timezone="America/Chicago")
    assert len(week["days"]) == 7
    info = outlook["by_zone"]["front"]
    assert info["at"] == datetime(2026, 11, 9, 5, 0, tzinfo=CHICAGO)
    assert info["estimated"] is True
    assert outlook["summary"] == "Next watering ~Nov 9 (estimated)"


def test_a_dormant_zone_keeps_its_note_instead_of_a_blank_date() -> None:
    zone = _zone(
        name="Front",
        deficit_mm=80.0,
        raw_mm=10.0,
        dormancy="dormant",
        dormancy_detail="Dormant. Regular watering is off.",
        maintenance_due=False,
    )
    result = _project(zone, days=60)
    outlook = describe_outlook(
        result["days"], timezone="America/Chicago", firm_days=7, horizon=60
    )
    assert outlook["by_zone"]["front"]["at"] is None
    assert "Dormant" in str(outlook["summary"])


def test_zero_water_loss_does_not_invent_a_date() -> None:
    zone = _zone(
        name="Front",
        deficit_mm=1.0,
        raw_mm=20.0,
        etc_mm=2.0,
        taw_mm=200.0,
        min_interval_days=None,
    )
    result = _project(zone, days=60, et_factors=[0.0] * 60)
    outlook = describe_outlook(
        result["days"], timezone="America/Chicago", firm_days=7, horizon=60
    )
    assert outlook["by_zone"] == {}
    assert "60" in str(outlook["summary"])


def test_a_date_inside_the_week_is_not_labeled_estimated() -> None:
    zone = _zone(
        name="Front",
        deficit_mm=30.0,
        raw_mm=8.0,
        min_interval_days=None,
        soak_override_min=0,
        max_cycle_override_min=60,
    )
    result = _project(zone, days=60)
    outlook = describe_outlook(
        result["days"], timezone="America/Chicago", firm_days=7, horizon=60
    )
    assert outlook["summary"] == ""
    assert outlook["by_zone"]["front"]["estimated"] is False
    assert outlook["by_zone"]["front"]["at"] is not None
