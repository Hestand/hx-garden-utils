"""A calendar of planned bursts and runs that already happened."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import SmartWaterConfigEntry
from .entity import SmartWaterHubEntity
from .units import mm_to_inches


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return dt_util.as_local(value)
    return value


def _overlaps(event: CalendarEvent, start: datetime, end: datetime) -> bool:
    event_start = event.start_datetime_local
    event_end = event.end_datetime_local
    return event_start < end and event_end > start


def _burst_events(days: list[dict], uid_prefix: str) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    for day in days:
        past_forecast = bool(day.get("estimated"))
        for zone in list(day.get("zones") or []):
            if not isinstance(zone, dict) or zone.get("scheduled") is False:
                continue
            name = str(zone.get("name") or "Zone")
            zone_id = str(zone.get("zone_id") or name)
            for burst in list(zone.get("bursts") or []):
                if not isinstance(burst, dict):
                    continue
                start_raw = burst.get("start_at")
                end_raw = burst.get("end_at")
                if not start_raw or not end_raw:
                    continue
                start = _aware(datetime.fromisoformat(str(start_raw)))
                end = _aware(datetime.fromisoformat(str(end_raw)))
                minutes = burst.get("minutes")
                inches = burst.get("inches")
                if inches is None and burst.get("mm") is not None:
                    inches = round(mm_to_inches(float(burst["mm"])), 3)
                cycle = burst.get("cycle")
                total = burst.get("of")
                parts = [f"{minutes} min"]
                if inches is not None:
                    parts.append(f"{float(inches):.2f} in")
                if cycle is not None and total is not None:
                    parts.append(f"cycle {cycle} of {total}")
                description = ", ".join(str(part) for part in parts) + "."
                if past_forecast:
                    description += " Estimated."
                events.append(
                    CalendarEvent(
                        start=start,
                        end=end,
                        summary=name,
                        description=description,
                        uid=f"{uid_prefix}-{zone_id}-{start.isoformat()}-{cycle}",
                    )
                )
    return events


def _history_events(runs: list[dict], uid_prefix: str) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    for run in runs:
        if str(run.get("result") or "ok") != "ok":
            continue
        stamp = run.get("at")
        if not stamp:
            continue
        start = _aware(datetime.fromisoformat(str(stamp)))
        minutes = float(run.get("minutes") or 0)
        end = start + timedelta(minutes=max(minutes, 1))
        inches = mm_to_inches(float(run.get("net_mm") or 0))
        name = str(run.get("name") or "Zone")
        events.append(
            CalendarEvent(
                start=start,
                end=end,
                summary=name,
                description=(
                    f"Completed run. {minutes:.0f} min, {inches:.2f} in."
                ),
                uid=f"{uid_prefix}-ran-{run.get('zone_id')}-{start.isoformat()}",
            )
        )
    return events


def watering_events(
    *,
    days: list[dict] | None,
    runs: list[dict] | None,
    start: datetime,
    end: datetime,
    uid_prefix: str,
) -> list[CalendarEvent]:
    """Bursts and completed runs that overlap ``start`` (inclusive) to ``end``."""
    start = _aware(start)
    end = _aware(end)
    found = _burst_events(list(days or []), uid_prefix)
    found.extend(_history_events(list(runs or []), uid_prefix))
    found = [event for event in found if _overlaps(event, start, end)]
    found.sort(key=lambda event: (event.start_datetime_local, event.summary))
    return found


def history_runs(coordinator) -> list[dict]:
    """Completed runs stored on each zone, including a last run with no list yet."""
    runs: list[dict] = []
    entry = coordinator.config_entry
    for zone_id, state in coordinator.store.zones.items():
        subentry = entry.subentries.get(zone_id)
        name = subentry.title if subentry is not None else zone_id
        seen: list[dict] = []
        stamps: set[str] = set()
        for item in list(state.get("run_history") or []):
            if isinstance(item, dict) and item.get("at"):
                seen.append(item)
                stamps.add(str(item.get("at")))
        last = state.get("last_run")
        if isinstance(last, dict) and last.get("at") and str(last.get("at")) not in stamps:
            seen.append(last)
        for item in seen:
            runs.append({**item, "zone_id": zone_id, "name": name})
    return runs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the hub watering calendar."""
    async_add_entities([WateringCalendar(entry.runtime_data)])


class WateringCalendar(SmartWaterHubEntity, CalendarEntity):
    """Every planned burst, plus runs that already happened."""

    _attr_translation_key = "watering"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator) -> None:
        """Set the unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_watering_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        """The next burst or a run that is still going."""
        now = dt_util.now()
        upcoming = self._collect(now, now + timedelta(days=366))
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return bursts and completed runs in an arbitrary range."""
        return self._collect(start_date, end_date)

    def _collect(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        data = self.coordinator.data
        days = list(data.schedule_days or []) if data is not None else []
        return watering_events(
            days=days,
            runs=history_runs(self.coordinator),
            start=start,
            end=end,
            uid_prefix=self._attr_unique_id or "watering",
        )
