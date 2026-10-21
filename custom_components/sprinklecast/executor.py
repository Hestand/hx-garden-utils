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
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .flow import GALLONS_PER_INCH_SQFT
from .flow_learn import DEFAULT_IDLE_GPM
from .flow_window import (
    SAMPLE_SECONDS,
    VALVE_WAIT_TIMEOUT_SECONDS,
    FlowSample,
    steady_gpm,
    zone_is_flowing,
    zone_is_quiet,
)
from .schedule import elapsed_seconds
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
    credit_bucket: bool = True
    uncapped: bool = False
    catch_cup: bool = False


class WateringExecutor:
    """Run cycle jobs sequentially. Only one entity is on at a time."""

    def __init__(self, hass: HomeAssistant, store: Any) -> None:
        """Bind Home Assistant and the hub store. Callbacks are set by the coordinator."""
        self.hass = hass
        self.store = store
        # Tests replace ``_pause``. ``_sleep`` counts the time on the run clock.
        self._pause: Callable[[float], Awaitable[None]] = asyncio.sleep
        self._task: asyncio.Task[None] | None = None
        self._catch_cup_active = False
        self._run_token = 0
        self._clock_base = dt_util.utcnow()
        self._clock_seconds = 0.0
        self.current_zone_id: str | None = None
        self.current_name: str | None = None
        self.idle_gpm_fn: Callable[[], float] | None = None
        self.skip_checker: Callable[[str, bool], str | None] | None = None
        self.rain_since: Callable[[datetime], float] | None = None
        self.on_cycle_done: Callable[..., Awaitable[None]] | None = None
        self.on_sequence_done: Callable[[], Awaitable[None]] | None = None
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
        """Replace any running sequence with ``jobs``.

        A catch-cup test that is already running ignores another press. That
        press used to stop the test and start it again.
        """
        catch_cup = bool(jobs) and all(job.catch_cup for job in jobs)
        if catch_cup and self._catch_cup_active:
            _LOGGER.info(
                "Catch-cup test is already running; ignoring another press"
            )
            return
        # Bump the token before stop() so the cancelled run does not clear
        # the flag this press just set.
        if catch_cup:
            self._run_token += 1
            self._catch_cup_active = True
        token = self._run_token
        await self.stop()
        if not jobs:
            if catch_cup:
                self._catch_cup_active = False
            return
        if not catch_cup:
            self._run_token += 1
            token = self._run_token
        self._clock_base = dt_util.utcnow()
        self._clock_seconds = 0.0
        self._task = asyncio.create_task(self._run(jobs, token))

    async def _run(self, jobs: list[CycleJob], token: int) -> None:
        hub_cap = self._hub_cap()
        hub_used = 0.0
        zone_used: dict[str, float] = {}
        scales: dict[str, float] = {}
        try:
            await self._run_jobs(jobs, hub_cap, hub_used, zone_used, scales)
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
        finally:
            if token == self._run_token:
                self._catch_cup_active = False
            self._sequence_finished()

    async def _run_jobs(
        self,
        jobs: list[CycleJob],
        hub_cap: float | None,
        hub_used: float,
        zone_used: dict[str, float],
        scales: dict[str, float],
    ) -> None:
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
                delay = elapsed_seconds(job.start, self._now(job.start))
                if delay > 0:
                    await self._sleep(delay)
            skip = None
            if self.skip_checker is not None:
                skip = self.skip_checker(job.zone_id, job.manual)
            if skip:
                await self._report(job, 0.0, 0.0, None, skip)
                continue
            if job.finish_by is not None:
                remaining = elapsed_seconds(job.finish_by, self._now(job.finish_by)) / 60.0
                if remaining <= 0:
                    await self._report(job, 0.0, 0.0, None, "The watering window is closed.")
                    continue
                if minutes > remaining:
                    net_mm *= remaining / minutes
                    minutes = remaining
            zone_before = zone_used.get(job.zone_id, 0.0)
            if not job.uncapped:
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
            samples: list[FlowSample] = []
            try:
                opened = await self._wait_until_flowing(job, samples)
                open_minutes = 0.0
                if opened:
                    open_minutes = await self._hold_open(job, minutes, samples)
            finally:
                await self._turn(job.entity_id, on=False)
                if self.store.watering_entity == job.entity_id:
                    self.store.watering_entity = None
                self.current_zone_id = None
                self.current_name = None
                await self.store.async_save()
                self._poke()
            # The valve can stay open, and the meter can stay up, after the
            # command. Those samples still belong to this zone. The next zone
            # waits until both have finished.
            await self._wait_until_quiet(job, samples)
            if open_minutes <= 0:
                await self._report(
                    job, 0.0, 0.0, None, f"Valve {job.entity_id} did not open."
                )
                continue
            hub_used += open_minutes
            zone_used[job.zone_id] = zone_before + open_minutes
            gpm = steady_gpm(samples, idle_gpm=self._idle_gpm())
            gallons = None if gpm is None else gpm * open_minutes
            if job.catch_cup:
                credited = self._rate_mm(job, open_minutes)
            else:
                share = open_minutes / minutes if minutes else 1.0
                credited = self._credited_mm(job, open_minutes, net_mm * share, gallons)
            await self._report(job, open_minutes, credited, gallons, "ok", gpm)
            if job.soak_after_min > 0 and index < len(jobs) - 1:
                await self._sleep(job.soak_after_min * 60.0)

    async def _sleep(self, seconds: float) -> None:
        """Pause, and move the run clock by the same amount.

        The wall clock does not move in tests. The run clock does, so a
        sample taken after a pause is later than the one before it.
        """
        await self._pause(seconds)
        self._clock_seconds += max(0.0, float(seconds))

    def _clock(self) -> datetime:
        return self._clock_base + timedelta(seconds=self._clock_seconds)

    def _idle_gpm(self) -> float:
        if self.idle_gpm_fn is None:
            return DEFAULT_IDLE_GPM
        try:
            return max(0.0, float(self.idle_gpm_fn()))
        except (TypeError, ValueError):
            return DEFAULT_IDLE_GPM

    def _take_sample(self, job: CycleJob) -> FlowSample:
        state = self.hass.states.get(job.entity_id)
        valve = None if state is None else state.state
        return FlowSample(
            at=self._clock(),
            valve=valve,
            gpm=self._flow_gpm(job),
            gallons=self._flow_gallons(job),
        )

    async def _wait_until_flowing(self, job: CycleJob, samples: list[FlowSample]) -> bool:
        """Wait until this valve is open, or the meter rises while the valve is unknown."""
        waited = 0.0
        while True:
            sample = self._take_sample(job)
            samples.append(sample)
            if zone_is_flowing(sample.valve, sample.gpm, self._idle_gpm()):
                return True
            if waited >= VALVE_WAIT_TIMEOUT_SECONDS:
                return False
            step = min(SAMPLE_SECONDS, VALVE_WAIT_TIMEOUT_SECONDS - waited)
            await self._sleep(step)
            waited += step

    async def _hold_open(
        self, job: CycleJob, minutes: float, samples: list[FlowSample]
    ) -> float:
        """Keep the valve commanded on for ``minutes`` of actual open time."""
        open_seconds = 0.0
        target = max(0.0, minutes) * 60.0
        idle = self._idle_gpm()
        while open_seconds < target - 0.25:
            step = min(SAMPLE_SECONDS, target - open_seconds)
            await self._sleep(step)
            sample = self._take_sample(job)
            samples.append(sample)
            if zone_is_flowing(sample.valve, sample.gpm, idle):
                open_seconds += step
                continue
            if sample.valve in {"closed", "off"}:
                break
        return open_seconds / 60.0

    async def _wait_until_quiet(self, job: CycleJob, samples: list[FlowSample]) -> None:
        """Wait until this valve is shut and the meter is near zero."""
        waited = 0.0
        idle = self._idle_gpm()
        while waited <= VALVE_WAIT_TIMEOUT_SECONDS:
            sample = self._take_sample(job)
            samples.append(sample)
            if zone_is_quiet(sample.valve, sample.gpm, idle):
                return
            if waited >= VALVE_WAIT_TIMEOUT_SECONDS:
                return
            step = min(SAMPLE_SECONDS, VALVE_WAIT_TIMEOUT_SECONDS - waited)
            await self._sleep(step)
            waited += step

    def _rate_mm(self, job: CycleJob, minutes: float) -> float:
        """Net depth from the zone's current precipitation rate."""
        if job.precip_in_hr <= 0 or job.efficiency <= 0 or minutes <= 0:
            return 0.0
        inches = (minutes / 60.0) * job.precip_in_hr * job.efficiency
        return inches * MM_PER_INCH

    def _sequence_finished(self) -> None:
        """Tell the coordinator the sequence ended, including after a cancel."""
        callback = self.on_sequence_done
        if callback is None:
            return
        self.hass.async_create_task(self._call_sequence_done(callback))

    async def _call_sequence_done(
        self, callback: Callable[[], Awaitable[None]]
    ) -> None:
        try:
            await callback()
        except Exception:  # noqa: BLE001 - a reminder must not break the next run
            _LOGGER.exception("Sprinklecast could not finish the watering sequence")

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
        if not job.credit_bucket:
            return 0.0
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
            catch_cup=job.catch_cup,
        )

    def _poke(self) -> None:
        if self.on_status is not None:
            self.on_status()

    async def _turn(self, entity_id: str, *, on: bool) -> bool:
        domain = entity_id.split(".", 1)[0]
        spec = _CONTROL.get(domain)
        if spec is None:
            _LOGGER.error(
                "Sprinklecast will not call %s; only switch, valve, and input_boolean",
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
                    "Sprinklecast %s.%s failed for %s: %s", domain, service, entity_id, err
                )
            state = self.hass.states.get(entity_id)
            if state is not None and state.state in wanted:
                return True
            _LOGGER.warning(
                "Sprinklecast expected %s to be %s after %s (attempt %s of %s, state %s)",
                entity_id,
                "on" if on else "off",
                service,
                attempt,
                _ATTEMPTS,
                None if state is None else state.state,
            )
            if attempt < _ATTEMPTS:
                await self._sleep(1)
        _LOGGER.error("Sprinklecast could not confirm %s changed", entity_id)
        return False
