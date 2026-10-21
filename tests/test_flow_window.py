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
    # The next zone's water must not be in this window.
    samples.append(FlowSample(closed + timedelta(minutes=1), "closed", gpm=14.7))
    assert steady_gpm(samples, idle_gpm=0.5) == pytest.approx(2.28)


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
    """Each zone runs 15 open minutes. The previous zone's tail is not included."""
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
            if state == "opening" and clock["t"] - marks[f"open:{entity}"] >= 180:
                hass.states.async_set(entity, "open")
                state = "open"
            if state == "closing" and clock["t"] - marks[f"close:{entity}"] >= 180:
                hass.states.async_set(entity, "closed")
                state = "closed"
            if state in {"open", "closing"}:
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
