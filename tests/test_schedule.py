"""Allowed watering days and blackout windows."""

from __future__ import annotations

from datetime import datetime, timezone

from smart_water.schedule import (
    clip_blackout,
    day_allowed,
    migrate_options,
    morning_window,
    rules_for,
    weekday_name,
)


def test_allowed_days_keep_weekday_order_and_an_empty_list() -> None:
    rules = rules_for(("fri", "mon"), 8, 18)
    assert rules.allowed_weekdays == ("mon", "fri")
    assert rules.blackout_start == 8
    assert rules.source == "days"
    every = rules_for(None, 6, 20)
    assert every.allowed_weekdays is None
    assert every.blackout_start == 6
    empty = rules_for((), None, None)
    assert empty.allowed_weekdays == ()


def test_none_allows_every_day_and_an_empty_tuple_allows_none() -> None:
    friday = datetime(2026, 10, 16, 6, tzinfo=timezone.utc)
    thursday = datetime(2026, 10, 15, 6, tzinfo=timezone.utc)
    assert weekday_name(friday) == "fri"
    assert weekday_name(thursday) == "thu"
    odd = ("sun", "tue", "thu")
    assert day_allowed(friday, odd) is False
    assert day_allowed(thursday, odd) is True
    assert day_allowed(friday, None) is True
    assert day_allowed(friday, ()) is False


def test_retired_presets_migrate_to_day_sets() -> None:
    odd = migrate_options(
        {"schedule_preset": "waco_odd", "dry_run": False, "elevation_m": 219}
    )
    assert odd["allowed_weekdays"] == ["sun", "tue", "thu"]
    assert (odd["blackout_start_hour"], odd["blackout_end_hour"]) == (10, 19)
    assert "schedule_preset" not in odd
    assert "dry_run" not in odd
    assert odd["elevation_m"] == 219
    even = migrate_options({"schedule_preset": "waco_even"})
    assert even["allowed_weekdays"] == ["mon", "wed", "sat"]
    assert "fri" not in even["allowed_weekdays"]
    every = migrate_options({"schedule_preset": "none", "blackout_start_hour": 9})
    assert every["allowed_weekdays"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert every["blackout_start_hour"] == 9


def test_evening_plan_uses_the_next_morning_window() -> None:
    from zoneinfo import ZoneInfo

    chicago = ZoneInfo("America/Chicago")
    evening = datetime(2026, 10, 24, 23, 0, tzinfo=chicago)
    earliest, start, finish = morning_window(evening)
    assert earliest == datetime(2026, 10, 25, 4, 0, tzinfo=chicago)
    assert start == datetime(2026, 10, 25, 5, 0, tzinfo=chicago)
    assert finish == datetime(2026, 10, 25, 9, 0, tzinfo=chicago)
    before = datetime(2026, 10, 25, 3, 0, tzinfo=chicago)
    same = morning_window(before, "04:30", "05:15", "08:45")
    assert same[1] == datetime(2026, 10, 25, 5, 15, tzinfo=chicago)
    assert same[2] == datetime(2026, 10, 25, 8, 45, tzinfo=chicago)


def test_blackout_clip_morning_and_evening() -> None:
    midday = datetime(2026, 10, 16, 11, 45, tzinfo=timezone.utc)
    finish, earliest, note = clip_blackout(midday, None, 10, 19)
    assert finish == datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
    assert earliest == datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    assert note is not None and "10:00" in note

    evening = datetime(2026, 10, 16, 21, 30, tzinfo=timezone.utc)
    finish, earliest, note = clip_blackout(evening, None, 10, 19)
    assert finish == evening
    assert earliest == datetime(2026, 10, 16, 19, 0, tzinfo=timezone.utc)
    assert note is not None and "19:00" in note

    morning = datetime(2026, 10, 16, 7, 15, tzinfo=timezone.utc)
    finish, earliest, note = clip_blackout(morning, None, 10, 19)
    assert finish == morning
    assert earliest == datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
    assert note is None
