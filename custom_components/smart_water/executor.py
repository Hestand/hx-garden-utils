"""Turn zone on/off entities on and off, one at a time.

Services are the generic Home Assistant ones: ``switch.turn_on`` /
``turn_off``, ``valve.open_valve`` / ``close_valve``, and
``input_boolean.turn_on`` / ``turn_off``. Hydrawise is never called.
Each command is confirmed against the entity state and retried. A cycle's
``finally`` turns the entity off, including when the task is cancelled.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .flow import GALLONS_PER_INCH_SQFT
from .units import MM_PER_INCH, rate_gpm, volume_gallons

_LOGGER = logging.getLogger(__name__)

# domain -> (on service, off service, on state, off state)
_CONTROL = {
    "switch": ("turn_on", "turn_off", "on", "off"),
    "input_boolean": ("turn_on", "turn_off", "on", "off"),
    "valve": ("open_valve", "close_valve", "open", "closed"),
}
_ON_STATES = {
    "switch": {"on"},
    "input_boolean": {"on"},
    "valve": {"open", "opening"},
}
_OFF_STATES = {
    "switch": {"off"},
    "input_boolean": {"off"},
    "valve": {"closed", "closing"},
}
_ATTEMPTS = 3


@dataclass
class CycleJob:
    """One on-interval for a single zone."""

    zone_id: str
    name: str
    entity_id: str
    start: datetime | None
    minutes: float
    net_mm: float
    zone_net_mm: float
    precip_in_hr: float
    efficiency: float
    area_sqft: float | None
    flow_entity: str | None
    flow_kind: str | None
    finish_by: datetime | None
    marked_at: datetime
    soak_after_min: float = 0.0
    manual: bool = False
    zone_cap_min: float | None = None


class WateringExecutor:
    """Run cycle jobs sequentially. Only one entity is on at a time."""

    def __init__(self, hass: HomeAssistant, store: Any) -> None:
        """Bind Home Assistant and the hub store. Callbacks are set by the coordinator."""
        self.hass = hass
        self.store = store
        self._sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self._task: asyncio.Task[None] | None = None
        self.current_zone_id: str | None = None
        self.current_name: str | None = None
        self.skip_checker: Callable[[str, bool], str | None] | None = None
        self.rain_since: Callable[[datetime], float] | None = None
        self.on_cycle_done: Callable[..., Awaitable[None]] | None = None
        self.on_status: Callable[[], None] | None = None
        self.hub_cap_fn: Callable[[], float | None] | None = None

    async def async_quiesce(self) -> None:
        """Turn off the entity this hub left on, if it recorded one."""
        entity_id = self.store.watering_entity
        if not entity_id:
            return
        await self._turn(str(entity_id), on=False)
        self.store.watering_entity = None
        self.current_zone_id = None
        self.current_name = None
        await self.store.async_save()

    async def stop(self) -> None:
        """Cancel the running sequence and force every recorded entity off."""
        task = self._task
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            await asyncio.wait({task})
        self._task = None
        await self.async_quiesce()
        self._poke()

    async def start(self, jobs: list[CycleJob]) -> None:
        """Replace any running sequence with ``jobs``."""
        await self.stop()
        if not jobs:
            return
        self._task = asyncio.create_task(self._run(jobs))

    async def _run(self, jobs: list[CycleJob]) -> None:
        hub_cap = self._hub_cap()
        hub_used = 0.0
        zone_used: dict[str, float] = {}
        scales: dict[str, float] = {}
        try:
            for index, job in enumerate(jobs):
                scale = scales.get(job.zone_id)
                if scale is None:
                    scale = self._rain_scale(job)
                    scales[job.zone_id] = scale
                if scale <= 0:
                    await self._report(job, 0.0, 0.0, None, "Skipped because rain fell after the plan.")
                    continue
                minutes = job.minutes * scale
                net_mm = job.net_mm * scale
                if job.start is not None:
                    delay = (job.start - self._now(job.start)).total_seconds()
                    if delay > 0:
                        await self._sleep(delay)
                skip = None
                if self.skip_checker is not None:
                    skip = self.skip_checker(job.zone_id, job.manual)
                if skip:
                    await self._report(job, 0.0, 0.0, None, skip)
                    continue
                if job.finish_by is not None:
                    remaining = (job.finish_by - self._now(job.finish_by)).total_seconds() / 60.0
                    if remaining <= 0:
                        await self._report(job, 0.0, 0.0, None, "The watering window is closed.")
                        continue
                    if minutes > remaining:
                        net_mm *= remaining / minutes
                        minutes = remaining
                zone_before = zone_used.get(job.zone_id, 0.0)
                room = minutes
                if job.zone_cap_min is not None:
                    room = min(room, job.zone_cap_min - zone_before)
                if hub_cap is not None:
                    room = min(room, hub_cap - hub_used)
                if room < 0.5:
                    hub_left = None if hub_cap is None else hub_cap - hub_used
                    zone_left = (
                        None
                        if job.zone_cap_min is None
                        else job.zone_cap_min - zone_before
                    )
                    if hub_left is not None and hub_left < 0.5:
                        await self._report(
                            job, 0.0, 0.0, None, "Run reached the nightly maximum runtime."
                        )
                        break
                    if zone_left is not None and zone_left < 0.5:
                        await self._report(
                            job, 0.0, 0.0, None, "Run reached this zone's maximum runtime."
                        )
                        continue
                    await self._report(
                        job, 0.0, 0.0, None, "Remaining runtime is under half a minute."
                    )
                    continue
                if minutes > room:
                    net_mm *= room / minutes
                    minutes = room
                turned_on = await self._turn(job.entity_id, on=True)
                if not turned_on:
                    await self._report(
                        job, 0.0, 0.0, None, f"Could not turn on {job.entity_id}."
                    )
                    continue
                self.store.watering_entity = job.entity_id
                self.current_zone_id = job.zone_id
                self.current_name = job.name
                await self.store.async_save()
                self._poke()
                flow_before = self._flow_gallons(job)
                gpm_before = self._flow_gpm(job)
                try:
                    await self._sleep(minutes * 60.0)
                finally:
                    await self._turn(job.entity_id, on=False)
                    if self.store.watering_entity == job.entity_id:
                        self.store.watering_entity = None
                    self.current_zone_id = None
                    self.current_name = None
                    await self.store.async_save()
                    self._poke()
                hub_used += minutes
                zone_used[job.zone_id] = zone_before + minutes
                flow_after = self._flow_gallons(job)
                gallons = None
                gpm = None
                if flow_before is not None and flow_after is not None and flow_after > flow_before:
                    gallons = flow_after - flow_before
                    if minutes > 0:
                        gpm = gallons / minutes
                else:
                    gpm_after = self._flow_gpm(job)
                    pair = [value for value in (gpm_before, gpm_after) if value is not None]
                    if pair:
                        gpm = sum(pair) / len(pair)
                        gallons = gpm * minutes
                credited = self._credited_mm(job, minutes, net_mm, gallons)
                await self._report(job, minutes, credited, gallons, "ok", gpm)
                if job.soak_after_min > 0 and index < len(jobs) - 1:
                    await self._sleep(job.soak_after_min * 60.0)
        except asyncio.CancelledError:
            entity_id = self.store.watering_entity
            if entity_id:
                await self._turn(str(entity_id), on=False)
                self.store.watering_entity = None
                await self.store.async_save()
            self.current_zone_id = None
            self.current_name = None
            self._poke()
            raise

    def _hub_cap(self) -> float | None:
        """All-zones valve budget for this sequence. None means no hub total."""
        if self.hub_cap_fn is None:
            return None
        value = self.hub_cap_fn()
        if value is None:
            return None
        return max(0.0, float(value))

    def _now(self, reference: datetime) -> datetime:
        if reference.tzinfo is None:
            return datetime.now()
        return dt_util.now(reference.tzinfo)

    def _rain_scale(self, job: CycleJob) -> float:
        if self.rain_since is None or job.zone_net_mm <= 0:
            return 1.0
        rain = max(0.0, self.rain_since(job.marked_at))
        remaining = job.zone_net_mm - rain
        if remaining <= 0:
            return 0.0
        return remaining / job.zone_net_mm

    def _flow_gallons(self, job: CycleJob) -> float | None:
        if not job.flow_entity or job.flow_kind != "total":
            return None
        state = self.hass.states.get(job.flow_entity)
        if state is None or state.state in {"unknown", "unavailable", "none", ""}:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = state.attributes.get("unit_of_measurement")
        return volume_gallons(value, unit)

    def _flow_gpm(self, job: CycleJob) -> float | None:
        """Instantaneous gal/min when the flow entity is a rate."""
        if not job.flow_entity or job.flow_kind != "rate":
            return None
        state = self.hass.states.get(job.flow_entity)
        if state is None or state.state in {"unknown", "unavailable", "none", ""}:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = state.attributes.get("unit_of_measurement")
        try:
            return rate_gpm(value, unit)
        except (TypeError, ValueError):
            return None

    def _credited_mm(
        self,
        job: CycleJob,
        minutes: float,
        planned_net_mm: float,
        gallons: float | None,
    ) -> float:
        if (
            gallons is not None
            and gallons > 0
            and job.area_sqft
            and job.area_sqft > 0
        ):
            gross_in = gallons / (job.area_sqft * GALLONS_PER_INCH_SQFT)
            return gross_in * job.efficiency * MM_PER_INCH
        if job.precip_in_hr > 0 and job.efficiency > 0 and minutes > 0:
            inches = (minutes / 60.0) * job.precip_in_hr * job.efficiency
            return inches * MM_PER_INCH
        return planned_net_mm

    async def _report(
        self,
        job: CycleJob,
        minutes: float,
        net_mm: float,
        gallons: float | None,
        result: str,
        gpm: float | None = None,
    ) -> None:
        if self.on_cycle_done is None:
            return
        await self.on_cycle_done(
            zone_id=job.zone_id,
            minutes=minutes,
            net_mm=net_mm,
            gallons=gallons,
            result=result,
            gpm=gpm,
        )

    def _poke(self) -> None:
        if self.on_status is not None:
            self.on_status()

    async def _turn(self, entity_id: str, *, on: bool) -> bool:
        domain = entity_id.split(".", 1)[0]
        spec = _CONTROL.get(domain)
        if spec is None:
            _LOGGER.error(
                "Smart Water will not call %s; only switch, valve, and input_boolean",
                entity_id,
            )
            return False
        service = spec[0] if on else spec[1]
        wanted = _ON_STATES[domain] if on else _OFF_STATES[domain]
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": entity_id},
                    blocking=True,
                )
            except Exception as err:  # noqa: BLE001 - a failed command is logged and retried
                _LOGGER.error(
                    "Smart Water %s.%s failed for %s: %s", domain, service, entity_id, err
                )
            state = self.hass.states.get(entity_id)
            if state is not None and state.state in wanted:
                return True
            _LOGGER.warning(
                "Smart Water expected %s to be %s after %s (attempt %s of %s, state %s)",
                entity_id,
                "on" if on else "off",
                service,
                attempt,
                _ATTEMPTS,
                None if state is None else state.state,
            )
            if attempt < _ATTEMPTS:
                await self._sleep(1)
        _LOGGER.error("Smart Water could not confirm %s changed", entity_id)
        return False
