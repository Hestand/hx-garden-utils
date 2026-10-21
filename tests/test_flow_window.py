"""Steady flow uses the open valve, not the scheduled clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant, ServiceRegistry
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
    peak_middle_gpm,
    steady_gpm,
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
    assert entry.runtime_data.store.zone("bed")["baseline_gpm"] == pytest.approx(2.28)
    assert entry.runtime_data.store.zone("front")["baseline_gpm"] == pytest.approx(14.7)
    # Open time, not the three minutes spent waiting for the valve.
    assert entry.runtime_data.store.zone("bed")["catch_cup_pending"]["minutes"] == pytest.approx(
        15
    )
    assert entry.runtime_data.store.zone("bed")["last_run"]["net_mm"] > 0
    assert entry.runtime_data.store.zone("front")["last_run"]["net_mm"] > 0


async def test_learn_flow_uses_five_minutes_and_the_middle_peak(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default learn-flow is 5 minutes. The peak is before the valve says open."""
    _weather(hass)
    entry = _entry()
    entry.add_to_hass(hass)
    hass.states.async_set("valve.bed", "closed")
    hass.states.async_set("sensor.main_flow", "0", {"unit_of_measurement": "gal/min"})
    clock = {"t": 0.0}
    marks: dict[str, float] = {}
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
        # Valve entity flips to open 170s after the command. Flow does not wait.
        if opened is not None and closed is None and clock["t"] - opened >= 170:
            hass.states.async_set("valve.bed", "open")
        rate = 0.0
        if opened is not None and (closed is None or clock["t"] - closed < 20):
            elapsed = clock["t"] - opened
            # Low at the edges. The middle of the five-minute run is the plateau,
            # and it is already up before the valve entity says open.
            if 90 <= elapsed < 240:
                rate = 9.5
            elif 30 <= elapsed < 90 or elapsed >= 240:
                rate = 2.0
        hass.states.async_set(
            "sensor.main_flow", str(rate), {"unit_of_measurement": "gal/min"}
        )

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
    assert zone["baseline_gpm"] == pytest.approx(9.5)
    assert zone["baseline_source"] == "flow_test"
    assert zone["last_run"]["minutes"] == pytest.approx(5, abs=0.1)
    assert marks["close"] - marks["open"] == pytest.approx(300, abs=5)

    await hass.services.async_call(
        DOMAIN, "learn_flow_rates", {"zone": "Bed", "minutes": 2}, blocking=True
    )
    task = entry.runtime_data.executor._task
    assert task is not None
    await task
    await hass.async_block_till_done()
    assert entry.runtime_data.store.zone("bed")["last_run"]["minutes"] == pytest.approx(
        2, abs=0.1
    )


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
