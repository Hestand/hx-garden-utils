"""Watering calendar events cover planned bursts and completed runs."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from sprinklecast.calendar import watering_events

TZ = ZoneInfo("America/Chicago")


def test_events_cover_a_burst_and_a_completed_run() -> None:
    start = datetime(2026, 10, 18, 5, 0, tzinfo=TZ)
    end = datetime(2026, 10, 18, 5, 5, tzinfo=TZ)
    events = watering_events(
        days=[
            {
                "estimated": True,
                "zones": [
                    {
                        "name": "Front Yard",
                        "zone_id": "front",
                        "scheduled": True,
                        "bursts": [
                            {
                                "cycle": 1,
                                "of": 2,
                                "minutes": 5,
                                "start_at": start.isoformat(),
                                "end_at": end.isoformat(),
                                "inches": 0.04,
                            }
                        ],
                    }
                ],
            }
        ],
        runs=[
            {
                "name": "Bed",
                "zone_id": "bed",
                "at": "2026-10-17T05:00:00-05:00",
                "minutes": 6,
                "net_mm": 2.54,
                "result": "ok",
            },
            {
                "name": "Bed",
                "zone_id": "bed",
                "at": "2026-10-16T05:00:00-05:00",
                "minutes": 1,
                "net_mm": 0,
                "result": "stopped",
            },
        ],
        start=datetime(2026, 10, 1, tzinfo=TZ),
        end=datetime(2026, 11, 1, tzinfo=TZ),
        uid_prefix="cal",
    )
    assert [event.summary for event in events] == ["Bed", "Front Yard"]
    front = events[1]
    assert front.start == start
    assert front.end == end
    assert "5 min" in (front.description or "")
    assert "0.04 in" in (front.description or "")
    assert "cycle 1 of 2" in (front.description or "")
    assert "Estimated" in (front.description or "")
    assert "Completed run" in (events[0].description or "")
    missed = watering_events(
        days=[],
        runs=[],
        start=datetime(2026, 12, 1, tzinfo=TZ),
        end=datetime(2026, 12, 2, tzinfo=TZ),
        uid_prefix="cal",
    )
    assert missed == []
    outside = watering_events(
        days=[
            {
                "estimated": False,
                "zones": [
                    {
                        "name": "Front Yard",
                        "zone_id": "front",
                        "scheduled": True,
                        "bursts": [
                            {
                                "cycle": 1,
                                "of": 1,
                                "minutes": 5,
                                "start_at": start.isoformat(),
                                "end_at": end.isoformat(),
                                "inches": 0.04,
                            }
                        ],
                    }
                ],
            }
        ],
        runs=[],
        start=datetime(2026, 12, 1, tzinfo=TZ),
        end=datetime(2026, 12, 2, tzinfo=TZ),
        uid_prefix="cal",
    )
    assert outside == []
    firm = outside or watering_events(
        days=[
            {
                "zones": [
                    {
                        "name": "Front Yard",
                        "zone_id": "front",
                        "scheduled": True,
                        "bursts": [
                            {
                                "cycle": 1,
                                "of": 1,
                                "minutes": 5,
                                "start_at": start.isoformat(),
                                "end_at": end.isoformat(),
                                "inches": 0.04,
                            }
                        ],
                    }
                ],
            }
        ],
        runs=[],
        start=datetime(2026, 10, 1, tzinfo=TZ),
        end=datetime(2026, 11, 1, tzinfo=TZ),
        uid_prefix="cal",
    )
    assert "Estimated" not in (firm[0].description or "")
