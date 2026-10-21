"""Steady flow uses the open valve, not the scheduled clock."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant, ServiceRegistry
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.climate_day import HistoryPoint
from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_FLOW_KIND,
    CONF_FLOW_SENSOR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SPRINKLER_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from custom_components.sprinklecast.flow_window import (
    FlowSample,
    baseline_gpm_from_history,
    learn_confirmed,
    middle_updates,
    peak_middle_gpm,
    steady_gpm,
    zone_ready_for_next,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

UTC = timezone.utc


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 21, hour, minute, second, tzinfo=UTC)


def _points(start: datetime, minutes: int, gpm: float) -> list[tuple[datetime, float]]:
    return [
        (start + timedelta(minutes=offset), gpm) for offset in range(minutes + 1)
    ]


def test_open_window_ignores_the_previous_zone_and_the_settle() -> None:
    """Bed's real rate is 2.28. The scheduled average mixed in a zero."""
    opened = datetime(2026, 10, 20, 23, 57, 13, tzinfo=UTC)
    closed = datetime(2026, 10, 21, 0, 12, 15, tzinfo=UTC)
    samples = [
        FlowSample(opened - timedelta(minutes=3), "opening", gpm=0.0),
        FlowSample(opened, "open", gpm=0.4),
        FlowSample(opened + timedelta(minutes=1), "open", gpm=1.1),
    ]
    moment = opened + timedelta(minutes=2)
    while moment <= closed:
        samples.append(FlowSample(moment, "open", gpm=2.28))
        moment += timedelta(minutes=1)
    # The meter falls before the next zone. The valve report is not the edge.
    samples.append(FlowSample(closed + timedelta(seconds=20), "closed", gpm=0.0))
    samples.append(FlowSample(closed + timedelta(minutes=1), "closed", gpm=14.7))
    assert steady_gpm(samples, idle_gpm=0.5) == pytest.approx(2.28)


def test_middle_updates_count_one_slow_meter_reading_once() -> None:
    """A re-poll of the opening reading is not a middle sample."""
    start = datetime(2026, 10, 20, 23, 55, 53, tzinfo=UTC)
    first = start
    second = start + timedelta(seconds=100)
    third = start + timedelta(seconds=120)
    end = start + timedelta(seconds=180)
    samples = [
        FlowSample(start, "closed", gpm=9.5, meter_at=first),
        FlowSample(start + timedelta(seconds=30), "closed", gpm=9.5, meter_at=first),
        # Still the opening reading, polled again after the middle has started.
        FlowSample(start + timedelta(seconds=70), "closed", gpm=9.5, meter_at=first),
        FlowSample(second, "closed", gpm=9.5, meter_at=second),
        FlowSample(second + timedelta(seconds=10), "open", gpm=9.5, meter_at=second),
        FlowSample(third, "open", gpm=9.5, meter_at=third),
        FlowSample(end, "open", gpm=4.0, meter_at=end),
    ]
    assert middle_updates(samples, idle_gpm=0.5) == 2
    assert peak_middle_gpm(samples, idle_gpm=0.5) == pytest.approx(9.5)


def test_next_zone_waits_for_a_closed_valve_and_a_quiet_meter() -> None:
    """Learn flow does not start the next zone on one of those two signals."""
    assert learn_confirmed("closed", 0.0, 0.5) is False
    assert learn_confirmed("opening", 0.1, 0.5) is False
    assert learn_confirmed("closed", 1.2, 0.5) is True
    assert learn_confirmed("open", 0.0, 0.5) is True
    assert zone_ready_for_next("open", 0.0, 0.5) is False
    assert zone_ready_for_next("closing", 0.0, 0.5) is False
    assert zone_ready_for_next("closed", 2.0, 0.5) is False
    assert zone_ready_for_next("closed", 0.2, 0.5) is True
    assert zone_ready_for_next(None, 0.0, 0.5) is True


def test_flow_starts_while_the_valve_entity_still_says_closed() -> None:
    """Bed's water is moving at 23:55:53. The valve entity says open at 23:57:13.

    That open report is cloud polling lag. The peak in the middle of the
    flowing window is the rate, including the part before the entity updates.
    """
    flow_at = datetime(2026, 10, 20, 23, 55, 53, tzinfo=UTC)
    valve_open = datetime(2026, 10, 20, 23, 57, 13, tzinfo=UTC)
    samples = [FlowSample(datetime(2026, 10, 20, 23, 54, 25, tzinfo=UTC), "closed", gpm=0.0)]
    moment = flow_at
    while moment < flow_at + timedelta(seconds=100):
        samples.append(FlowSample(moment, "closed", gpm=9.5))
        moment += timedelta(seconds=30)
    while moment < flow_at + timedelta(minutes=5):
        valve = "open" if moment >= valve_open else "closed"
        samples.append(FlowSample(moment, valve, gpm=4.0))
        moment += timedelta(seconds=30)
    samples.append(FlowSample(moment + timedelta(seconds=30), "open", gpm=0.0))
    assert peak_middle_gpm(samples, idle_gpm=0.5) == pytest.approx(9.5)
    # A window that waited for the valve report would only see 4.0.
    assert steady_gpm(samples, idle_gpm=0.5) == pytest.approx(4.0)


def test_history_keeps_flow_from_before_the_valve_reports_open() -> None:
    """The only high samples are before the valve entity says open."""
    flow_at = datetime(2026, 10, 20, 23, 55, 53, tzinfo=UTC)
    valve_open = datetime(2026, 10, 20, 23, 57, 13, tzinfo=UTC)
    valve_close = datetime(2026, 10, 21, 0, 2, 13, tzinfo=UTC)
    flow = []
    moment = flow_at
    while moment < valve_open:
        flow.append((moment, 9.5))
        moment += timedelta(seconds=30)
    measured = baseline_gpm_from_history(
        flow,
        [(valve_open, "open"), (valve_close, "closed")],
        [],
        finished_at=valve_close,
        minutes=5,
        idle_gpm=0.5,
    )
    assert measured == pytest.approx(9.5)


def test_overlapping_valve_samples_are_left_out() -> None:
    """A minute when the other valve is also open is not this zone's rate."""
    start = datetime(2026, 10, 21, 0, 12, 15, tzinfo=UTC)
    flow = []
    for offset in range(16):
        moment = start + timedelta(minutes=offset)
        flow.append((moment, 99.0 if offset < 10 else 14.7))
    valve = [(start, "open"), (start + timedelta(minutes=15), "closed")]
    other = [[(start, "open"), (start + timedelta(minutes=10), "closed")]]
    measured = baseline_gpm_from_history(
        flow,
        valve,
        other,
        finished_at=start + timedelta(minutes=12),
        minutes=15,
        idle_gpm=0.5,
    )
    assert measured == pytest.approx(14.7)


def test_history_rebuilds_the_live_catch_cup_rates() -> None:
    """The recorded averages mixed neighbors. The open window does not."""
    zones = {
        "bed": (datetime(2026, 10, 20, 23, 57, 13, tzinfo=UTC), 2.28, datetime(2026, 10, 21, 0, 9, 25, tzinfo=UTC)),
        "front": (datetime(2026, 10, 21, 0, 12, 15, tzinfo=UTC), 14.7, datetime(2026, 10, 21, 0, 24, 28, tzinfo=UTC)),
        "left_front": (datetime(2026, 10, 21, 0, 27, 15, tzinfo=UTC), 14.9, datetime(2026, 10, 21, 0, 39, 28, tzinfo=UTC)),
        "left": (datetime(2026, 10, 21, 0, 42, 15, tzinfo=UTC), 13.5, datetime(2026, 10, 21, 0, 54, 28, tzinfo=UTC)),
        "back": (datetime(2026, 10, 21, 0, 57, 15, tzinfo=UTC), 13.3, datetime(2026, 10, 21, 1, 9, 28, tzinfo=UTC)),
        "right": (datetime(2026, 10, 21, 1, 12, 15, tzinfo=UTC), 15.05, datetime(2026, 10, 21, 1, 24, 28, tzinfo=UTC)),
    }
    series: dict[str, list[tuple[datetime, str]]] = {}
    flow: list[tuple[datetime, float]] = []
    for name, (opened, gpm, _finished) in zones.items():
        closed = opened + timedelta(minutes=15, seconds=2)
        series[name] = [(opened, "open"), (closed, "closed")]
        flow.extend(_points(opened + timedelta(minutes=1), 14, gpm))
    for name, (opened, gpm, finished) in zones.items():
        others = [points for other, points in series.items() if other != name]
        measured = baseline_gpm_from_history(
            flow,
            series[name],
            others,
            finished_at=finished,
            minutes=15,
            idle_gpm=0.5,
        )
        assert measured == pytest.approx(gpm)


def _zone(title: str, valve: str, unique_id: str) -> dict:
    return {
        "data": {
            CONF_PLANT_TYPE: "warm_season_turf",
            CONF_SOIL_TYPE: "clay_loam",
            CONF_SLOPE_PCT: 6,
            CONF_SUN_EXPOSURE: "full_sun",
            CONF_ROOT_DEPTH_IN: 6,
            CONF_SPRINKLER_TYPE: "spray",
            CONF_PRECIPITATION_RATE: 1.5,
            CONF_VALVE_ENTITY: valve,
        },
        "subentry_type": "zone",
        "title": title,
        "unique_id": unique_id,
        "subentry_id": unique_id,
    }


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Garden",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_FLOW_SENSOR: "sensor.main_flow",
            CONF_FLOW_KIND: "rate",
        },
        subentries_data=[
            _zone("Bed", "valve.bed", "bed"),
            _zone("Front", "valve.front", "front"),
        ],
    )


def _weather(hass: HomeAssistant) -> None:
    hass.config.latitude = 31.5493
    hass.config.longitude = -97.1467
    hass.config.time_zone = "America/Chicago"
    hass.states.async_set(
        "weather.home",
        "sunny",
        {
            "temperature": 30,
            "temperature_unit": "°C",
            "humidity": 45,
            "wind_speed": 2.0,
            "wind_speed_unit": "m/s",
            "precipitation_unit": "mm",
        },
    )


async def test_a_lagging_valve_is_measured_while_it_is_open(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each zone runs 15 commanded minutes. Flow, not the valve report, is the window."""
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    hass.states.async_set("valve.bed", "closed")
    hass.states.async_set("valve.front", "closed")
    hass.states.async_set("sensor.main_flow", "0", {"unit_of_measurement": "gal/min"})
    clock = {"t": 0.0}
    marks: dict[str, float] = {}
    rates = {"valve.bed": 2.28, "valve.front": 14.7}
    original = ServiceRegistry.async_call

    async def fake(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        data = service_data or {}
        entity = data.get("entity_id")
        if domain == "valve" and entity in rates:
            if service == "open_valve":
                marks[f"open:{entity}"] = clock["t"]
                hass.states.async_set(entity, "opening")
            elif service == "close_valve":
                marks[f"close:{entity}"] = clock["t"]
                hass.states.async_set(entity, "closing")
            return None
        return await original(
            self, domain, service, service_data, blocking, context, target, return_response
        )

    async def pause(seconds: float) -> None:
        clock["t"] += seconds
        flowing = None
        for entity, rate in rates.items():
            state = hass.states.get(entity).state
            opened_at = marks.get(f"open:{entity}")
            closed_at = marks.get(f"close:{entity}")
            # The entity reports open about 168s late. Water is already moving.
            if state == "opening" and opened_at is not None and clock["t"] - opened_at >= 168:
                hass.states.async_set(entity, "open")
                state = "open"
            if state == "closing" and closed_at is not None and clock["t"] - closed_at >= 180:
                hass.states.async_set(entity, "closed")
                state = "closed"
            # Meter rises 90s after the command, before the valve report,
            # and falls 30s after the close command.
            if opened_at is not None and clock["t"] - opened_at >= 90:
                if closed_at is None or clock["t"] - closed_at < 30:
                    flowing = rate
        hass.states.async_set(
            "sensor.main_flow",
            "0" if flowing is None else str(flowing),
            {"unit_of_measurement": "gal/min"},
        )

    monkeypatch.setattr(ServiceRegistry, "async_call", fake)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.executor._pause = pause
    await hass.services.async_call(
        DOMAIN, "run_catch_cup_test", {"minutes": 15}, blocking=True
    )
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    await hass.async_block_till_done()
    assert entry.runtime_data.store.zone("bed")["baseline_gpm"] is None
    assert entry.runtime_data.store.zone("front")["baseline_gpm"] is None
    # Open time, not the three minutes spent waiting for the valve.
    assert entry.runtime_data.store.zone("bed")["catch_cup_pending"]["minutes"] == pytest.approx(
        15
    )
    assert entry.runtime_data.store.zone("bed")["last_run"]["net_mm"] > 0
    assert entry.runtime_data.store.zone("front")["last_run"]["net_mm"] > 0


async def test_learn_flow_starts_when_flow_rises_and_waits_for_two_samples(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """60 seconds starts at the meter, and a once-a-minute meter extends the run."""
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    hass.states.async_set("valve.bed", "closed")
    hass.states.async_set("sensor.main_flow", "0", {"unit_of_measurement": "gal/min"})
    clock = {"t": 0.0}
    marks: dict[str, float] = {}
    published: dict[str, int | None] = {"bucket": None}
    started = time.time()
    seen: list[tuple[str, str | None, str | None]] = []
    original = ServiceRegistry.async_call

    async def fake(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        data = service_data or {}
        entity = data.get("entity_id")
        if domain == "valve" and entity == "valve.bed":
            if service == "open_valve":
                marks["open"] = clock["t"]
                marks.pop("close", None)
                hass.states.async_set(entity, "closed")
            elif service == "close_valve":
                marks["close"] = clock["t"]
                hass.states.async_set(entity, "closed")
            return None
        return await original(
            self, domain, service, service_data, blocking, context, target, return_response
        )

    async def pause(seconds: float) -> None:
        clock["t"] += seconds
        opened = marks.get("open")
        closed = marks.get("close")
        # The valve entity reports open late. Flow is already moving.
        if opened is not None and closed is None and clock["t"] - opened >= 170:
            hass.states.async_set("valve.bed", "open")
        bucket = int(clock["t"] // 60)
        if closed is not None or opened is None or bucket <= 0:
            rate = 0.0
        elif bucket >= 5:
            rate = 4.0
        else:
            rate = 9.5
        if closed is not None or published["bucket"] != bucket:
            # Same gallons per minute still has to be a new meter timestamp.
            hass.states.async_set(
                "sensor.main_flow",
                str(rate),
                {"unit_of_measurement": "gal/min"},
                force_update=True,
                timestamp=started + clock["t"],
            )
            published["bucket"] = None if closed is not None else bucket
        now = hass.states.get("sensor.garden_watering_now")
        if now is not None:
            seen.append((now.state, now.attributes.get("status"), now.attributes.get("zone")))

    monkeypatch.setattr(ServiceRegistry, "async_call", fake)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("button", DOMAIN, f"{entry.entry_id}_learn_flow")
    entry.runtime_data.executor._pause = pause
    await hass.services.async_call(
        DOMAIN, "learn_flow_rates", {"zone": "Bed"}, blocking=True
    )
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    await hass.async_block_till_done()
    zone = entry.runtime_data.store.zone("bed")
    assert zone["baseline_gpm"] == pytest.approx(9.5)
    assert zone["baseline_source"] == "flow_learning"
    # A minute with the meter still at zero, then three minutes of measurement.
    assert zone["last_run"]["minutes"] == pytest.approx(3, abs=0.1)
    assert marks["close"] - marks["open"] == pytest.approx(240, abs=5)
    assert ("Learning flow rates", "Waiting for flow", "Bed") in seen
    assert ("Learning flow rates", "Measuring", "Bed") in seen
    assert hass.states.get("sensor.garden_watering_now").state != "Learning flow rates"


async def test_learn_flow_waits_until_the_previous_zone_is_quiet(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Front stays off while Bed's valve still says open and the meter is up."""
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    hass.states.async_set("valve.bed", "closed")
    hass.states.async_set("valve.front", "closed")
    hass.states.async_set("sensor.main_flow", "0", {"unit_of_measurement": "gal/min"})
    clock = {"t": 0.0}
    started = time.time()
    active: dict[str, str | None] = {"entity": None}
    close_at: dict[str, float] = {}
    pending_close: dict[str, float] = {}
    opens: list[tuple[str, float, str, str]] = []
    published: dict[str, object] = {"bucket": None, "entity": None}
    original = ServiceRegistry.async_call

    def publish(rate: float, bucket: int | None, entity: str | None) -> None:
        if published["bucket"] == bucket and published["entity"] == entity:
            return
        hass.states.async_set(
            "sensor.main_flow",
            str(rate),
            {"unit_of_measurement": "gal/min"},
            force_update=True,
            timestamp=started + clock["t"],
        )
        published["bucket"] = bucket
        published["entity"] = entity

    async def fake(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        data = service_data or {}
        entity = data.get("entity_id")
        if domain == "valve" and entity in {"valve.bed", "valve.front"}:
            if service == "open_valve":
                bed = hass.states.get("valve.bed")
                flow = hass.states.get("sensor.main_flow")
                opens.append(
                    (
                        entity,
                        clock["t"],
                        "closed" if bed is None else bed.state,
                        "0" if flow is None else flow.state,
                    )
                )
                active["entity"] = entity
                pending_close.pop(entity, None)
                hass.states.async_set(entity, "open")
                publish(8.0, int(clock["t"] // 60), entity)
            elif service == "close_valve":
                close_at[entity] = clock["t"]
                pending_close[entity] = clock["t"]
                active["entity"] = None
            return None
        return await original(
            self, domain, service, service_data, blocking, context, target, return_response
        )

    async def pause(seconds: float) -> None:
        clock["t"] += seconds
        for entity, requested in list(pending_close.items()):
            if clock["t"] - requested < 60:
                continue
            hass.states.async_set(entity, "closed")
            publish(0.0, None, None)
            pending_close.pop(entity, None)
            return
        running = active["entity"]
        if running is not None:
            publish(8.0, int(clock["t"] // 60), running)

    monkeypatch.setattr(ServiceRegistry, "async_call", fake)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.executor._pause = pause
    await hass.services.async_call(
        DOMAIN,
        "learn_flow_rates",
        {"zone": ["Bed", "Front"]},
        blocking=True,
    )
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    await hass.async_block_till_done()
    front_open = next(item for item in opens if item[0] == "valve.front")
    assert front_open[1] >= close_at["valve.bed"] + 59
    assert front_open[2] == "closed"
    assert float(front_open[3]) == pytest.approx(0.0)
    for zone_id in ("bed", "front"):
        zone = entry.runtime_data.store.zone(zone_id)
        assert zone["baseline_gpm"] == pytest.approx(8.0)
        assert zone["baseline_source"] == "flow_learning"


async def test_learn_flow_fails_when_no_flow_is_seen(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    hass.states.async_set("valve.bed", "closed")
    hass.states.async_set("sensor.main_flow", "0", {"unit_of_measurement": "gal/min"})
    original = ServiceRegistry.async_call

    async def fake(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        data = service_data or {}
        if domain == "valve" and data.get("entity_id") == "valve.bed":
            hass.states.async_set("valve.bed", "closed")
            return None
        return await original(
            self, domain, service, service_data, blocking, context, target, return_response
        )

    async def pause(_seconds: float) -> None:
        return None

    monkeypatch.setattr(ServiceRegistry, "async_call", fake)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.executor._pause = pause
    await hass.services.async_call(
        DOMAIN, "learn_flow_rates", {"zone": "Bed"}, blocking=True
    )
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    await hass.async_block_till_done()
    zone = entry.runtime_data.store.zone("bed")
    assert zone.get("baseline_gpm") is None
    assert "No flow was seen for Bed" in zone["last_run"]["result"]


async def test_stop_all_cancels_learn_flow_and_a_second_press_is_ignored(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    hass.states.async_set("valve.bed", "closed")
    hass.states.async_set("sensor.main_flow", "0", {"unit_of_measurement": "gal/min"})
    opens: list[str] = []
    gate = asyncio.Event()
    original = ServiceRegistry.async_call

    async def fake(
        self,
        domain,
        service,
        service_data=None,
        blocking=False,
        context=None,
        target=None,
        return_response=False,
    ):
        data = service_data or {}
        entity = data.get("entity_id")
        if domain == "valve" and entity == "valve.bed":
            if service == "open_valve":
                opens.append(entity)
                hass.states.async_set(entity, "closed")
            elif service == "close_valve":
                hass.states.async_set(entity, "closed")
            return None
        return await original(
            self, domain, service, service_data, blocking, context, target, return_response
        )

    async def pause(_seconds: float) -> None:
        await gate.wait()

    monkeypatch.setattr(ServiceRegistry, "async_call", fake)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    entry.runtime_data.executor._pause = pause
    await hass.services.async_call(
        DOMAIN, "learn_flow_rates", {"zone": "Bed"}, blocking=True
    )
    for _ in range(20):
        await hass.async_block_till_done()
        if hass.states.get("sensor.garden_watering_now").state == "Learning flow rates":
            break
    assert hass.states.get("sensor.garden_watering_now").state == "Learning flow rates"
    assert hass.states.get("sensor.garden_watering_now").attributes["zone"] == "Bed"
    await hass.services.async_call(
        DOMAIN, "learn_flow_rates", {"zone": "Bed"}, blocking=True
    )
    assert opens == ["valve.bed"]
    await hass.services.async_call(DOMAIN, "stop_all", {}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get("valve.bed").state == "closed"
    assert entry.runtime_data.store.zone("bed").get("baseline_gpm") is None
    assert hass.states.get("sensor.garden_watering_now").state != "Learning flow rates"
    gate.set()


def _point(moment: datetime, state: str, unit: str | None = None) -> HistoryPoint:
    return HistoryPoint(at=moment, state=state, unit=unit, attributes={})


async def test_upgrade_rebuilds_a_catch_cup_baseline_from_history(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    opened = datetime(2026, 10, 21, 0, 12, 15, tzinfo=UTC)
    finished = datetime(2026, 10, 21, 0, 24, 28, tzinfo=UTC)
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    await store.async_save(
        {
            "zones": {
                "front": {
                    "deficit_mm": 12.0,
                    "baseline_gpm": 8.585,
                    "baseline_gpm_at": finished.isoformat(),
                    "baseline_source": "catch_cup",
                    "last_run_gpm": 8.585,
                    "flow_history": [
                        {"at": finished.isoformat(), "gpm": 8.585, "minutes": 15}
                    ],
                },
                "bed": {
                    "deficit_mm": 4.0,
                    "baseline_gpm": 1.135,
                    "baseline_gpm_at": datetime(2026, 10, 21, 0, 9, 25, tzinfo=UTC).isoformat(),
                    "baseline_source": "catch_cup",
                    "last_run_gpm": 1.135,
                    "flow_history": [
                        {
                            "at": datetime(2026, 10, 21, 0, 9, 25, tzinfo=UTC).isoformat(),
                            "gpm": 1.135,
                            "minutes": 15,
                        }
                    ],
                },
            }
        }
    )
    bed_open = datetime(2026, 10, 20, 23, 57, 13, tzinfo=UTC)
    bed_close = datetime(2026, 10, 21, 0, 12, 15, tzinfo=UTC)

    async def history(_hass, _entities, _start, _end):
        flow = []
        moment = bed_open
        while moment <= bed_close:
            flow.append(_point(moment, "2.28", "gal/min"))
            moment += timedelta(minutes=1)
        moment = opened + timedelta(minutes=1)
        while moment <= opened + timedelta(minutes=15):
            flow.append(_point(moment, "14.7", "gal/min"))
            moment += timedelta(minutes=1)
        return {
            "sensor.main_flow": flow,
            "valve.bed": [
                _point(bed_open, "open"),
                _point(bed_close, "closed"),
            ],
            "valve.front": [
                _point(opened, "open"),
                _point(opened + timedelta(minutes=15), "closed"),
            ],
        }

    monkeypatch.setattr(
        "custom_components.sprinklecast.coordinator.climate_day.async_entity_histories",
        history,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    zones = entry.runtime_data.store.zones
    assert zones["bed"]["baseline_gpm"] == pytest.approx(2.28)
    assert zones["front"]["baseline_gpm"] == pytest.approx(14.7)
    assert zones["bed"]["baseline_window"] == "steady"
    assert zones["front"]["flow_history"] == []
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"catch_cup_baseline_{entry.entry_id}")
        is None
    )


async def test_missing_history_leaves_the_baseline_and_asks_for_a_retest(
    hass: HomeAssistant,
) -> None:
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    finished = datetime(2026, 10, 21, 0, 24, 28, tzinfo=UTC)
    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
    await store.async_save(
        {
            "zones": {
                "front": {
                    "deficit_mm": 12.0,
                    "baseline_gpm": 8.585,
                    "baseline_gpm_at": finished.isoformat(),
                    "baseline_source": "catch_cup",
                    "last_run_gpm": 8.585,
                }
            }
        }
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.store.zone("front")["baseline_gpm"] == pytest.approx(8.585)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"catch_cup_baseline_{entry.entry_id}"
    )
    assert issue is not None
    assert "left as they are" in issue.translation_placeholders["detail"]
