"""A simulated week must call the same planner a live hub uses."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smart_water.balance import apply_daily_balance
from smart_water.et import ETInputs, daily_et0, extraterrestrial_radiation_mj
from smart_water.et import radiation_from_sunshine_mj
from smart_water.planner import PlanRequest, build_plan, build_zone_request
from smart_water.schedule import rules_for
from smart_water.simulate import (
    SCENARIOS,
    SimSettings,
    SimZone,
    initial_deficit_mm,
    parse_day,
    preset_week,
    run_week,
)
from smart_water.solar import next_sunrise

SITE = SimSettings(
    latitude=31.5493,
    longitude=-97.1467,
    elevation_m=219,
    timezone="America/Chicago",
    start=date(2026, 7, 13),
)


def _lawn(**extra: object) -> SimZone:
    data = {
        "plant_type": "st_augustine",
        "soil_type": "clay_loam",
        "sprinkler_type": "spray",
        "sun_exposure": "full_sun",
        "area_sqft": 1000,
        "valve_entity": "simulation.front_lawn",
    }
    data.update(extra)
    return SimZone(zone_id="front", name="Front lawn", data=data)


def test_presets_are_seven_example_days() -> None:
    """Each named week is seven days. The numbers are examples, not normals."""
    assert date(2026, 7, 13).weekday() == 0
    for scenario in SCENARIOS:
        days = preset_week(scenario)
        assert len(days) == 7
        assert all(0 <= day.cloud <= 1 for day in days)


def test_one_day_matches_the_live_planner() -> None:
    """ET, the bucket, and the timeline come from the live functions."""
    zone = _lawn()
    day = preset_week("hot_dry")[0]
    result = run_week((zone,), (day,), SITE, bucket="full", scenario="hot_dry")
    current = date(2026, 7, 13)
    ra = extraterrestrial_radiation_mj(SITE.latitude, current.timetuple().tm_yday)
    rs = radiation_from_sunshine_mj(ra, 1.0 - day.cloud)
    et = daily_et0(
        ETInputs(
            t_max_c=day.high_c,
            t_min_c=day.low_c,
            latitude_deg=SITE.latitude,
            day_of_year=current.timetuple().tm_yday,
            elevation_m=SITE.elevation_m,
            rh_mean_pct=day.humidity_pct,
            wind_m_s=day.wind_m_s,
            wind_height_m=SITE.wind_height_m,
            rs_mj_m2_day=rs,
        )
    )
    assert et.et0_mm is not None
    deficit = initial_deficit_mm("full", zone.data, current.month)
    preview = build_zone_request(
        zone_id=zone.zone_id,
        name=zone.name,
        data=zone.data,
        deficit_mm=deficit,
        et0_mm=et.et0_mm,
        month=current.month,
    )
    updated = apply_daily_balance(
        deficit,
        preview.taw_mm,
        etc_mm=preview.etc_mm,
        precip_mm=day.rain_mm,
        et0_mm=et.et0_mm,
    )
    request = build_zone_request(
        zone_id=zone.zone_id,
        name=zone.name,
        data=zone.data,
        deficit_mm=updated.deficit_mm,
        et0_mm=et.et0_mm,
        month=current.month,
    )
    evening = datetime(2026, 7, 13, 23, tzinfo=ZoneInfo("America/Chicago"))
    finish_by = next_sunrise(SITE.latitude, SITE.longitude, evening).astimezone(
        evening.tzinfo
    ) - timedelta(minutes=SITE.sunrise_buffer_min)
    schedule = rules_for(None, None, None)
    plan = build_plan(
        PlanRequest(
            zones=(request,),
            finish_by=finish_by,
            earliest_start=None,
            forecast_precip_mm=0.0,
            forecast_skip_mm=None,
            hub_rain_wet=False,
            mode="notify_only",
            automatic=False,
            allowed_weekdays=schedule.allowed_weekdays,
            blackout_start_hour=schedule.blackout_start,
            blackout_end_hour=schedule.blackout_end,
            whole_minutes=True,
        )
    )
    planned = plan.zones[0]
    row = result["days"][0]["zones"][0]
    assert result["would_execute"] is False
    assert row["et0_mm"] == round(et.et0_mm, 2)
    assert row["etc_mm"] == round(planned.etc_mm, 2)
    assert row["kc"] == round(planned.kc, 2)
    assert row["deficit_mm"] == round(planned.deficit_mm, 2)
    assert row["effective_rain_mm"] == round(updated.effective_precip_mm, 2)
    assert row["waters"] is planned.scheduled
    assert row["runtime_min"] == planned.runtime_min
    assert row["cycles"] == list(planned.cycles)
    assert row["valve"] == "simulation.front_lawn"
    assert "Front lawn" in result["markdown"]


def test_hot_dry_week_for_st_augustine_on_clay_loam() -> None:
    """July uses the warm-season monthly coefficient, and gallons need an area."""
    result = run_week(
        (_lawn(),),
        preset_week("hot_dry"),
        SITE,
        bucket="full",
        scenario="hot_dry",
    )
    rows = [zone for day in result["days"] for zone in day["zones"]]
    assert result["scenario_name"] == "Hot dry Texas summer"
    assert result["would_execute"] is False
    assert len(result["days"]) == 7
    assert all(zone["kc"] == pytest.approx(0.71) for zone in rows)
    assert any(zone["waters"] for zone in rows)
    assert all(zone["gallons"] is not None for zone in rows if zone["waters"])
    assert "Total runtime" in result["markdown"]
    assert "no valve" in result["note"].lower() or "No valve" in result["note"]


def test_custom_day_and_bucket_choices() -> None:
    """A service payload can replace the preset and start the soil partly dry."""
    assert parse_day({"high_f": 70, "low_f": 50, "rain_mm": 12}).rain_in == pytest.approx(
        12 / 25.4, rel=0.01
    )
    day = parse_day({"high_c": 35, "low_c": 22, "rain_in": 0, "wind_m_s": 2})
    assert day.humidity_pct == 50
    assert day.cloud == pytest.approx(0.2)
    lawn = _lawn().data
    raw = initial_deficit_mm("raw", lawn, 7)
    half = initial_deficit_mm("half", lawn, 7)
    assert initial_deficit_mm("full", lawn, 7) == 0
    # St. Augustine's table depletion is 0.50, so half of TAW is RAW.
    assert half == pytest.approx(raw)
    assert raw > 0
    cool = dict(lawn)
    cool["plant_type"] = "cool_season_turf"
    assert initial_deficit_mm("raw", cool, 7) < initial_deficit_mm("half", cool, 7)
    result = run_week((_lawn(),), (day,), SITE, bucket="raw", scenario=None)
    assert result["scenario_name"] == "Custom week"
    assert result["bucket"] == "raw"
    assert result["days"][0]["zones"][0]["waters"] is True


def test_overrides_and_skip_reasons_use_the_planner() -> None:
    """A crop-coefficient override, a pause, a forecast, and a schedule day."""
    overridden = run_week(
        (_lawn(kc_override=1.0),),
        preset_week("hot_dry")[:1],
        SITE,
        bucket="full",
    )
    assert overridden["days"][0]["zones"][0]["kc"] == pytest.approx(1.0)

    paused = SimZone(
        zone_id="front",
        name="Front lawn",
        data=_lawn().data,
        skipped_until="2026-07-20",
    )
    paused_week = run_week((paused,), preset_week("hot_dry"), SITE, bucket="raw")
    assert all("Skipped until" in zone["reason"] for day in paused_week["days"] for zone in day["zones"])
    assert not any(zone["waters"] for day in paused_week["days"] for zone in day["zones"])

    rainy = run_week(
        (_lawn(),),
        preset_week("rainy"),
        SimSettings(
            latitude=SITE.latitude,
            longitude=SITE.longitude,
            elevation_m=219,
            timezone="America/Chicago",
            start=date(2026, 7, 13),
            forecast_skip_mm=5,
        ),
        bucket="raw",
        scenario="rainy",
    )
    assert any(
        "forecast rain" in zone["reason"]
        for day in rainy["days"]
        for zone in day["zones"]
    )

    scheduled = run_week(
        (_lawn(),),
        preset_week("hot_dry"),
        SimSettings(
            latitude=SITE.latitude,
            longitude=SITE.longitude,
            elevation_m=219,
            timezone="America/Chicago",
            start=date(2026, 7, 13),
            allowed_weekdays=("sun", "tue", "thu"),
        ),
        bucket="raw",
        scenario="hot_dry",
    )
    assert any(
        "Not an allowed watering day" in zone["reason"]
        for day in scheduled["days"]
        for zone in day["zones"]
    )


def test_bubbler_without_a_rate_is_rejected() -> None:
    """A bubbler still has no invented precipitation rate."""
    zone = _lawn(sprinkler_type="bubbler")
    del zone.data["area_sqft"]
    with pytest.raises(ValueError):
        run_week((zone,), preset_week("hot_dry")[:1], SITE)
