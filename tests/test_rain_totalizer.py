"""Each report adds rain into the local day. Daily total stays the default."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sprinklecast.const import (
    CONF_ELEVATION_M,
    CONF_PLAN_HOUR,
    CONF_PLANT_TYPE,
    CONF_PRECIPITATION_RATE,
    CONF_RAIN_AMOUNT_SENSOR,
    CONF_RAIN_KIND,
    CONF_ROOT_DEPTH_IN,
    CONF_SLOPE_PCT,
    CONF_SOIL_TYPE,
    CONF_SUN_EXPOSURE,
    CONF_VALVE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    RAIN_KIND_DAILY,
    RAIN_KIND_INTERVAL,
)
from custom_components.sprinklecast.diagnostics import async_get_config_entry_diagnostics
from sprinklecast.balance import rain_effect
from sprinklecast.observe import fresh_day, note_rain_interval
from sprinklecast.store import SmartWaterStore
from sprinklecast.units import depth_mm

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

CHICAGO = ZoneInfo("America/Chicago")
RAIN = "sensor.rain_amount"


def _at(day: date, hour: int, minute: int, *, fold: int = 0) -> datetime:
    return datetime(
        day.year, day.month, day.day, hour, minute, tzinfo=CHICAGO, fold=fold
    )


def test_equal_consecutive_reports_each_count_once() -> None:
    """Two minutes can publish the same amount. Each reset is its own rain."""
    track = fresh_day("2026-11-07")
    moment = _at(date(2026, 11, 7), 23, 1)
    assert note_rain_interval(track, value_mm=0.254, identity="2026-11-07T23:01:00-06:00", at=moment)
    assert note_rain_interval(track, value_mm=0.254, identity="2026-11-07T23:02:00-06:00", at=moment)
    assert track["rain_mm"] == pytest.approx(0.508)
    assert note_rain_interval(
        track, value_mm=0.254, identity="2026-11-07T23:02:00-06:00", at=moment
    ) is False
    assert track["rain_mm"] == pytest.approx(0.508)


def test_a_repeated_poll_and_a_restored_report_do_not_add_again() -> None:
    track = fresh_day("2026-11-07")
    moment = _at(date(2026, 11, 7), 23, 4)
    note_rain_interval(track, value_mm=1.0, identity="reset-a", at=moment)
    saved = dict(track)
    restored = fresh_day("2026-11-07")
    restored.update(saved)
    assert note_rain_interval(restored, value_mm=1.0, identity="reset-a", at=moment) is False
    assert restored["rain_mm"] == pytest.approx(1.0)


def test_daily_total_still_replaces_and_does_not_sum_reports() -> None:
    from sprinklecast.observe import note_rain

    track = fresh_day("2026-11-07")
    note_rain(track, kind=RAIN_KIND_DAILY, value_mm=0.254, at=_at(date(2026, 11, 7), 23, 1))
    note_rain(track, kind=RAIN_KIND_DAILY, value_mm=0.254, at=_at(date(2026, 11, 7), 23, 2))
    assert track["rain_mm"] == pytest.approx(0.254)


def test_small_reports_count_once_the_day_total_is_large_enough() -> None:
    """One minute can be below 0.2 × ET0. The storm is the sum of the minutes."""
    one = depth_mm(0.01, "in")
    assert one == pytest.approx(0.254)
    ignored, reason = rain_effect(one, 5.0)[1:]
    assert ignored is True
    assert "day's total" in reason
    counted, counted_reason = rain_effect(one * 10, 5.0)[1:]
    assert counted is False
    assert "so it counts" in counted_reason
    assert depth_mm(1.0, None) is None
    assert depth_mm(1.0, "cm") is None
    assert depth_mm(1.0, "ft") is None


def test_dst_and_midnight_keep_each_local_day() -> None:
    """Both 1:30s on the fall-back morning belong to that day. Midnight starts the next."""
    fall_first = _at(date(2026, 11, 1), 1, 30, fold=0)
    fall_second = _at(date(2026, 11, 1), 1, 30, fold=1)
    assert fall_first.date() == fall_second.date() == date(2026, 11, 1)
    assert fall_first.utcoffset() != fall_second.utcoffset()
    track = fresh_day(fall_first.date().isoformat())
    note_rain_interval(track, value_mm=1.0, identity=fall_first.isoformat(), at=fall_first)
    note_rain_interval(track, value_mm=1.0, identity=fall_second.isoformat(), at=fall_second)
    assert track["rain_mm"] == pytest.approx(2.0)

    spring_early = _at(date(2026, 3, 8), 1, 30)
    spring_late = _at(date(2026, 3, 8), 3, 30)
    assert spring_early.date() == spring_late.date() == date(2026, 3, 8)
    assert _at(date(2026, 3, 9), 0, 10).date() == date(2026, 3, 9)

    store = SmartWaterStore.__new__(SmartWaterStore)
    store.weather = fresh_day("2026-11-07")
    store.climate_days = []
    note_rain_interval(
        store.weather,
        value_mm=1.5,
        identity="2026-11-07T23:50:00-06:00",
        at=_at(date(2026, 11, 7), 23, 50),
    )
    store.weather["rain_credited_mm"] = 1.5
    rolled = store.weather_for("2026-11-08")
    assert rolled["rain_mm"] == 0
    assert rolled["rain_credited_mm"] == 0
    assert rolled["rain_interval_id"] == "2026-11-07T23:50:00-06:00"
    assert note_rain_interval(
        rolled,
        value_mm=1.5,
        identity="2026-11-07T23:50:00-06:00",
        at=_at(date(2026, 11, 8), 0, 5),
    ) is False
    assert rolled["rain_mm"] == 0
    note_rain_interval(
        rolled,
        value_mm=0.4,
        identity="2026-11-08T00:10:00-06:00",
        at=_at(date(2026, 11, 8), 0, 10),
    )
    assert rolled["rain_mm"] == pytest.approx(0.4)


def _entry(kind: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Sprinklers",
        data={CONF_WEATHER_ENTITY: "weather.home"},
        options={
            CONF_ELEVATION_M: 219.0,
            CONF_PLAN_HOUR: 23,
            CONF_RAIN_AMOUNT_SENSOR: RAIN,
            CONF_RAIN_KIND: kind,
        },
        subentries_data=[
            {
                "data": {
                    CONF_PLANT_TYPE: "warm_season_turf",
                    CONF_SOIL_TYPE: "clay_loam",
                    CONF_SLOPE_PCT: 6,
                    CONF_SUN_EXPOSURE: "full_sun",
                    CONF_ROOT_DEPTH_IN: 6,
                    CONF_PRECIPITATION_RATE: 1.5,
                    CONF_VALVE_ENTITY: "switch.front_valve",
                },
                "subentry_type": "zone",
                "title": "Front",
                "unique_id": "front",
                "subentry_id": "front",
            }
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
    hass.states.async_set("switch.front_valve", "off")


async def _setup(hass: HomeAssistant, kind: str) -> MockConfigEntry:
    entry = _entry(kind)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _push(
    hass: HomeAssistant, value: str, reset: str, unit: str | None = "in"
) -> None:
    attributes = {} if unit is None else {"unit_of_measurement": unit}
    attributes["last_reset"] = reset
    hass.states.async_set(RAIN, value, attributes)
    await hass.async_block_till_done()


async def test_live_interval_counts_equal_amounts_and_skips_duplicates(
    hass: HomeAssistant,
) -> None:
    _weather(hass)
    entry = await _setup(hass, RAIN_KIND_INTERVAL)
    await _push(hass, "0.01", "2026-11-07T23:01:00-06:00")
    await _push(hass, "0.01", "2026-11-07T23:02:00-06:00")
    await _push(hass, "0.01", "2026-11-07T23:02:00-06:00")
    coordinator = entry.runtime_data
    state = hass.states.get(RAIN)
    coordinator._ingest_rain_state(state, dt_util.now(CHICAGO))
    assert coordinator.store.weather["rain_mm"] == pytest.approx(0.508)
    await _push(hass, "unavailable", "2026-11-07T23:03:00-06:00")
    await _push(hass, "0.01", "2026-11-07T23:04:00-06:00", unit="cm")
    await _push(hass, "nope", "2026-11-07T23:05:00-06:00")
    assert coordinator.store.weather["rain_mm"] == pytest.approx(0.508)
    assert coordinator.store.weather["rain_unit_rejected"] is True
    downloaded = await async_get_config_entry_diagnostics(hass, entry)
    rain = downloaded["rain"]
    assert rain["sensor"] == RAIN
    assert rain["mode"] == "interval"
    assert rain["source"] == "sensor"
    assert rain["accumulated_mm"] == pytest.approx(0.508)
    assert rain["raw_mm"] == pytest.approx(0.254)
    assert rain["unit"] == "cm"


async def test_daily_mode_keeps_only_the_current_reading(hass: HomeAssistant) -> None:
    """An existing hub that does not choose Each report still replaces the day."""
    _weather(hass)
    entry = await _setup(hass, RAIN_KIND_DAILY)
    await _push(hass, "0.01", "2026-11-07T23:01:00-06:00")
    await _push(hass, "0.01", "2026-11-07T23:02:00-06:00")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.store.weather["rain_mm"] == pytest.approx(0.254)
    assert entry.runtime_data.store.weather["rain_mode"] == "daily_total"
    note = entry.runtime_data.rain_diagnostics()["note"]
    assert "Each report" in note


async def test_restart_and_a_second_credit_do_not_repeat_rain(
    hass: HomeAssistant,
) -> None:
    _weather(hass)
    entry = await _setup(hass, RAIN_KIND_INTERVAL)
    await _push(hass, "0.10", "2026-11-07T18:00:00-06:00")
    coordinator = entry.runtime_data
    total = float(coordinator.store.weather["rain_mm"])
    assert total == pytest.approx(2.54)
    day = str(coordinator.store.weather["date"])
    zone = coordinator.store.zone("front")
    zone["deficit_mm"] = 10.0
    zone["balance_date"] = day
    coordinator.store.et0_mm = 5.0
    coordinator.store.et0_date = day
    coordinator.store.weather["rain_credited_mm"] = 0.0
    coordinator._credit_uncredited_rain(day, 5.0)
    assert zone["deficit_mm"] == pytest.approx(10.0 - total)
    credited = zone["deficit_mm"]
    coordinator._credit_uncredited_rain(day, 5.0)
    assert zone["deficit_mm"] == pytest.approx(credited)
    await coordinator.store.async_save()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    restarted = entry.runtime_data
    assert restarted.store.weather["rain_mm"] == pytest.approx(total)
    assert restarted.store.zone("front")["deficit_mm"] == pytest.approx(credited)
    state = hass.states.get(RAIN)
    restarted._ingest_rain_state(state, dt_util.now(CHICAGO))
    assert restarted.store.weather["rain_mm"] == pytest.approx(total)
    restarted._credit_uncredited_rain(str(restarted.store.weather["date"]), 5.0)
    assert restarted.store.zone("front")["deficit_mm"] == pytest.approx(credited)


async def test_rain_after_the_evening_step_carries_across_midnight(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rain after 23:05 counts once. Midnight does not drop it or apply it twice."""
    clock = datetime(2026, 11, 7, 23, 10, tzinfo=CHICAGO)

    def frozen_now(tz=None):
        if tz is None:
            return clock
        return clock.astimezone(tz)

    monkeypatch.setattr(dt_util, "now", frozen_now)
    _weather(hass)
    entry = await _setup(hass, RAIN_KIND_INTERVAL)
    coordinator = entry.runtime_data
    zone = coordinator.store.zone("front")
    zone["balance_date"] = "2026-11-07"
    coordinator.store.et0_mm = 5.0
    coordinator.store.et0_date = "2026-11-07"
    await _push(hass, "0.10", "2026-11-07T23:40:00-06:00")
    added = float(coordinator.store.weather["rain_mm"])
    assert added == pytest.approx(2.54)
    zone["deficit_mm"] = 8.0
    coordinator.store.weather["rain_credited_mm"] = 0.0
    coordinator._credit_uncredited_rain("2026-11-07", 5.0)
    assert zone["deficit_mm"] == pytest.approx(8.0 - added)
    after_credit = zone["deficit_mm"]
    coordinator._credit_uncredited_rain("2026-11-07", 5.0)
    assert zone["deficit_mm"] == pytest.approx(after_credit)

    clock = datetime(2026, 11, 8, 0, 10, tzinfo=CHICAGO)
    await _push(hass, "0.02", "2026-11-08T00:10:00-06:00")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    weather = coordinator.store.weather
    assert weather["date"] == "2026-11-08"
    assert weather["rain_mm"] == pytest.approx(0.508)
    yesterday = coordinator.store.climate_day("2026-11-07")
    assert yesterday["rain_mm"] == pytest.approx(added)
    # The new day's 0.02 in is under 0.2 × 5 mm, and yesterday was already credited.
    assert zone["deficit_mm"] == pytest.approx(after_credit)
    coordinator._credit_uncredited_rain("2026-11-08", 5.0)
    assert zone["deficit_mm"] == pytest.approx(after_credit)


def test_invalid_state_object_does_not_guess_a_unit() -> None:
    """A blank unit is not inches. The helper the coordinator uses rejects it."""
    assert depth_mm(0.1, "") is None
    state = SimpleNamespace(
        entity_id=RAIN,
        state="0.1",
        attributes={"last_reset": "2026-11-07T12:00:00-06:00"},
        last_changed=None,
        last_updated=None,
        last_reset=None,
    )
    assert state.attributes.get("unit_of_measurement") is None
