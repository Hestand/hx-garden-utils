"""Morning clocks stay on the wall time across both daylight-saving changes.

America/Chicago, 2026: clocks spring forward on March 8 at 2:00 AM, and fall
back on November 1 at 2:00 AM. A fixed UTC−5 offset carried onto November 1
is 4:05 AM CST (10:05 UTC), which is the bug this guards against.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from smart_water.planner import build_plan
from smart_water.schedule import morning_window, shift_minutes, wall_clock
from smart_water.sensor import earliest_enabled_run
from smart_water.week_plan import describe_outlook
from tests.test_planner import _request, _zone
from tests.test_week_plan import _project

CHICAGO = ZoneInfo("America/Chicago")


def _due_zone():
    return _zone(
        name="Bed",
        deficit_mm=30.0,
        raw_mm=8.0,
        soak_override_min=0,
        max_cycle_override_min=20,
        min_interval_days=None,
    )


def test_fall_back_morning_stays_5am_and_9am_central() -> None:
    evening = datetime(2026, 10, 31, 23, 0, tzinfo=CHICAGO)
    earliest, start, finish = morning_window(evening)
    assert start.date().isoformat() == "2026-11-01"
    assert (earliest.hour, earliest.minute) == (4, 0)
    assert (start.hour, start.minute) == (5, 0)
    assert (finish.hour, finish.minute) == (9, 0)
    assert start.utcoffset() == timedelta(hours=-6)
    assert finish.utcoffset() == timedelta(hours=-6)
    assert start.astimezone(timezone.utc).isoformat() == "2026-11-01T11:00:00+00:00"
    assert finish.astimezone(timezone.utc).isoformat() == "2026-11-01T15:00:00+00:00"


def test_spring_forward_morning_stays_5am_and_9am_central() -> None:
    evening = datetime(2026, 3, 7, 23, 0, tzinfo=CHICAGO)
    earliest, start, finish = morning_window(evening)
    assert start.date().isoformat() == "2026-03-08"
    assert (earliest.hour, earliest.minute) == (4, 0)
    assert (start.hour, start.minute) == (5, 0)
    assert (finish.hour, finish.minute) == (9, 0)
    assert start.utcoffset() == timedelta(hours=-5)
    assert finish.utcoffset() == timedelta(hours=-5)
    assert start.astimezone(timezone.utc).isoformat() == "2026-03-08T10:00:00+00:00"
    assert finish.astimezone(timezone.utc).isoformat() == "2026-03-08T14:00:00+00:00"


def test_projection_keeps_local_start_on_both_transition_mornings() -> None:
    for evening, morning, offset_hours, utc_hour in (
        (datetime(2026, 10, 31, 23, 0, tzinfo=CHICAGO), "2026-11-01", -6, 11),
        (datetime(2026, 3, 7, 23, 0, tzinfo=CHICAGO), "2026-03-08", -5, 10),
    ):
        result = _project(_due_zone(), now=evening, days=3)
        assert result["window"].startswith("Start 05:00, finish by 09:00")
        first = result["days"][0]
        assert first["date"] == morning
        assert str(first["zones"][0]["starts"]).split(",")[0].strip() == "05:00"
        outlook = describe_outlook(
            result["days"], timezone="America/Chicago", firm_days=7, horizon=3
        )
        moment = outlook["by_zone"]["front"]["at"]
        assert moment.hour == 5 and moment.minute == 0
        assert moment.utcoffset() == timedelta(hours=offset_hours)
        utc = moment.astimezone(timezone.utc)
        assert utc.hour == utc_hour
        assert "~" not in str(outlook["summary"])
        assert "estimated" not in str(outlook["summary"]).lower()


def test_a_fixed_cdt_offset_does_not_stick_to_the_fall_back_morning() -> None:
    """The live sensor was 2026-11-01T10:05:00+00:00, which is 4:05 AM CST."""
    fixed = timezone(timedelta(hours=-5))
    now = datetime(2026, 10, 31, 23, 5, tzinfo=fixed)
    result = _project(_due_zone(), now=now, days=3)
    outlook = describe_outlook(
        result["days"], timezone="America/Chicago", firm_days=7, horizon=3
    )
    moment = outlook["by_zone"]["front"]["at"]
    assert moment.isoformat() == "2026-11-01T05:00:00-06:00"
    assert moment.astimezone(timezone.utc).isoformat() == "2026-11-01T11:00:00+00:00"
    stuck = datetime(2026, 11, 1, 5, 5, tzinfo=fixed)
    assert stuck.astimezone(timezone.utc).isoformat() == "2026-11-01T10:05:00+00:00"


def test_spring_window_includes_the_missing_hour() -> None:
    now = datetime(2026, 3, 8, 0, 30, tzinfo=CHICAGO)
    earliest, start, finish = morning_window(now, "01:00", "01:30", "04:00")
    assert (start.hour, start.minute) == (1, 30)
    assert start.utcoffset() == timedelta(hours=-6)
    assert (finish.hour, finish.minute) == (4, 0)
    assert finish.utcoffset() == timedelta(hours=-5)
    assert finish.astimezone(timezone.utc) - start.astimezone(timezone.utc) == timedelta(
        minutes=90
    )
    missing = wall_clock(start.date(), 2, 30, CHICAGO)
    assert (missing.hour, missing.minute) == (3, 30)
    assert missing.utcoffset() == timedelta(hours=-5)
    plan = build_plan(
        _request(
            _due_zone(),
            start_at=start,
            finish_by=finish,
            earliest_start=earliest,
        )
    )
    opened = plan.timeline[0].start.astimezone(CHICAGO)
    assert (opened.hour, opened.minute) == (1, 30)
    assert opened.utcoffset() == timedelta(hours=-6)
    later = shift_minutes(opened, 60).astimezone(CHICAGO)
    assert (later.hour, later.minute) == (3, 30)
    assert later.utcoffset() == timedelta(hours=-5)


def test_fall_back_window_includes_the_repeated_hour() -> None:
    now = datetime(2026, 11, 1, 0, 20, tzinfo=CHICAGO)
    earliest, start, finish = morning_window(now, "00:30", "01:00", "03:00")
    assert (earliest.hour, earliest.minute) == (0, 30)
    assert (start.hour, start.minute) == (1, 0)
    assert start.fold == 0
    assert start.utcoffset() == timedelta(hours=-5)
    assert (finish.hour, finish.minute) == (3, 0)
    assert finish.utcoffset() == timedelta(hours=-6)
    assert finish.astimezone(timezone.utc) - start.astimezone(timezone.utc) == timedelta(
        hours=3
    )
    plan = build_plan(
        _request(
            _due_zone(),
            start_at=start,
            finish_by=finish,
            earliest_start=earliest,
        )
    )
    opened = plan.timeline[0].start.astimezone(CHICAGO)
    assert (opened.hour, opened.minute) == (1, 0)
    assert opened.fold == 0
    assert opened.utcoffset() == timedelta(hours=-5)


def test_hub_next_watering_is_the_earliest_enabled_zone() -> None:
    disabled = SimpleNamespace(
        enabled=False,
        next_run=datetime(2026, 11, 1, 5, tzinfo=CHICAGO),
    )
    later = SimpleNamespace(
        enabled=True,
        next_run=datetime(2026, 11, 8, 5, tzinfo=CHICAGO),
    )
    sooner = SimpleNamespace(
        enabled=True,
        next_run=datetime(2026, 11, 2, 5, tzinfo=CHICAGO),
    )
    assert earliest_enabled_run([disabled, later, sooner]) == sooner.next_run
    assert earliest_enabled_run([disabled]) is None
