"""Persist bucket state and the last plan across restarts."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_ADJUSTMENT_PCT, DOMAIN
from .observe import fresh_day

STORAGE_VERSION = 1


def fresh_zone() -> dict[str, Any]:
    """A zone that starts at field capacity (deficit 0) and is enabled."""
    return {
        "deficit_mm": 0.0,
        "balance_date": None,
        "skipped_until": None,
        "enabled": True,
        "adjustment_pct": DEFAULT_ADJUSTMENT_PCT,
        "flow_date": None,
        "flow_delivered_gal": 0.0,
        "flow_cursor": None,
        "flow_last_at": None,
        "last_run_now": None,
        "moisture_deficit_mm": None,
    }


class SmartWaterStore:
    """JSON storage for one hub."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Create the store. Call ``async_load`` before reading."""
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}"
        )
        self.zones: dict[str, dict[str, Any]] = {}
        self.plan: dict[str, Any] | None = None
        self.notified_date: str | None = None
        self.et0_mm: float | None = None
        self.et0_method: str | None = None
        self.et0_detail: str | None = None
        self.et0_date: str | None = None
        self.weather: dict[str, Any] = fresh_day("")
        self.simulation: dict[str, Any] | None = None

    async def async_load(self) -> None:
        """Load the last saved state."""
        data = await self._store.async_load() or {}
        self.zones = {
            zone_id: {**fresh_zone(), **zone}
            for zone_id, zone in dict(data.get("zones") or {}).items()
        }
        self.plan = data.get("plan")
        self.notified_date = data.get("notified_date")
        self.et0_mm = data.get("et0_mm")
        self.et0_method = data.get("et0_method")
        self.et0_detail = data.get("et0_detail")
        self.et0_date = data.get("et0_date")
        saved_weather = dict(data.get("weather") or {})
        self.weather = {**fresh_day(str(saved_weather.get("date") or "")), **saved_weather}
        saved_simulation = data.get("simulation")
        self.simulation = dict(saved_simulation) if isinstance(saved_simulation, dict) else None

    def zone(self, zone_id: str) -> dict[str, Any]:
        """Return mutable state for a zone, creating it at field capacity."""
        state = self.zones.get(zone_id)
        if state is None:
            state = fresh_zone()
            self.zones[zone_id] = state
        return state

    def weather_for(self, date: str) -> dict[str, Any]:
        """Return today's accumulation, resetting it when the date changes."""
        if self.weather.get("date") != date:
            self.weather = fresh_day(date)
        return self.weather

    def prune(self, zone_ids: set[str]) -> None:
        """Drop state for zones that were removed."""
        for zone_id in list(self.zones):
            if zone_id not in zone_ids:
                del self.zones[zone_id]

    async def async_save(self) -> None:
        """Write the current state."""
        await self._store.async_save(
            {
                "zones": self.zones,
                "plan": self.plan,
                "notified_date": self.notified_date,
                "et0_mm": self.et0_mm,
                "et0_method": self.et0_method,
                "et0_detail": self.et0_detail,
                "et0_date": self.et0_date,
                "weather": self.weather,
                "simulation": self.simulation,
            }
        )
