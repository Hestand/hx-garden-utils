# Smart Water

Work in progress, not ready for general use.

Dry-run water-balance planner for Home Assistant (`smart_water` 0.1.0).

It estimates reference evapotranspiration, tracks a soil-water deficit for each zone, and builds a nightly cycle-and-soak plan that finishes before sunrise. **Version 0.1 never opens a valve and never calls `hydrawise.start_watering`.** A plan is a notification and a set of sensors.

The formulas follow FAO-56 (Penman-Monteith, the soil-water bucket, and the depletion fraction) and the NRCS maximum sprinkler application rates by soil and slope. Comments in `et.py`, `balance.py`, `cycle_soak.py`, and `soil.py` cite the equations and tables.

## Install on Home Assistant OS

Requires Home Assistant **2025.3** or newer (config subentries). No extra Python packages.

### HACS custom repository

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/Hestand/hx-garden-utils` as category **Integration**.
3. Download **Smart Water** (release `v0.1.0`), then restart Home Assistant.

`hacs.json` is included. This is not in the default HACS store.

### Manual copy

Copy the integration folder onto the HA config share:

```text
config/custom_components/smart_water/
```

That directory must contain `__init__.py` and `manifest.json`. Restart Home Assistant. Settings → Devices & services → Add integration → **Smart Water**.

## Configure

Add the integration once. That creates the hub, then immediately asks for the first zone. More zones are added from the hub's device page (Add zone).

### Hub

| Setting | Notes |
| --- | --- |
| Name | Device name. |
| Weather entity | Daily forecast via `weather.get_forecasts`. |
| Elevation (m) | Used for atmospheric pressure when no pressure sensor is set. Default **219 m** is the design site (USGS ~218.6 m). Home Assistant's elevation of 0 is wrong for ET — confirm yours. |
| Latitude / longitude | Optional override. Blank uses the HA location. |
| Dry-run | **Off by default.** Optional. v0.1 still does not water. |
| Mode | `auto`, `notify_only` (default), or `off`. |
| Notify target | Optional, `notify.mobile_app_phone` or `mobile_app_phone`. |
| Rain sensor | Optional binary sensor. On means skip every zone. |
| Plan hour | Local hour when today's ET and rain are committed (default 23). |
| Earliest hour / sunrise buffer | Watering window. The plan is shifted so the last cycle ends at sunrise minus the buffer (default 30 min). |
| Forecast skip | Optional rain depth (mm). Unset means forecast rain does not skip a zone. |
| Climate sensors | Optional temperature, humidity, wind, pressure, and solar. Tempest-shaped hooks; not required. |

### Zone

Name, plant type, soil type, slope %, sun exposure, root depth, and management allowed depletion (MAD / p). Precipitation rate is **inches per hour**, or GPM plus area in square feet (`96.25 × GPM / area`). An entered rate wins over GPM and area. Valve and rain-sensor entities are stored and **not called**.

Plant presets fill suggested root depth and p. Cool-season turf Kc 0.8 and warm-season turf Kc 0.6 are UC ANR annual averages. Warm-season p = 0.50, shrub / native / vegetable / tree coefficients, and the sun factors (full 1.0, part 0.8, shade 0.6) are starting points you can override per zone.

## Why v0.1 does not water

Dry-run is optional and **defaults to off**. There is no confirmation phrase. Turning it on only marks a plan as not for execution.

What actually stops watering is that **v0.1 has no executor**. `safety.EXECUTION_IMPLEMENTED` is false, so `would_execute` stays false even when dry-run is off and mode is `auto`. The plan summary still starts with `DRY-RUN` and the block reason. Mode defaults to notify-only. The master switch never opens a valve.

Services `calculate_plan`, `reset_bucket`, `set_bucket`, `mark_watered`, and `skip_zone` only change the stored bucket or the plan. They do not turn switches or call Hydrawise.

Your Hydrawise cloud schedule is unchanged. If it still waters at dawn, Smart Water will not stop it. Suspend that schedule only when you are ready for a later version that actually runs zones.

## What the nightly plan does

Once per local day, at or after the plan hour, each zone's bucket is updated:

`Dr = Dr + ETc − rain − irrigation` (FAO-56 style), clamped to total available water. Rain below 0.2 × ET0 is ignored. Irrigation is credited only by `mark_watered` or `set_bucket` / `reset_bucket`, not by the daily job. Calling `calculate_plan` before the plan hour commits that day's ET early; the evening update will not apply it twice.

A zone is due when its deficit has reached readily available water (RAW), or when a few days of crop ET would reach RAW. The scheduled depth is the current deficit (back to field capacity), not the projected extra. Runtime is whole minutes: `60 × (net inches / efficiency) / precipitation rate`. Efficiency defaults to **1.0** so an unverified distribution uniformity is not assumed.

Max cycle length is `floor(60 × NRCS intake in/hr / precipitation rate)`. Example from the design notes: clay loam on a 5–8% slope (0.10 in/hr) at 1.5 in/hr is a **4 minute** cycle. Soak is 60 minutes on clay, clay loam, and compact silt loam, otherwise 30. One valve at a time; another zone may be planned during a soak. The timeline is shifted to finish by sunrise minus the buffer. If it does not fit, cycle lengths are scaled down and the plan says so.

ET0 uses FAO-56 Penman-Monteith when humidity and wind are available (daily solar radiation if you provide MJ/m²; otherwise the temperature estimate). Instantaneous W/m² is recorded and is not treated as a daily total. Otherwise ET0 is Hargreaves from temperature. Missing temperatures produce no ET0 and the bucket is left alone.

## Entities

Per zone: soil-water deficit, readily available water, next planned run, last plan reason, and an enabled switch (stored, not a config reload).

Hub: mode, tonight's plan (short state, full summary and timeline in attributes), today's ET0, and the master auto switch.

## Develop

```bash
python3 -m pytest
```

Tests cover ET, the bucket, the NRCS cycle table, and the planner. They do not import Home Assistant.

## Roadmap

**v0.2 — execution.** Call `hydrawise.start_watering` with whole-minute durations, one zone at a time, and verify the controller stopped. Suspend the Hydrawise cloud schedule at cutover so the two schedulers do not both water. Honor dry-run and mode before any valve call. Wind, freeze, and watering-day restrictions belong here too.

**v0.3 — measurements.** Tempest (or another station) as the primary ET weather source, soil-moisture correction of the bucket, and flow to confirm a cycle actually ran.

The v0.1 planner already interleaves soaks on paper. Running that interleaved timeline is still v0.2.

## Limits

- No Lovelace card.
- No odd/even or weekday watering rules.
- No wind or freeze lockout.
- Valve entities are labels only.
- Sunrise is a civil approximation (about ten minutes), not a weather-service sunrise.
- Soil, slope, plant, sun, and precipitation rate are entered per zone. They are not inferred from Hydrawise zone names.
- Daytime `calculate_plan` commits a full day of ET if today's balance has not run yet.
