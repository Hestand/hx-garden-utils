"""Watering days and blackout windows, including the Waco preset."""

from __future__ import annotations

from datetime import datetime, timezone

from smart_water.schedule import clip_blackout, day_allowed, rules_for, weekday_name


def test_waco_presets_fix_days_and_the_daytime_blackout() -> None:
    odd = rules_for("waco_odd", ("mon",), 0, 1)
    assert odd.allowed_weekdays == ("sun", "tue", "thu")
    assert (odd.blackout_start, odd.blackout_end) == (10, 19)
    even = rules_for("waco_even", None, None, None)
    assert even.allowed_weekdays == ("mon", "wed", "sat")
    assert "fri" not in odd.allowed_weekdays
    assert "fri" not in even.allowed_weekdays


def test_custom_days_and_an_empty_list() -> None:
    custom = rules_for("custom", ("fri", "mon"), 8, 18)
    assert custom.allowed_weekdays == ("mon", "fri")
    assert custom.blackout_start == 8
    none = rules_for("none", ("mon",), 6, 20)
    assert none.allowed_weekdays is None
    assert none.blackout_start == 6
    empty = rules_for("custom", (), None, None)
    assert empty.allowed_weekdays is None


def test_friday_is_not_a_waco_day_and_thursday_is_odd() -> None:
    friday = datetime(2026, 10, 16, 6, tzinfo=timezone.utc)
    thursday = datetime(2026, 10, 15, 6, tzinfo=timezone.utc)
    assert weekday_name(friday) == "fri"
    assert weekday_name(thursday) == "thu"
    odd = rules_for("waco_odd", None, None, None).allowed_weekdays
    assert day_allowed(friday, odd) is False
    assert day_allowed(thursday, odd) is True
    assert day_allowed(friday, None) is True


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
