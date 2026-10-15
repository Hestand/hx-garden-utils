"""v0.2 must not grow a valve, switch, or controller call."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "smart_water"
CALL = re.compile(
    r"""async_call\(\s*['\"](valve|switch|hydrawise|input_boolean)['\"]""",
    re.MULTILINE,
)


def test_python_sources_do_not_actuate() -> None:
    offenders: list[str] = []
    for path in sorted(ROOT.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "start_watering" in text:
            offenders.append(f"{path.name}: start_watering")
        if CALL.search(text):
            offenders.append(f"{path.name}: service call")
    assert offenders == []


def test_execution_flag_stays_off() -> None:
    from smart_water.safety import EXECUTION_IMPLEMENTED, would_execute

    assert EXECUTION_IMPLEMENTED is False
    assert would_execute(dry_run=False, mode="auto") is False
