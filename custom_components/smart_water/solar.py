"""Civil sunrise used to anchor the nightly plan.

This is the common low-accuracy sunrise calculation: declination from the day
of year, the equation of time, and a zenith of 90.833° so refraction and the
solar radius are included. It is accurate to roughly ten minutes, which sits
inside the default 30 minute buffer before sunrise. Longitude is degrees east
(negative in the Americas).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone


def _sunrise_hours_utc(latitude_deg: float, longitude_east: float, day: date) -> float:
    """Hours after 00:00 UTC on ``day`` when the sun rises. May be outside 0–24."""
    day_number = day.timetuple().tm_yday
    declination = math.radians(
        23.45 * math.sin(math.radians(360.0 / 365.0 * (day_number - 81)))
    )
    latitude = math.radians(latitude_deg)
    cos_hour = math.cos(math.radians(90.833)) / (
        math.cos(latitude) * math.cos(declination)
    ) - math.tan(latitude) * math.tan(declination)
    if cos_hour > 1 or cos_hour < -1:
        raise ValueError("no sunrise or sunset at this latitude on this day")
    hour_angle = math.degrees(math.acos(cos_hour))
    b = math.radians(360.0 / 365.0 * (day_number - 81))
    equation_of_time_min = (
        9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    )
    solar_noon_utc = 12.0 - longitude_east / 15.0 - equation_of_time_min / 60.0
    return solar_noon_utc - hour_angle / 15.0


def sunrise_utc(latitude_deg: float, longitude_east: float, day: date) -> datetime:
    """Timezone-aware UTC sunrise for a calendar date."""
    hours = _sunrise_hours_utc(latitude_deg, longitude_east, day)
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return midnight + timedelta(hours=hours)


def next_sunrise(
    latitude_deg: float,
    longitude_east: float,
    after: datetime,
) -> datetime:
    """The next sunrise strictly after ``after``."""
    moment = after.astimezone(timezone.utc)
    day = moment.date()
    for offset in range(0, 4):
        try:
            rise = sunrise_utc(latitude_deg, longitude_east, day + timedelta(days=offset))
        except ValueError:
            continue
        if rise > moment:
            return rise
    raise ValueError("could not find a sunrise within four days")
