"""Only the executor may call a zone entity, and never Hydrawise."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "smart_water"
CALL = re.compile(
    r"""async_call\(\s*['\"](valve|switch|hydrawise|input_boolean)['\"]""",
    re.MULTILINE,
)
HYDRAWISE = re.compile(r"""async_call\(\s*['\"]hydrawise['\"]""")


def test_only_the_executor_calls_zone_entities() -> None:
    offenders: list[str] = []
    for path in sorted(ROOT.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "start_watering" in text:
            offenders.append(f"{path.name}: start_watering")
        if HYDRAWISE.search(text):
            offenders.append(f"{path.name}: hydrawise")
        if path.name != "executor.py" and CALL.search(text):
            offenders.append(f"{path.name}: service call")
    assert offenders == []
    executor = (ROOT / "executor.py").read_text(encoding="utf-8")
    assert "switch" in executor and "valve" in executor and "input_boolean" in executor


def test_execution_requires_the_automatic_switch() -> None:
    from smart_water.safety import EXECUTION_IMPLEMENTED, would_execute

    assert EXECUTION_IMPLEMENTED is True
    assert would_execute(automatic=False, mode="auto") is False
    assert would_execute(automatic=True, mode="auto") is True
    assert would_execute(automatic=True, mode="notify_only") is True
    assert would_execute(automatic=True, mode="off") is False
