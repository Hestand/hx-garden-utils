# Smart Water

Work in progress, not ready for general use.

Water-balance planner for Home Assistant (`smart_water` 0.2.0).

It estimates reference evapotranspiration, tracks a soil-water deficit for each zone, and builds a nightly cycle-and-soak plan that finishes before sunrise. **Version 0.2.0 never opens a valve, switch, or input boolean, and it never calls a controller API.** A plan is a notification and a set of sensors. The formulas and the stored on/off entity are ready for a later executor.

The formulas follow FAO-56 (Penman-Monteith, the soil-water bucket, and the depletion fraction) and the NRCS maximum sprinkler application rates by soil and slope. `docs/design.md` is the design note. Comments in `et.py`, `balance.py`, `cycle_soak.py`, and `soil.py` cite the equations and tables.

## Install on Home Assistant OS

Requires Home Assistant **2025.3** or newer (config subentries). Tested on **2026.10.1**. No extra Python packages. Number selectors use a step of at least 0.001, or `"any"` for latitude and longitude.

### HACS custom repository

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/Hestand/hx-garden-utils` as category **Integration**.
3. Download **Smart Water** (release `v0.2.0`), then restart Home Assistant.

`hacs.json` is included. This is not in the default HACS store.

### Manual copy

Copy the integration folder onto the HA config share:

```text
config/custom_components/smart_water/
```

That directory must contain `__init__.py` and `manifest.json`. Restart Home Assistant. Settings → Devices & services → Add integration → **Smart Water**.

### Upgrading from 0.1.x

Download 0.2.0 and restart. The config entry stays at version 1. Existing hubs and zones keep working with no reconfigure:

- Schedule preset stays unset, which means every day is allowed. Friday plans do not start skipping.
- Runtimes stay whole minutes.
- Sprinkler type defaults to spray, so soak times do not change.
- Moisture is off, flow is unconfigured, and adjustment is 100%.
- A valve saved earlier is still stored. The selector now also accepts a `switch` or `input_boolean`. Pick one the next time you edit the zone if you want a different entity. Nothing is turned on.

Set a schedule preset, rain sensor, moisture sensor, or flow sensor only if you want those features.

## Configure

Add the integration once. That creates the hub, then immediately asks for the first zone. More zones are added from the hub's device page (Add zone). Options and zone reconfigure edit the same fields.

### Hub

| Setting | Notes |
| --- | --- |
| Name | Device name. |
| Weather entity | Fallback daily forecast via `weather.get_forecasts`. Entity sensors win when they are set. |
| Elevation (m) | Atmospheric pressure when no pressure sensor is set. Default **219 m** is the design site (USGS ~218.6 m). Home Assistant's elevation of 0 is wrong for ET. |
| Latitude / longitude | Optional override. Blank uses the HA location. Step is `any` so 2026.10 accepts full precision. |
| Dry-run | **Off by default.** Optional. v0.2.0 still does not water. |
| Mode | `auto`, `notify_only` (default), or `off`. |
| Notify target | Optional, `notify.mobile_app_phone` or `mobile_app_phone`. |
| Rain sensor | Optional binary sensor. On means skip every zone. |
| Plan hour | Local hour when today's ET and rain are committed (default 23). |
| Earliest hour / sunrise buffer | Watering window. The plan is shifted so the last cycle ends at sunrise minus the buffer (default 30 min). |
| Forecast skip | Optional rain depth (mm) for tomorrow. Unset means forecast rain does not skip a zone. |
| Round minutes | On by default. Off keeps cycle lengths to 0.1 minute. |
| Watering-day preset | `none` (default), Waco odd, Waco even, or custom. |
| Allowed weekdays / blackout hours | Used by `none` (blackout only) and `custom`. Waco presets ignore these and use their own days and 10:00–19:00. |
| Drip ignores weekdays | Off by default. Buried drip can skip the weekday check. The blackout still clips the shared timeline. A drip-only yard can leave the preset on `none`. |
| Climate sensors | Optional temperature, humidity, wind, pressure, solar radiation, UV, and rain amount. |

### Tempest as the reference weather setup

Map the station's entities. Units are converted (temperature, mm/in, m/s, kPa, W/m² or MJ/m², gallons).

| Smart Water field | Typical Tempest entity |
| --- | --- |
| Temperature | Air temperature |
| Humidity | Humidity |
| Wind | Wind speed (height defaults to 2 m) |
| Pressure | Station pressure, not sea-level pressure |
| Solar radiation | Solar radiation in W/m², integrated through the day |
| UV index | Only if solar radiation is empty. About 100 W/m² per UV index, which is not an FAO factor |
| Rain amount, kind daily total | Rain today |
| Weather entity | Left as the fallback for forecast rain and for any sensor you leave empty |

Rain kinds: **daily total** replaces today's amount (Tempest rain today). **Cumulative** ignores the first sample so history before install is not credited, then adds increases and ignores a counter reset. **Rate** is mm/h, trapezoid-integrated, and gaps longer than 6 hours are dropped. Effective rain follows FAO-56: a day below 0.2 × ET0 is ignored. Forecast rain skips a zone only when you set a threshold.

### Zone

Name, plant type, soil type, slope %, sun exposure, sprinkler type, root depth, and management allowed depletion (MAD / p). Precipitation rate is **inches per hour**, or GPM plus area in square feet (`96.25 × GPM / area`). An entered rate wins over GPM and area.

Plant presets fill suggested root depth and p. Cool-season turf Kc 0.8 and warm-season turf Kc 0.6 are UC ANR annual averages. Warm-season p = 0.50, shrub / native / vegetable / tree coefficients, and the sun factors (full 1.0, part 0.8, shade 0.6) are starting points you can override per zone.

Sprinkler type is spray, rotor, MP rotator, drip, or bubbler. Drip and bubbler soak for 0 unless you set a soak override. Spray keeps the NRCS soak (60 minutes on clay, clay loam, and compact silt loam, otherwise 30).

| Optional zone field | What it does |
| --- | --- |
| On/off entity | `switch`, `valve`, or `input_boolean`. Stored. Not called. |
| Soil moisture | Relative percent (or a 0–1 fraction) or volumetric water content. **Correct** blends toward the sensor once on the day the bucket commits, weight default 0.5. **Override** replaces the deficit on every update. VWC needs field capacity: deficit = max(0, (θFC − θ) × root depth in meters × 1000). |
| Flow sensor | Any entity, volume total or rate. Records delivered gallons and sets the flow sensor to `pending`, `ok`, `low_flow`, `leak`, `no_data`, or `not_configured`. Default low ratio 0.5, leak ratio 1.5. Nothing is shut off. |
| Zone rain sensor | Binary sensor. On skips that zone. |

## Why v0.2.0 does not water

Dry-run is optional and **defaults to off**. There is no confirmation phrase. Turning it on only marks a plan as not for execution.

What stops watering is that **there is no executor**. `safety.EXECUTION_IMPLEMENTED` is false, so `would_execute` stays false even when dry-run is off and mode is `auto`. The plan summary still starts with `DRY-RUN` and the block reason. Mode defaults to notify-only. The master switch never opens a valve.

Services only change the stored bucket, the adjustment, or the plan:

| Service | Effect |
| --- | --- |
| `calculate_plan` | Commit today's balance if needed, then rebuild the plan. |
| `reset_bucket` / `set_bucket` | Deficit 0, or an absolute deficit clamped to total available water. |
| `mark_watered` | Credit net irrigation already applied. Empty depth refills the bucket. |
| `skip_zone` | Skip through a date. Default is the next local morning. |
| `pause_zone` | Skip N local days. Zero clears the pause. |
| `set_adjustment` | Percent of the calculated depth. 100 is unchanged. 0 keeps the zone off the timeline. The number entity does the same thing. |
| `run_now` | Writes the planned minutes to the log and to `last_run_now`. Does not credit the bucket and does not call the on/off entity. |

A later executor will call the stored entity's turn-on or open service, one zone at a time, and will not call Hydrawise APIs or `hydrawise.start_watering`. A Hydrawise zone is usable only when Home Assistant already exposes it as a valve, switch, or other on/off entity. Your existing controller schedule is unchanged. If it still waters at dawn, Smart Water will not stop it.

## What the nightly plan does

Once per local day, at or after the plan hour, each zone's bucket is updated:

`Dr = Dr + ETc − rain − irrigation` (FAO-56 style), clamped to total available water. Rain below 0.2 × ET0 is ignored. Irrigation is credited only by `mark_watered` or `set_bucket` / `reset_bucket`, not by the daily job. Calling `calculate_plan` before the plan hour commits that day's ET early; the evening update will not apply it twice.

A zone is due when its deficit has reached readily available water (RAW), or when a few days of crop ET would reach RAW. The scheduled depth is the current deficit times the adjustment percent, back toward field capacity. Runtime is `60 × (net inches / efficiency) / precipitation rate`, whole minutes unless you turn rounding off. Efficiency defaults to **1.0**.

Max cycle length is `floor(60 × NRCS intake in/hr / precipitation rate)`. Example: clay loam on a 5–8% slope (0.10 in/hr) at 1.5 in/hr is a **4 minute** cycle and a 20 mm deficit is **31 minutes**. One valve at a time; another zone may be planned during a soak. The timeline is shifted to finish by sunrise minus the buffer, after the blackout clips that deadline. If it does not fit, cycle lengths are scaled down and the plan says so.

ET0 uses FAO-56 Penman-Monteith when humidity and wind are available. Daily solar radiation is the integrated W/m² (or a daily MJ/m² sensor) when that total is above zero, otherwise the Hargreaves radiation estimate. Temperature-only days use Hargreaves ET0. A temperature sensor replaces the forecast high and low once the observed range is at least 0.5 °C, so one reading cannot zero the radiation estimate. Missing temperatures produce no ET0 and the bucket is left alone.

### Waco rules

The preset matches the City of Waco year-round outdoor rules effective 1 July 2024: odd addresses water Sunday, Tuesday, and Thursday; even addresses water Monday, Wednesday, and Saturday; Friday is off; no watering from 10:00 to 19:00. The ordinance does not restrict buried drip the same way. This integration only lets drip skip the weekday check, and only when **Drip ignores weekday limits** is on. The 10:00–19:00 blackout still applies to the shared timeline. Sources: the city water-conservation page and the outdoor watering ordinance.

## Entities

Per zone: deficit, readily available water, next planned run, plan reason, plan (scheduled or idle, with runtime, cycles, adjustment, sprinkler, and the stored on/off entity), flow status, moisture deficit, an adjustment number (0–300%), a run-now button, and an enabled switch.

Hub: mode, tonight's plan, today's ET0, rain today (effective rain and whether it was ignored), next run (preset, weekdays, blackout, whole-minute rounding), and the master auto switch.

Bucket state, the day's weather accumulation, flow totals, adjustment, and the last plan are stored and survive a restart. Storage version stays 1; new keys are filled in when an older file is loaded.

## Develop

```bash
python3 -m pytest
```

Math tests do not import Home Assistant. Config-flow tests need `pytest-homeassistant-custom-component` matching Home Assistant 2026.10 and serialize every form the way the config HTTP API does.

## Roadmap

**Next — a generic executor.** Call the stored on/off entity (valve, switch, or input boolean, including an entity a controller integration already exposed). Do not call Hydrawise services. One zone at a time, whole minutes when that option is on, and honor dry-run, mode, and `would_execute`. Confirm the entity returned to off.

Wind and freeze lockouts are not in this version.

## Limits

- No Lovelace card.
- No wind or freeze lockout.
- On/off entities are stored and never called.
- Run-now only logs the plan.
- Flow and moisture never close a valve.
- Sunrise is a civil approximation (about ten minutes), not a weather-service sunrise.
- Soil, slope, plant, sun, and precipitation rate are entered per zone.
- The Waco drip exemption is weekday-only. The blackout is shared by every zone on the timeline.
- Daytime `calculate_plan` commits a full day of ET if today's balance has not run yet.
