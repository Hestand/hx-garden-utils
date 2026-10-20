"""Persist bucket state and the last plan across restarts."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DEFAULT_ADJUSTMENT_PCT, DOMAIN
from .observe import fresh_day

STORAGE_VERSION = 1
RUN_HISTORY_LIMIT = 60


def remember_run(state: dict[str, Any], run: dict[str, Any]) -> None:
    """Append one finished run. The list is capped so storage stays small."""
    history = [
        item for item in list(state.get("run_history") or []) if isinstance(item, dict)
    ]
    history.append(run)
    state["run_history"] = history[-RUN_HISTORY_LIMIT:]


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
        "last_watered": None,
        "last_run": None,
        "learn_factor": 1.0,
        "learn_confidence": 0.0,
        "learn_samples": 0,
        "learn_date": None,
        "dormancy": "active",
        "dormancy_mean_f": None,
        "dormancy_detail": "",
        "gpm_samples": [],
        "learned_gpm": None,
        "last_run_gpm": None,
        "flow_alert": None,
        "flow_locked": False,
        "water_total_gal": 0.0,
        "water_days": {},
        "forecast_defer_days": 0,
        "forecast_defer_last": None,
        "bucket_history": [],
        "audit_history": [],
        "run_history": [],
        "audit_pending": None,
        "baseline_gpm": None,
        "baseline_gpm_at": None,
        "baseline_source": None,
        "flow_history": [],
        "catch_cup": None,
        "catch_cup_pending": None,
        "measured_precipitation_rate_in_hr": None,
        "measured_efficiency": None,
        "measured_du_lq": None,
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
        self.automatic = False
        self.watering_entity: str | None = None
        self.temp_history: list[dict[str, Any]] = []
        self.armed_date: str | None = None
        self.plan_marked_at: str | None = None
        self.flow_locked = False
        self.budget_alert_week: str | None = None
        self.summary_sent_week: str | None = None
        self.freeze_alert_key: str | None = None
        self.freeze_alert_detail: str | None = None
        self.et0_history: list[dict[str, Any]] = []
        self.flow_idle_cursor: float | None = None
        self.flow_idle_last_at: str | None = None
        self.flow_idle_alert_date: str | None = None

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
        self.automatic = bool(data.get("automatic", False))
        watering = data.get("watering_entity")
        self.watering_entity = str(watering) if watering else None
        self.temp_history = list(data.get("temp_history") or [])
        self.armed_date = data.get("armed_date")
        self.plan_marked_at = data.get("plan_marked_at")
        self.flow_locked = bool(data.get("flow_locked", False))
        self.budget_alert_week = data.get("budget_alert_week")
        self.summary_sent_week = data.get("summary_sent_week")
        self.freeze_alert_key = data.get("freeze_alert_key")
        self.freeze_alert_detail = data.get("freeze_alert_detail")
        self.et0_history = list(data.get("et0_history") or [])
        cursor = data.get("flow_idle_cursor")
        self.flow_idle_cursor = None if cursor is None else float(cursor)
        self.flow_idle_last_at = data.get("flow_idle_last_at")
        self.flow_idle_alert_date = data.get("flow_idle_alert_date")

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
            events = list(self.weather.get("rain_events") or [])
            cursor = self.weather.get("rain_cursor")
            last_at = self.weather.get("rain_last_at")
            self.weather = fresh_day(date)
            self.weather["rain_events"] = events
            self.weather["rain_cursor"] = cursor
            self.weather["rain_last_at"] = last_at
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
                "automatic": self.automatic,
                "watering_entity": self.watering_entity,
                "temp_history": self.temp_history,
                "armed_date": self.armed_date,
                "plan_marked_at": self.plan_marked_at,
                "flow_locked": self.flow_locked,
                "budget_alert_week": self.budget_alert_week,
                "summary_sent_week": self.summary_sent_week,
                "freeze_alert_key": self.freeze_alert_key,
                "freeze_alert_detail": self.freeze_alert_detail,
                "et0_history": self.et0_history,
                "flow_idle_cursor": self.flow_idle_cursor,
                "flow_idle_last_at": self.flow_idle_last_at,
                "flow_idle_alert_date": self.flow_idle_alert_date,
            }
        )
