"""Whether a plan may open a zone's on/off entity.

The executor calls the zone's stored Home Assistant entity (valve, switch,
or input_boolean). It does not call Hydrawise APIs or services. Watering
requires the hub's Automatic watering switch. The switch defaults off,
including after an upgrade.
"""

from __future__ import annotations

# The generic entity executor lives in executor.py.
EXECUTION_IMPLEMENTED = True


def block_reason(*, automatic: bool) -> str:
    """Return why a plan must not open a valve. Empty when it may."""
    reasons: list[str] = []
    if not EXECUTION_IMPLEMENTED:
        reasons.append("no executor and will not open valves")
    if not automatic:
        reasons.append("automatic watering is off")
    return "; ".join(reasons)


def would_execute(*, automatic: bool) -> bool:
    """Return whether an automatic plan may open zone entities."""
    if not EXECUTION_IMPLEMENTED:
        return False
    return bool(automatic)
