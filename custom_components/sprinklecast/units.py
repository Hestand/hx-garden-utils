"""Unit conversions used by the water-balance math.

FAO-56 formulas in this integration run in SI (mm, m, °C, kPa, m/s).
Zone precipitation rate stays in inches per hour because that is how
sprinkler tables and the NRCS intake rates are published.
"""

from __future__ import annotations

MM_PER_INCH = 25.4
M_PER_INCH = 0.0254


def inches_to_mm(inches: float) -> float:
    """Convert a depth or precipitation amount to millimeters."""
    return inches * MM_PER_INCH


def mm_to_inches(mm: float) -> float:
    """Convert millimeters to inches."""
    return mm / MM_PER_INCH


def depth_to_inches(value: float, unit: str | None) -> float:
    """Convert a precipitation depth in the user's unit to inches."""
    if unit == "mm":
        return value / MM_PER_INCH
    if unit == "cm":
        return value / 2.54
    return value


def inches_to_depth(inches: float, unit: str | None) -> float:
    """Convert inches to the user's precipitation unit."""
    if unit == "mm":
        return inches * MM_PER_INCH
    if unit == "cm":
        return inches * 2.54
    return inches


def inches_to_m(inches: float) -> float:
    """Convert a root depth in inches to meters (FAO Zr)."""
    return inches * M_PER_INCH


def temperature_c(value: float, unit: str | None) -> float:
    """Convert a temperature reading to Celsius."""
    if unit in {"°F", "F", "degF", "ºF"}:
        return (value - 32.0) * 5.0 / 9.0
    return value


def temperature_f(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


def speed_mph(meters_per_second: float) -> float:
    """Convert m/s to miles per hour."""
    return meters_per_second / 0.44704


def depth_mm(value: float, unit: str | None) -> float:
    """Convert a precipitation or water-depth reading to millimeters."""
    if unit in {"in", "inch", "inches"}:
        return inches_to_mm(value)
    return value


def speed_m_s(value: float, unit: str | None) -> float:
    """Convert a wind speed to meters per second."""
    normalized = (unit or "m/s").lower().replace(" ", "")
    if normalized in {"mph", "mi/h"}:
        return value * 0.44704
    if normalized in {"km/h", "kph", "kmh"}:
        return value / 3.6
    if normalized in {"kn", "kt", "knots"}:
        return value * 0.514444
    return value


def pressure_kpa(value: float, unit: str | None) -> float:
    """Convert an air-pressure reading to kilopascals."""
    normalized = unit or "hPa"
    if normalized in {"hPa", "mbar", "mb"}:
        return value * 0.1
    if normalized == "kPa":
        return value
    if normalized in {"inHg", "inhg"}:
        return value * 3.386389
    if normalized == "psi":
        return value * 6.894757
    if normalized == "mmHg":
        return value * 0.133322
    if normalized == "Pa":
        return value / 1000.0
    return value * 0.1


def volume_gallons(value: float, unit: str | None) -> float:
    """Convert a volume total to US gallons."""
    normalized = (unit or "gal").lower().replace(" ", "").replace("³", "3")
    if normalized in {"l", "liter", "liters", "litre", "litres"}:
        return value * 0.264172
    if normalized in {"m3", "m^3"}:
        return value * 264.172
    if normalized in {"ft3", "ft^3", "cuft"}:
        return value * 7.48052
    return value


def rate_gpm(value: float, unit: str | None) -> float:
    """Convert a flow rate to US gallons per minute."""
    normalized = (unit or "gal/min").lower().replace(" ", "").replace("³", "3")
    if normalized in {"l/min", "lpm"}:
        return value * 0.264172
    if normalized in {"m3/h", "m^3/h"}:
        return value * 264.172 / 60.0
    if normalized in {"gal/h", "gph"}:
        return value / 60.0
    return value


def solar_parts(value: float, unit: str | None) -> tuple[float | None, float | None]:
    """Split a solar sensor into daily MJ/m² and instantaneous W/m².

    Daily Penman-Monteith needs a daily radiation total. An instantaneous
    W/m² reading (typical of a Tempest) is kept for later, not treated as Rs.
    A UV index is not solar radiation and is ignored.
    """
    normalized = (unit or "").lower().replace(" ", "").replace("²", "2")
    if normalized in {"w/m2", "wm2", "w/m^2"}:
        return None, value
    if "mj" in normalized:
        return value, None
    return None, None
