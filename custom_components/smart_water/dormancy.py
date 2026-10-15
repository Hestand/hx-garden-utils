"""Temperature dormancy for turf. Non-turf plantings are left active.

The proxy is a 7-day mean of daily mean air temperature, and only after at
least three days exist. Soil temperature is not measured. Night air
temperature is the published stand-in for soil-surface temperature on
warm-season grasses, so a multi-day air mean is what this integration can
actually compute.

Warm-season shoot growth stops as air temperature falls below 50°F, and
rhizomes and stolons need soil above about 55°F for several weeks (Texas
A&M Forage Fax; the same text is republished by Mississippi State).
St. Augustine is the least cold-hardy of the common Texas warm-season
lawns (AgriLife dormant-sodding note) and grows best at 80–95°F, so its
slow and dormant lines sit 5°F higher. That shift is a judgment from the
susceptibility ranking, not a separate published cutoff. Buffalo uses the
group lines; a lower number is not published here.

Cool-season growth slows in heat. UNL G2191 says survival of drought
dormancy is greatly reduced when temperatures stay above 80°F, so the
slowdown starts there. There is no temperature-only full stop.

AgriLife says to turn irrigation off when turf is dormant. Optional
maintenance is therefore off unless the zone enables it. When it is on,
a dormant zone that is also at RAW and has not had recent rain gets
0.25 inch (the low end of the UNL 1/4–1/2 inch survival watering) no more
often than every 21 days.
"""

from __future__ import annotations

from dataclasses import dataclass

from .units import MM_PER_INCH

_WARM = frozenset({"bermuda", "zoysia", "buffalo", "warm_season_turf"})
_ST_AUGUSTINE = frozenset({"st_augustine"})
_COOL = frozenset({"cool_season_turf"})

SLOW_FACTOR = 0.5
MIN_HISTORY_DAYS = 3
HISTORY_DAYS = 7
MAINTENANCE_INTERVAL_DAYS = 21
MAINTENANCE_INCHES = 0.25
MAINTENANCE_MM = MAINTENANCE_INCHES * MM_PER_INCH

# Preset thresholds, °F. Overrides replace these per zone.
WARM_SLOW_BELOW_F = 55.0
WARM_DORMANT_BELOW_F = 50.0
ST_AUGUSTINE_SLOW_BELOW_F = 60.0
ST_AUGUSTINE_DORMANT_BELOW_F = 55.0
COOL_HEAT_ABOVE_F = 80.0


@dataclass(frozen=True)
class Dormancy:
    """One zone's seasonal state."""

    status: str
    factor: float
    mean_f: float | None
    samples: int
    detail: str
    slow_below_f: float | None
    dormant_below_f: float | None
    heat_above_f: float | None


def _mean(history: list[dict[str, object]]) -> tuple[float | None, int]:
    """Mean of up to seven distinct daily means. Newest rows win."""
    seen: set[str] = set()
    values: list[float] = []
    for row in reversed(history):
        day = str(row.get("date") or "")
        if not day or day in seen or row.get("mean_f") is None:
            continue
        seen.add(day)
        values.append(float(row["mean_f"]))
        if len(values) == HISTORY_DAYS:
            break
    if len(values) < MIN_HISTORY_DAYS:
        return None, len(values)
    return sum(values) / len(values), len(values)


def classify(
    plant_type: str,
    history: list[dict[str, object]],
    *,
    dormant_below_f: float | None = None,
    slow_below_f: float | None = None,
    heat_above_f: float | None = None,
) -> Dormancy:
    """Return active, slow, or dormant, and the crop-ET factor."""
    mean_f, samples = _mean(history)
    if plant_type in _COOL:
        heat = COOL_HEAT_ABOVE_F if heat_above_f is None else heat_above_f
        dormant_line = dormant_below_f
        if mean_f is None:
            return Dormancy(
                "active",
                1.0,
                None,
                samples,
                "Not enough temperature history to judge dormancy.",
                slow_below_f,
                dormant_line,
                heat,
            )
        if dormant_line is not None and mean_f <= dormant_line:
            return Dormancy(
                "dormant",
                0.0,
                mean_f,
                samples,
                (
                    f"Dormant: 7-day mean {mean_f:.0f}°F is at or below "
                    f"{dormant_line:.0f}°F."
                ),
                slow_below_f,
                dormant_line,
                heat,
            )
        if mean_f >= heat:
            return Dormancy(
                "slow",
                SLOW_FACTOR,
                mean_f,
                samples,
                (
                    f"Heat slowdown: 7-day mean {mean_f:.0f}°F is at or above "
                    f"{heat:.0f}°F."
                ),
                slow_below_f,
                dormant_line,
                heat,
            )
        return Dormancy(
            "active",
            1.0,
            mean_f,
            samples,
            f"Active: 7-day mean {mean_f:.0f}°F.",
            slow_below_f,
            dormant_line,
            heat,
        )

    if plant_type in _ST_AUGUSTINE:
        slow_line = ST_AUGUSTINE_SLOW_BELOW_F if slow_below_f is None else slow_below_f
        dormant_line = (
            ST_AUGUSTINE_DORMANT_BELOW_F if dormant_below_f is None else dormant_below_f
        )
    elif plant_type in _WARM:
        slow_line = WARM_SLOW_BELOW_F if slow_below_f is None else slow_below_f
        dormant_line = WARM_DORMANT_BELOW_F if dormant_below_f is None else dormant_below_f
    else:
        return Dormancy(
            "active",
            1.0,
            mean_f,
            samples,
            "No dormancy model for this planting.",
            None,
            None,
            None,
        )

    if mean_f is None:
        return Dormancy(
            "active",
            1.0,
            None,
            samples,
            "Not enough temperature history to judge dormancy.",
            slow_line,
            dormant_line,
            None,
        )
    if mean_f <= dormant_line:
        return Dormancy(
            "dormant",
            0.0,
            mean_f,
            samples,
            (
                f"Dormant: 7-day mean {mean_f:.0f}°F is at or below "
                f"{dormant_line:.0f}°F."
            ),
            slow_line,
            dormant_line,
            None,
        )
    if mean_f <= slow_line:
        return Dormancy(
            "slow",
            SLOW_FACTOR,
            mean_f,
            samples,
            (
                f"Slow growth: 7-day mean {mean_f:.0f}°F is at or below "
                f"{slow_line:.0f}°F."
            ),
            slow_line,
            dormant_line,
            None,
        )
    return Dormancy(
        "active",
        1.0,
        mean_f,
        samples,
        f"Active: 7-day mean {mean_f:.0f}°F.",
        slow_line,
        dormant_line,
        None,
    )


def maintenance_due(
    *,
    enabled: bool,
    status: str,
    days_since: int | None,
    deficit_mm: float,
    raw_mm: float,
    recent_rain_mm: float,
    recent_rain_skip_mm: float | None,
) -> bool:
    """True when a dormant zone may take a small survival watering."""
    if not enabled or status != "dormant":
        return False
    if deficit_mm < raw_mm:
        return False
    if recent_rain_skip_mm is not None and recent_rain_mm >= recent_rain_skip_mm:
        return False
    if days_since is not None and days_since < MAINTENANCE_INTERVAL_DAYS:
        return False
    return True
