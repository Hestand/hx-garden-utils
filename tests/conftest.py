"""Keep the suite on the same side of the plan hour.

The evening bucket step runs at 23:00 local. A test that stores a deficit and
then starts the hub would otherwise add today's water loss only when the
suite runs after that hour.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.util import dt as dt_util
import pytest

CHICAGO = ZoneInfo("America/Chicago")


@pytest.fixture(autouse=True)
def _before_the_plan_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze local time at 15:00 so the plan-hour bucket step stays idle."""
    afternoon = datetime.now(CHICAGO).replace(hour=15, minute=0, second=0, microsecond=0)

    def frozen_now(tz=None):
        if tz is None:
            return afternoon
        return afternoon.astimezone(tz)

    monkeypatch.setattr(dt_util, "now", frozen_now)
