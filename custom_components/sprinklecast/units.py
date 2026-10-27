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


_LENGTH_IN = {"in", "inch", "inches"}
_LENGTH_CM = {"cm", "centimeter", "centimeters"}
_LENGTH_MM = {"mm", "millimeter", "millimeters"}


def length_to_inches(value: float, unit: str | None) -> float:
    """Convert a root depth to inches. A missing or unknown unit is an error.

    Inches and centimeters are accepted. Millimeters are accepted because
    that unit is explicit. Anything else, including a blank unit, is not
    treated as inches.
    """
    token = str(unit or "").strip().casefold()
    if token in _LENGTH_IN:
        return float(value)
    if token in _LENGTH_CM:
        return float(value) / 2.54
    if token in _LENGTH_MM:
        return float(value) / MM_PER_INCH
    raise ValueError(
        "Root depth needs a unit of inches or centimeters. "
        f"{unit!r} is not one of those."
    )


def inches_to_length(inches: float, unit: str | None) -> float:
    """Convert inches to inches, centimeters, or millimeters."""
    token = str(unit or "").strip().casefold()
    if token in _LENGTH_IN:
        return float(inches)
    if token in _LENGTH_CM:
        return float(inches) * 2.54
    if token in _LENGTH_MM:
        return float(inches) * MM_PER_INCH
    raise ValueError(
        "Root depth needs a unit of inches or centimeters. "
        f"{unit!r} is not one of those."
    )


# Accepted sensor units. A missing or unknown unit is not converted.
TEMPERATURE_UNITS = "°C, C, degC, ºC, °F, F, degF, ºF"
HUMIDITY_UNITS = "%"
WIND_UNITS = "m/s, mph, mi/h, km/h, kph, kmh, kn, kt, knots"
PRESSURE_UNITS = "hPa, mbar, mb, kPa, inHg, psi, mmHg, Pa"
SOLAR_UNITS = "W/m², W/m2, Wm2, W/m^2, or any unit containing MJ"
UV_UNITS = "UV index, UV, UVI, index"
DEPTH_UNITS = "mm, in, inch, inches"
VOLUME_UNITS = (
    "gal, gallon, gallons, L, liter, liters, litre, litres, "
    "m³, m3, m^3, ft³, ft3, ft^3, cuft"
)
RATE_UNITS = "gal/min, gpm, L/min, lpm, m³/h, m3/h, m^3/h, gal/h, gph"
RAIN_RATE_UNITS = (
    "in/h, in/hr, in/hour, inch/h, inch/hr, inch/hour, "
    "inches/h, inches/hr, inches/hour, mm/h, mm/hr, mm/hour"
)
MOISTURE_UNITS = (
    "%, percent, pct, fraction, ratio, 0-1, m³/m³, m3/m3, m^3/m^3, "
    "cm³/cm³, cm3/cm3, v/v"
)

_CELSIUS = {"°c", "c", "degc", "ºc"}
_FAHRENHEIT = {"°f", "f", "degf", "ºf"}
_WIND_MS = {"m/s"}
_WIND_MPH = {"mph", "mi/h"}
_WIND_KMH = {"km/h", "kph", "kmh"}
_WIND_KN = {"kn", "kt", "knots"}
_DEPTH_MM = {"mm"}
_DEPTH_IN = {"in", "inch", "inches"}
_VOLUME_GAL = {"gal", "gallon", "gallons"}
_VOLUME_L = {"l", "liter", "liters", "litre", "litres"}
_VOLUME_M3 = {"m3", "m^3"}
_VOLUME_FT3 = {"ft3", "ft^3", "cuft"}
_RATE_GPM = {"gal/min", "gpm", "gallon/min", "gallons/min"}
_RATE_LPM = {"l/min", "lpm"}
_RATE_M3H = {"m3/h", "m^3/h"}
_RATE_GPH = {"gal/h", "gph"}
_RAIN_IN_H = {
    "in/h",
    "in/hr",
    "in/hour",
    "inch/h",
    "inch/hr",
    "inch/hour",
    "inches/h",
    "inches/hr",
    "inches/hour",
}
_RAIN_MM_H = {"mm/h", "mm/hr", "mm/hour"}
_SOLAR_W = {"w/m2", "wm2", "w/m^2"}
_UV = {"uv index", "uv", "uvi", "index"}
_MOISTURE_PERCENT = {"%", "percent", "pct"}
_MOISTURE_FRACTION = {
    "fraction",
    "ratio",
    "0-1",
    "m3/m3",
    "m^3/m^3",
    "cm3/cm3",
    "v/v",
}

_ACCEPTED = {
    "temperature": TEMPERATURE_UNITS,
    "humidity": HUMIDITY_UNITS,
    "wind": WIND_UNITS,
    "pressure": PRESSURE_UNITS,
    "solar": SOLAR_UNITS,
    "uv": UV_UNITS,
    "depth": DEPTH_UNITS,
    "volume": VOLUME_UNITS,
    "rate": RATE_UNITS,
    "rain_rate": RAIN_RATE_UNITS,
    "moisture": MOISTURE_UNITS,
}


def accepted_units(kind: str) -> str:
    """The units a field converts, for a form error or a repair."""
    return _ACCEPTED[kind]


def _token(unit: str | None) -> str:
    if unit is None:
        return ""
    return str(unit).strip()


def _folded(unit: str | None) -> str:
    return _token(unit).casefold()


def _compact(unit: str | None) -> str:
    return _folded(unit).replace(" ", "").replace("³", "3").replace("²", "2")


def unit_ok(kind: str, unit: str | None) -> bool:
    """True only when ``unit`` is one this integration converts."""
    if kind == "temperature":
        return _folded(unit) in _CELSIUS or _folded(unit) in _FAHRENHEIT
    if kind == "humidity":
        return _token(unit) == "%"
    if kind == "wind":
        token = _compact(unit)
        return token in _WIND_MS | _WIND_MPH | _WIND_KMH | _WIND_KN
    if kind == "pressure":
        token = _folded(unit)
        return token in {"hpa", "mbar", "mb", "kpa", "inhg", "psi", "mmhg", "pa"}
    if kind == "solar":
        token = _compact(unit)
        return bool(token) and (token in _SOLAR_W or "mj" in token)
    if kind == "uv":
        return _folded(unit) in _UV
    if kind == "depth":
        token = _folded(unit)
        return token in _DEPTH_MM or token in _DEPTH_IN
    if kind == "volume":
        return _compact(unit) in _VOLUME_GAL | _VOLUME_L | _VOLUME_M3 | _VOLUME_FT3
    if kind == "rate":
        return _compact(unit) in _RATE_GPM | _RATE_LPM | _RATE_M3H | _RATE_GPH
    if kind == "rain_rate":
        token = _compact(unit)
        return token in _RAIN_IN_H or token in _RAIN_MM_H
    if kind == "moisture":
        token = _compact(unit)
        return token in _MOISTURE_PERCENT or token in _MOISTURE_FRACTION
    raise ValueError(f"unknown unit kind {kind}")


def moisture_scale(unit: str | None) -> str | None:
    """``percent`` or ``fraction`` when the moisture unit says which one."""
    token = _compact(unit)
    if token in _MOISTURE_PERCENT:
        return "percent"
    if token in _MOISTURE_FRACTION:
        return "fraction"
    return None


def temperature_c(value: float, unit: str | None) -> float | None:
    """Convert a temperature reading to Celsius, or None if the unit is unknown."""
    folded = _folded(unit)
    if folded in _FAHRENHEIT:
        return (value - 32.0) * 5.0 / 9.0
    if folded in _CELSIUS:
        return value
    return None


def temperature_f(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0


def speed_mph(meters_per_second: float) -> float:
    """Convert m/s to miles per hour."""
    return meters_per_second / 0.44704


def depth_mm(value: float, unit: str | None) -> float | None:
    """Convert a precipitation or water-depth reading to millimeters."""
    token = _folded(unit)
    if token in _DEPTH_IN:
        return inches_to_mm(value)
    if token in _DEPTH_MM:
        return value
    return None


def speed_m_s(value: float, unit: str | None) -> float | None:
    """Convert a wind speed to meters per second."""
    token = _compact(unit)
    if token in _WIND_MPH:
        return value * 0.44704
    if token in _WIND_KMH:
        return value / 3.6
    if token in _WIND_KN:
        return value * 0.514444
    if token in _WIND_MS:
        return value
    return None


def pressure_kpa(value: float, unit: str | None) -> float | None:
    """Convert an air-pressure reading to kilopascals."""
    token = _folded(unit)
    if token in {"hpa", "mbar", "mb"}:
        return value * 0.1
    if token == "kpa":
        return value
    if token == "inhg":
        return value * 3.386389
    if token == "psi":
        return value * 6.894757
    if token == "mmhg":
        return value * 0.133322
    if token == "pa":
        return value / 1000.0
    return None


def volume_gallons(value: float, unit: str | None) -> float | None:
    """Convert a volume total to US gallons."""
    token = _compact(unit)
    if token in _VOLUME_L:
        return value * 0.264172
    if token in _VOLUME_M3:
        return value * 264.172
    if token in _VOLUME_FT3:
        return value * 7.48052
    if token in _VOLUME_GAL:
        return value
    return None


def rain_rate_mm_h(value: float, unit: str | None) -> float | None:
    """Convert a rain intensity to millimeters per hour.

    A depth (mm, in) is not a rate. A missing or unknown unit is ignored.
    """
    token = _compact(unit)
    if token in _RAIN_MM_H:
        return value
    if token in _RAIN_IN_H:
        return inches_to_mm(value)
    return None


def rate_gpm(value: float, unit: str | None) -> float | None:
    """Convert a flow rate to US gallons per minute."""
    token = _compact(unit)
    if token in _RATE_LPM:
        return value * 0.264172
    if token in _RATE_M3H:
        return value * 264.172 / 60.0
    if token in _RATE_GPH:
        return value / 60.0
    if token in _RATE_GPM:
        return value
    return None


def humidity_percent(value: float, unit: str | None) -> float | None:
    """A humidity reading in percent. Only ``%`` is accepted."""
    if _token(unit) == "%":
        return value
    return None


def uv_index_value(value: float, unit: str | None) -> float | None:
    """A UV index. The unit has to say that it is an index."""
    if _folded(unit) in _UV:
        return value
    return None


def solar_parts(value: float, unit: str | None) -> tuple[float | None, float | None]:
    """Split a solar sensor into daily MJ/m² and instantaneous W/m².

    Daily Penman-Monteith needs a daily radiation total. An instantaneous
    W/m² reading (typical of a Tempest) is kept for later, not treated as Rs.
    A missing unit, a UV index, or illuminance is ignored.
    """
    token = _compact(unit)
    if token in _SOLAR_W:
        return None, value
    if token and "mj" in token:
        return value, None
    return None, None
