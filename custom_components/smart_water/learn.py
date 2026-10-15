"""Slow available-water correction from a soil-moisture sensor.

The sensor's fraction full does not depend on our bucket size. The model
fraction full is ``1 - deficit / (TAW × factor)``. When the sensor is
wetter, the factor rises so the same deficit is a smaller share of a larger
bucket. The step is 0.05 times the gap, clamped to ±30% (0.7–1.3). Those
bounds are engineering limits, not an agronomy citation.

Learning is skipped on days with at least 2.5 mm of rain and on the day of
a watering and the day after. One update per day, applied to the next plan.
Confidence reaches 1 after 14 samples.
"""

from __future__ import annotations

from datetime import date

LEARN_RATE = 0.05
FACTOR_MIN = 0.7
FACTOR_MAX = 1.3
CONFIDENCE_SAMPLES = 14
RAIN_HOLD_MM = 2.5


def should_learn(
    *,
    enabled: bool,
    has_sensor: bool,
    rain_today_mm: float,
    last_watered: str | None,
    today: date,
) -> bool:
    """Return whether today's reading may move the factor."""
    if not enabled or not has_sensor:
        return False
    if rain_today_mm >= RAIN_HOLD_MM:
        return False
    if last_watered:
        watered = date.fromisoformat(str(last_watered)[:10])
        if (today - watered).days <= 1:
            return False
    return True


def update_awc_factor(
    factor: float,
    sensor_full: float,
    deficit_mm: float,
    taw_mm: float,
    samples: int,
) -> tuple[float, float, int]:
    """Return the next factor, confidence, and sample count."""
    scaled = taw_mm * factor
    if scaled <= 0:
        model_full = 1.0
    else:
        model_full = 1.0 - min(1.0, max(0.0, deficit_mm / scaled))
    updated = factor + LEARN_RATE * (sensor_full - model_full)
    updated = min(FACTOR_MAX, max(FACTOR_MIN, updated))
    count = samples + 1
    confidence = min(1.0, count / CONFIDENCE_SAMPLES)
    return updated, confidence, count


def relative_full(reading: float) -> float:
    """A 0–1 fraction, or a 0–100 percent, as a fraction full."""
    if reading > 1.0:
        fraction = reading / 100.0
    else:
        fraction = reading
    return min(1.0, max(0.0, fraction))
