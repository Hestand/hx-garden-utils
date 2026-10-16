"""Hourly forecast wind moves the dawn deadline earlier, not past the window."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from smart_water.timing import calm_finish

TZ = ZoneInfo("America/Chicago")


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 14, hour, minute, tzinfo=TZ)


def test_dawn_hour_of_wind_finishes_at_the_start_of_that_hour() -> None:
    finish, note = calm_finish(
        _at(6, 30),
        _at(4),
        ((_at(5), 8.0), (_at(6), 14.0)),
        10,
    )
    assert finish == _at(6)
    assert note is not None
    assert "06:00" in note


def test_a_windy_stretch_walks_back_to_the_last_calm_hour() -> None:
    finish, note = calm_finish(
        _at(6, 30),
        _at(4),
        ((_at(4), 5.0), (_at(5), 14.0), (_at(6), 14.0)),
        10,
    )
    assert finish == _at(5)
    assert note is not None


def test_earliest_start_stops_the_retreat() -> None:
    finish, note = calm_finish(
        _at(6, 30),
        _at(5),
        ((_at(4), 20.0), (_at(5), 14.0), (_at(6), 14.0)),
        10,
    )
    assert finish == _at(5)
    assert note is not None
    assert "earliest" in note


def test_missing_forecast_leaves_dawn_alone() -> None:
    finish, note = calm_finish(_at(6, 30), _at(4), (), 10)
    assert finish == _at(6, 30)
    assert note is None
