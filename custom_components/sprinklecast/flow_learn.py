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
DEFAULT_TREND_PCT = 10.0
DEFAULT_TREND_RUNS = 5
SAMPLE_LIMIT = 12
FLOW_HISTORY_LIMIT = 30
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


def _positive(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def reference_flow(state: dict) -> tuple[float | None, str]:
    """Gallons per minute to compare against, and where that number came from.

    A catch-cup or manual baseline wins. Otherwise this is the learned median.
    """
    baseline = _positive(state.get("baseline_gpm"))
    if baseline is not None:
        return baseline, str(state.get("baseline_source") or "catch_cup")
    learned = _positive(state.get("learned_gpm"))
    if learned is not None:
        return learned, "learned"
    return None, "none"


def compare_to_reference(
    gpm: float | None,
    reference: float | None,
    *,
    high_pct: float,
    low_pct: float,
) -> str:
    """Label one run against a fixed baseline. No minimum-run wait."""
    if gpm is None or gpm <= 0:
        return "no_data"
    if reference is None or reference <= 0:
        return "no_baseline"
    if gpm > reference * (1.0 + high_pct / 100.0):
        return "high_flow"
    if gpm < reference * (1.0 - low_pct / 100.0):
        return "low_flow"
    return "ok"


def flow_problem(
    *,
    baseline_gpm: float | None,
    last_run_gpm: float | None,
    trend: str,
    high_pct: float,
    low_pct: float,
) -> tuple[bool, str, float | None]:
    """Whether Flow problem is on, a short reason, and the percent gap.

    A saved baseline is required. A learned median, with no baseline, stays
    off even when that run would have been high or low against the median.
    """
    baseline = _positive(baseline_gpm)
    if baseline is None:
        return False, "No baseline yet", None
    gap = percent_vs_reference(last_run_gpm, baseline)
    shown = None if gap is None else round(gap, 1)
    run = compare_to_reference(
        last_run_gpm, baseline, high_pct=high_pct, low_pct=low_pct
    )
    reasons: list[str] = []
    if run == "high_flow":
        reasons.append("Last run is above the baseline")
    elif run == "low_flow":
        reasons.append("Last run is below the baseline")
    if trend == "high_trend":
        reasons.append("Recent runs are above the baseline")
    elif trend == "low_trend":
        reasons.append("Recent runs are below the baseline")
    if reasons:
        return True, ". ".join(reasons), shown
    if run == "no_data":
        return False, "Baseline is set. No run to compare yet.", None
    return False, "Last run is within the baseline", shown


def percent_vs_reference(gpm: float | None, reference: float | None) -> float | None:
    """Percent difference of one run from the reference. Positive is higher."""
    measured = _positive(gpm)
    base = _positive(reference)
    if measured is None or base is None:
        return None
    return (measured - base) / base * 100.0


def append_flow_history(
    history: list | None,
    *,
    at: str,
    gpm: float,
    minutes: float,
) -> list[dict]:
    """Keep the last 30 per-run averages. Older rows drop off the front."""
    rows = [
        dict(item)
        for item in list(history or [])
        if isinstance(item, dict) and _positive(item.get("gpm")) is not None
    ]
    rows.append(
        {
            "at": at,
            "gpm": round(float(gpm), 3),
            "minutes": round(float(minutes), 2),
        }
    )
    return rows[-FLOW_HISTORY_LIMIT:]


def trend_status(
    history: list | None,
    reference: float | None,
    *,
    runs: int = DEFAULT_TREND_RUNS,
    trend_pct: float = DEFAULT_TREND_PCT,
) -> tuple[str, float | None]:
    """Median of the last N runs versus the reference.

    Returns ``(status, drift_pct)``. Status is learning until N runs exist.
    A drift past ``trend_pct`` is high_trend or low_trend.
    """
    gpms: list[float] = []
    for item in list(history or []):
        if not isinstance(item, dict):
            continue
        value = _positive(item.get("gpm"))
        if value is not None:
            gpms.append(value)
    base = _positive(reference)
    window = gpms[-max(1, int(runs)) :]
    if not window or base is None:
        return ("no_baseline" if base is None else "learning"), None
    drift = (float(statistics.median(window)) - base) / base * 100.0
    if len(window) < int(runs):
        return "learning", drift
    if drift > trend_pct:
        return "high_trend", drift
    if drift < -trend_pct:
        return "low_trend", drift
    return "ok", drift


def alert_detail(
    kind: str,
    *,
    name: str,
    gpm: float | None,
    learned: float | None,
    source: str = "learned",
) -> str:
    """One sentence for a notification, a repair, and the event payload."""
    learned_text = "unknown" if not learned else f"{learned:.2f}"
    gpm_text = "unknown" if not gpm else f"{gpm:.2f}"
    if source in {"learned", "none", ""}:
        normal = f"Learned normal is {learned_text} gal/min."
    else:
        normal = f"Baseline is {learned_text} gal/min."
    if kind == "high_flow":
        return (
            f"{name} flowed at {gpm_text} gal/min. {normal} "
            "That is high enough to be a broken head or a leak."
        )
    if kind == "low_flow":
        return (
            f"{name} flowed at {gpm_text} gal/min. {normal} "
            "That is low enough to be a clog, a stuck valve, or low pressure."
        )
    if kind == "main_leak":
        return (
            f"Flow was seen while no zone was running"
            + (f" ({gpm_text} gal/min)." if gpm else ".")
            + " That can be a main-line leak or a valve that did not close."
        )
    return f"{name}: {kind}."


def trend_note(
    status: str,
    *,
    reference: float | None,
    have: int,
    need: int,
) -> str:
    """Plain status for the device page.

    ``learning`` used to be the whole message after a baseline was saved.
    The baseline is already set. The trend is what still needs normal runs.
    """
    if reference is None or status == "no_baseline":
        return "No baseline yet. Run a catch-cup test, or save the flow, to set one."
    base = f"Baseline is set at {reference:.2f} gal/min."
    if status == "learning" or have < max(1, int(need)):
        return f"{base} Trend needs {int(need)} normal runs ({int(have)} so far)."
    if status == "high_trend":
        return f"{base} Recent runs are above it."
    if status == "low_trend":
        return f"{base} Recent runs are below it."
    return f"{base} Recent runs are in line with it."


def trend_detail(
    kind: str,
    *,
    name: str,
    drift_pct: float,
    reference: float,
    source: str,
) -> str:
    """One sentence when the recent median has drifted from the baseline."""
    direction = "higher" if kind == "high_trend" else "lower"
    if source == "learned":
        basis = "the learned flow"
    elif source == "manual":
        basis = "the saved baseline"
    else:
        basis = "the catch-cup baseline"
    return (
        f"{name}'s recent runs are {abs(drift_pct):.0f}% {direction} than {basis} "
        f"of {reference:.2f} gal/min. A slow change can be a clogging nozzle or a growing leak."
    )
