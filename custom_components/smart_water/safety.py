"""Guards that keep v0.1 from watering.

Dry-run is an optional switch and defaults off. It is not what stops
watering in this version: this module refuses execution because v0.1 has
no executor. A later version that calls ``hydrawise.start_watering`` must
keep the dry-run and mode checks.
"""

from __future__ import annotations

from .const import MODE_AUTO, MODE_NOTIFY_ONLY, MODE_OFF

# Flip only when an executor exists and has been reviewed. Tests assert this
# stays false for the 0.1 series.
EXECUTION_IMPLEMENTED = False


def block_reason(*, dry_run: bool, mode: str) -> str:
    """Return why a plan must not open a valve.

    The string is never empty while ``EXECUTION_IMPLEMENTED`` is false, so a
    caller cannot treat a cleared dry-run flag as permission to water.
    """
    reasons: list[str] = []
    if not EXECUTION_IMPLEMENTED:
        reasons.append("v0.1 has no executor and will not open valves")
    if dry_run:
        reasons.append("dry-run is on")
    if mode != MODE_AUTO:
        reasons.append(f"mode is {mode}")
    return "; ".join(reasons)


def would_execute(*, dry_run: bool, mode: str) -> bool:
    """Return whether the integration may water. Always false in v0.1."""
    if not EXECUTION_IMPLEMENTED:
        return False
    return not dry_run and mode == MODE_AUTO


def mode_after_master_switch(*, mode: str, dry_run: bool, turn_on: bool) -> str:
    """Map the master switch onto a hub mode without clearing dry-run.

    Turning the switch on never leaves dry-run. From off, dry-run hubs come
    back to notify-only. A hub already in auto or notify-only keeps that mode.
    """
    if not turn_on:
        return MODE_OFF
    if mode != MODE_OFF:
        return mode
    if dry_run:
        return MODE_NOTIFY_ONLY
    return MODE_AUTO
