"""Shift the finish earlier when the hourly forecast is too windy.

The run stays inside the morning window. If the hour at the finish time is
forecast at or above a zone's wind cutoff, the finish moves back to the
start of that windy stretch, and never earlier than the earliest start.
"""

from __future__ import annotations

from datetime import datetime, timedelta


def calm_finish(
    finish_by: datetime,
    earliest: datetime | None,
    hourly: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]],
    limit_mph: float | None,
) -> tuple[datetime, str | None]:
    """Return a finish time that is not inside a forecast-windy hour.

    ``hourly`` is ``(timestamp, wind_mph)`` pairs. A missing forecast leaves
    the finish alone. When every hour back to the earliest start is windy,
    the finish stays at that earliest start.
    """
    if limit_mph is None or not hourly or finish_by.tzinfo is None:
        return finish_by, None
    points = _points(hourly, finish_by)
    if not points:
        return finish_by, None
    if not _windy(finish_by - timedelta(minutes=1), points, limit_mph):
        return finish_by, None
    shifted = finish_by
    probe = finish_by
    for _step in range(18):
        if not _windy(probe - timedelta(minutes=1), points, limit_mph):
            break
        hour_start = probe.replace(minute=0, second=0, microsecond=0)
        if hour_start >= probe:
            hour_start = hour_start - timedelta(hours=1)
        if earliest is not None and hour_start <= earliest:
            return earliest, (
                f"Forecast wind stays at or above {limit_mph:.0f} mph through "
                "the allowed window, so the run finishes at the earliest start."
            )
        shifted = hour_start
        probe = hour_start
    if shifted == finish_by:
        return finish_by, None
    return shifted, (
        f"Forecast wind at or above {limit_mph:.0f} mph, so the run "
        f"finishes at {shifted.strftime('%H:%M')} instead of {finish_by.strftime('%H:%M')}."
    )


def strictest_limit(limits: list[float | None]) -> float | None:
    """The lowest overhead wind cutoff among the zones that will run."""
    values = [limit for limit in limits if limit is not None]
    if not values:
        return None
    return min(values)


def _points(
    hourly: tuple[tuple[datetime, float], ...] | list[tuple[datetime, float]],
    finish_by: datetime,
) -> list[tuple[datetime, float]]:
    tz = finish_by.tzinfo
    points: list[tuple[datetime, float]] = []
    for stamp, wind in hourly:
        if stamp.tzinfo is None:
            local = stamp.replace(tzinfo=tz)
        else:
            local = stamp.astimezone(tz)
        points.append((local, float(wind)))
    points.sort(key=lambda item: item[0])
    return points


def _windy(
    moment: datetime,
    points: list[tuple[datetime, float]],
    limit_mph: float,
) -> bool:
    """True when the forecast reading covering ``moment`` is at or above the limit."""
    wind = _wind_at(moment, points)
    return wind is not None and wind >= limit_mph


def _wind_at(moment: datetime, points: list[tuple[datetime, float]]) -> float | None:
    best: tuple[datetime, float] | None = None
    for stamp, wind in points:
        if stamp <= moment:
            best = (stamp, wind)
        else:
            if best is None and (stamp - moment).total_seconds() <= 3600:
                return wind
            break
    if best is None:
        return None
    if (moment - best[0]).total_seconds() > 90 * 60:
        return None
    return best[1]
