"""Guards that keep this version from watering.

Dry-run is an optional switch and defaults off. It is not what stops
watering: this module refuses execution because there is no executor.
A later executor must call the zone's stored Home Assistant entity
(valve, switch, or another on/off entity). It must not call Hydrawise
APIs or services.
"""

from __future__ import annotations

from .const import MODE_AUTO, MODE_NOTIFY_ONLY, MODE_OFF

# Flip only when an executor exists and has been reviewed. Tests assert this
# stays false until a generic entity executor has been reviewed.
EXECUTION_IMPLEMENTED = False


def block_reason(*, dry_run: bool, mode: str) -> str:
    """Return why a plan must not open a valve.

    The string is never empty while ``EXECUTION_IMPLEMENTED`` is false, so a
    caller cannot treat a cleared dry-run flag as permission to water.
    """
    reasons: list[str] = []
    if not EXECUTION_IMPLEMENTED:
        reasons.append("no executor and will not open valves")
    if dry_run:
        reasons.append("dry-run is on")
    if mode != MODE_AUTO:
        reasons.append(f"mode is {mode}")
    return "; ".join(reasons)


def would_execute(*, dry_run: bool, mode: str) -> bool:
    """Return whether the integration may water. Always false in v0.3."""
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
