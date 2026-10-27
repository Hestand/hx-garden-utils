"""Config-entry diagnostics.

The watering-schedule sensor keeps a short attribute list so the recorder
can store it. The reasons, cycle times, and markdown table are here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import SmartWaterConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: SmartWaterConfigEntry,
) -> dict[str, Any]:
    """Return the schedule detail that is no longer a sensor attribute."""
    _ = hass
    coordinator = entry.runtime_data
    data = coordinator.data
    titles = {
        subentry.subentry_id: subentry.title
        for subentry in entry.subentries.values()
    }
    if data is None:
        return {"schedule": {"window": "", "markdown": "", "days": []}, "zones": []}
    zones: list[dict[str, Any]] = []
    for zone_id, zone in data.zones.items():
        zones.append(
            {
                "zone_id": zone_id,
                "name": titles.get(zone_id, zone_id),
                "reason": zone.reason,
                "next_note": zone.next_note,
                "scheduled": zone.scheduled,
                "runtime_min": zone.runtime_min,
                "next_run": None if zone.next_run is None else zone.next_run.isoformat(),
                "root_depth_in": zone.root_depth_in,
                "root_depth_source": zone.root_depth_source,
                "bucket_in": zone.bucket_in,
                "water_next_chance": zone.water_next_chance,
            }
        )
    return {
        "schedule": {
            "window": data.schedule_window,
            "summary": data.outlook_summary,
            "markdown": data.schedule_markdown,
            "days": list(data.schedule_days or []),
            "water_next_chance": data.water_next_chance,
        },
        "zones": zones,
    }
