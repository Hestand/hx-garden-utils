"""Learn a zone's normal gallons per minute and label a run against it.

The estimate is the median of the last few runs, so one broken head does not
become the new normal. Alerts start after a minimum number of learned runs.
A run far from the median is reported and then left out of the median.
"""

from __future__ import annotations

import statistics

DEFAULT_HIGH_PCT = 30.0
DEFAULT_LOW_PCT = 25.0
DEFAULT_LEARN_RUNS = 3
DEFAULT_IDLE_GPM = 0.5
SAMPLE_LIMIT = 12
# A run outside this band is an outlier and is not folded into the median.
_OUTLIER_HIGH = 2.0
_OUTLIER_LOW = 0.4


def robust_gpm(samples: list[float]) -> float | None:
    """Median of the stored runs. None when nothing has been learned."""
    clean = [float(value) for value in samples if value and float(value) > 0]
    if not clean:
        return None
    return float(statistics.median(clean[-SAMPLE_LIMIT:]))


def accept_sample(samples: list[float], gpm: float, *, minimum_runs: int) -> list[float]:
    """Append a run, dropping outliers once the median is established."""
    if gpm <= 0:
        return list(samples)
    learned = robust_gpm(samples) if len(samples) >= minimum_runs else None
    if learned is not None and (gpm > learned * _OUTLIER_HIGH or gpm < learned * _OUTLIER_LOW):
        return list(samples)
    updated = [*samples, float(gpm)]
    return updated[-SAMPLE_LIMIT:]


def run_status(
    gpm: float | None,
    samples_before: list[float],
    *,
    high_pct: float,
    low_pct: float,
    minimum_runs: int,
) -> str:
    """Return learning, ok, high_flow, or low_flow for one finished run."""
    if gpm is None or gpm <= 0:
        return "no_data"
    if len(samples_before) < minimum_runs:
        return "learning"
    learned = robust_gpm(samples_before)
    if learned is None or learned <= 0:
        return "learning"
    if gpm > learned * (1.0 + high_pct / 100.0):
        return "high_flow"
    if gpm < learned * (1.0 - low_pct / 100.0):
        return "low_flow"
    return "ok"


def alert_detail(kind: str, *, name: str, gpm: float | None, learned: float | None) -> str:
    """One sentence for a notification, a repair, and the event payload."""
    learned_text = "unknown" if not learned else f"{learned:.2f}"
    gpm_text = "unknown" if not gpm else f"{gpm:.2f}"
    if kind == "high_flow":
        return (
            f"{name} flowed at {gpm_text} gal/min. Learned normal is {learned_text} gal/min. "
            "That is high enough to be a broken head or a leak."
        )
    if kind == "low_flow":
        return (
            f"{name} flowed at {gpm_text} gal/min. Learned normal is {learned_text} gal/min. "
            "That is low enough to be a clog, a stuck valve, or low pressure."
        )
    if kind == "main_leak":
        return (
            f"Flow was seen while no zone was running"
            + (f" ({gpm_text} gal/min)." if gpm else ".")
            + " That can be a main-line leak or a valve that did not close."
        )
    return f"{name}: {kind}."
