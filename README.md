# Smart Water

Work in progress, not ready for general use.

Water-balance planner for Home Assistant (`smart_water` 0.4.0).

It estimates reference evapotranspiration, tracks a soil-water deficit for each zone, and builds a nightly cycle-and-soak plan that finishes before sunrise. **Version 0.4.0 never opens a valve, switch, or input boolean, and it never calls a controller API.** A plan is a notification and a set of sensors. A simulation hub plays an example week through that same planner. The formulas and the stored on/off entity are ready for a later executor.

The formulas follow FAO-56 (Penman-Monteith, the soil-water bucket, and the depletion fraction) and the NRCS maximum sprinkler application rates by soil and slope. Plant, soil, and sprinkler defaults, each with a source, live in `presets.py`. `docs/design.md` is the design note.

## Install on Home Assistant OS

Requires Home Assistant **2025.3** or newer (config subentries). Tested on **2026.10.1**. No extra Python packages. Number selectors use a step of at least 0.001, or `"any"` for latitude and longitude.

### HACS custom repository

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/Hestand/hx-garden-utils` as category **Integration**.
3. Download **Smart Water** (release `v0.4.0`), then restart Home Assistant.

`hacs.json` is included. This is not in the default HACS store.

### Manual copy

Copy the integration folder onto the HA config share:

```text
config/custom_components/smart_water/
```

That directory must contain `__init__.py` and `manifest.json`. Restart Home Assistant. Settings → Devices & services → Add integration → **Smart Water**.

### Upgrading from 0.3.x, 0.2.x, or 0.1.x

Download 0.4.0 and restart. The config entry moves to version 3. Zone data is not rewritten, and the stored bucket (storage version 1) is kept. You do not reconfigure an existing hub. A simulation hub is a new entry from the first menu.

Zones saved by the 0.2 forms already have root depth, depletion, slope, precipitation rate, and efficiency. Those stored numbers stay in effect. Efficiency was saved as 1.0 unless you changed it, so an old zone does **not** pick up the new sprinkler efficiency until you clear that field. Clear root depth, depletion, slope, precipitation rate, or efficiency in the zone's Advanced step to use the preset instead. Leave the field blank and save.

What does change for a zone that never stored a crop coefficient:

- Turf uses the monthly Meyer / UC ANR coefficient for the current month. The annual averages (warm-season 0.60, cool-season 0.80) are used only when the month is unknown.
- Sun exposure uses the WUCOLS factors: full sun 1.0, part sun 0.9, shade 0.7.
- Loam available water is the FAO-56 Table 19 midpoint, 0.155 in/in, when the zone has no available-water override. The 0.2 forms did not store that override.
- Vegetables use the ASABE plant factor 1.0 when no crop-coefficient override is stored.

A zone with no on/off entity still loads. The next time you edit it, the form asks for one. Nothing is turned on.

### Quick start

1. Settings → Devices & services → Add integration → **Smart Water**.
2. Choose **Live hub** or **Simulation hub**. A simulation needs no weather entity and no on/off entity. See [Simulation](#simulation).
3. On a live hub, name it. Pick a weather entity, or open **Sensors** and pick a temperature sensor. A Tempest (or WeatherFlow) station is filled in when Home Assistant has exactly one. Submit. Location and schedule can stay collapsed.
4. Name the zone. On a live hub, pick the on/off entity (`switch`, `valve`, or `input_boolean`), then plant, soil, sprinkler, and sun. Submit.
5. On **Advanced**, leave the fields blank. Blank means the preset. A bubbler has no published precipitation rate, so enter a rate or both flow and area. Submit.

Add more zones from the hub's device page. Options edits the sensors and the schedule. Reconfigure edits the hub name and weather entity.

## Configure

Add the integration once. That creates the hub, then immediately asks for the first zone. More zones are added from the hub's device page (Add zone). Options and zone reconfigure edit the same fields.

### Hub

The first step is a menu: **Live hub** or **Simulation hub**. The live form is the whole hub. Name is required. Weather is required only when no temperature sensor is set. **Sensors** and **Location and schedule** are collapsed sections.

| Setting | Notes |
| --- | --- |
| Name | Device name. |
| Weather entity | Optional if a temperature sensor is set. Fallback daily forecast via `weather.get_forecasts`. Entity sensors win when they are set. |
| Elevation (m) | Atmospheric pressure when no pressure sensor is set. Default **219 m** is the design site (USGS ~218.6 m). Home Assistant's elevation of 0 is wrong for ET. |
| Latitude / longitude | Optional override. Blank uses the HA location. Step is `any` so 2026.10 accepts full precision. |
| Dry-run | **Off by default.** Optional. v0.4.0 still does not water. |
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

Quick setup is the name, the on/off entity, and four dropdowns: plant, soil, sprinkler, and sun. Everything else comes from `presets.py` until you type over it.

The Advanced step is three collapsed sections. Each numeric override shows its preset in the description. Leave it blank to keep the preset. The preset is not written into the zone, so a later change to the table can apply, and a save does not freeze the suggestion. Reopening the zone shows a number only when one was saved.

| Blank field | Preset used |
| --- | --- |
| Root depth | Plant row (6 in for turf, 12 in flowers and vegetables, 24 in shrubs and drip beds, 39 in trees) |
| Available water | Soil row, FAO-56 Table 19 midpoint |
| Intake | NRCS rate for that soil at the slope (0% if slope is blank) |
| Depletion (MAD) | Plant row, then the FAO ET adjustment |
| Crop coefficient | Monthly turf table when the plant has one, otherwise the annual factor, times the sun factor |
| Precipitation rate | Sprinkler row. Bubbler has none, so the form requires a rate or GPM and area |
| Efficiency | Sprinkler row |
| Slope | 0%, the NRCS 0–5% band |
| Max cycle / soak | Computed from intake and soil. Drip and bubbler soak 0 |
| Flow and area | Optional. Together they override the precipitation preset (`96.25 × GPM / area`). An entered rate still wins |

Plant choices cover St. Augustine, Bermuda, Zoysia, Buffalo, a generic warm-season grass, cool-season grass, shrubs, flower beds, vegetables, trees, drip beds, and native plantings. The short tables and the citations are in `docs/design.md`.

| Optional zone field | What it does |
| --- | --- |
| On/off entity | Required for a new zone. `switch`, `valve`, or `input_boolean`. Stored. Not called. A zone saved before 0.3.0 without one still loads. |
| Soil moisture | Relative percent (or a 0–1 fraction) or volumetric water content. **Correct** blends toward the sensor once on the day the bucket commits, weight default 0.5. **Override** replaces the deficit on every update. VWC needs field capacity: deficit = max(0, (θFC − θ) × root depth in meters × 1000). |
| Flow sensor | Any entity, volume total or rate. Records delivered gallons and sets the flow sensor to `pending`, `ok`, `low_flow`, `leak`, `no_data`, or `not_configured`. Default low ratio 0.5, leak ratio 1.5. Nothing is shut off. |
| Zone rain sensor | Binary sensor. On skips that zone. |

## Simulation

A simulation hub is the first menu choice. It does not ask for a weather entity, a sensor, or an on/off entity. Each zone is plant, soil, sprinkler, and sun, plus an optional area and slope. The on/off id is a `simulation.<name>` label. Nothing in the week calls a valve, a switch, an input boolean, or a controller.

The week uses the same functions as a live hub: Penman-Monteith ET0, the soil bucket, `build_zone_request`, and `build_plan`. After a night that would have watered, the planned net depth is subtracted from that zone's simulated deficit, which is what a later executor would do. The live bucket is not changed.

### Run one

1. Add integration → **Smart Water** → **Simulation hub**.
2. Name the hub. Leave **Weather week** on Hot dry Texas summer and **Starting soil** on Full, or pick another preset (mild spring, rainy week, heat wave then storm, fall cooldown). Location and schedule can stay collapsed. Empty latitude and longitude use the Home Assistant location for sunrise.
3. Name the zone. Choose plant, soil, sprinkler, and sun. Area is optional; set it when you want gallons. Leave slope blank for the 0–5% intake rate. Submit.
4. On **Advanced**, leave the fields blank unless you want to override a preset. Submit.
5. The **Simulation** sensor fills in as soon as the zone exists. Its state is the week name and the total minutes. The attributes hold each day and a markdown table.
6. To run it again, press **Run simulation** on the hub, or change the week under the hub's options and press the button. The button uses the stored preset and starting soil.

Custom days replace the preset for one run. Developer tools → Actions → `smart_water.simulate`. Set **Return response** if you want the week in the action result. `days` is a YAML list. `high_f` / `low_f` or `high_c` / `low_c`, `humidity` (default 50), `wind_mph` (default 8) or `wind_m_s`, `cloud` from 0 clear to 1 overcast (default 0.2), and `rain_in` or `rain_mm`. `start_date` is `YYYY-MM-DD`. Empty starts today. The same action works on a live hub and does not change that hub's stored deficit.

```yaml
action: smart_water.simulate
data:
  hub: Play yard
  bucket: full
  start_date: "2026-07-13"
  days: |
    - high_f: 99
      low_f: 75
      humidity: 40
      wind_mph: 8
      cloud: 0.1
      rain_in: 0
```

Cloudiness becomes FAO-56 equation 35 sunshine (`n/N = 1 − cloud`) and then solar radiation, so the ET0 is Penman-Monteith. The five presets are example weeks with round numbers, not a forecast and not a climate normal. Starting soil: **full** is field capacity, **half** is half the root zone used, **raw** is ready to water.

A markdown card shows the table. The entity id follows the hub name. A hub named Play yard is `sensor.play_yard_simulation`.

```yaml
type: markdown
title: This week's watering
content: "{{ state_attr('sensor.play_yard_simulation', 'markdown') }}"
```

### Example: hot dry week, St. Augustine, clay loam, spray, full sun

Computed by `run_week`, not typed by hand. Location is the design site: latitude 31.5493, longitude −97.1467, elevation 219 m, America/Chicago. The week starts Monday 13 July 2026, so July's warm-season coefficient is 0.71. The zone is 1000 sq ft. Slope is blank, so clay loam intake is 0.15 in/hr and the max cycle is 7 minutes with a 60 minute soak. The bucket starts full. The schedule is any day, finishing 30 minutes before sunrise. Gallons are gross water from the heads (`runtime × 1.25 in/hr × 1000 sq ft × 0.623`), rounded in the table. It waters every morning because one more day of crop ET would reach readily available water, which is the live planner's rule. Total runtime is 147 minutes. `would_execute` is false.

| Day | Zone | ET0 mm | Rain in | Effective in | Deficit mm | Water | Minutes | Cycles | Start | Gallons | Why |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- | ---: | --- |
| Mon 07-13 | Front lawn | 9.1 | 0.00 | 0.00 | 6.5 | yes | 20 | 7+7+6, soak 60 | Tue 03:43, Tue 04:50, Tue 05:57 | 260 | Due |
| Tue 07-14 | Front lawn | 9.9 | 0.00 | 0.00 | 7.0 | yes | 22 | 6+6+5+5, soak 60 | Wed 02:41, Wed 03:47, Wed 04:53, Wed 05:58 | 286 | Due |
| Wed 07-15 | Front lawn | 10.7 | 0.00 | 0.00 | 7.6 | yes | 24 | 6+6+6+6, soak 60 | Thu 02:40, Thu 03:46, Thu 04:52, Thu 05:58 | 312 | Due |
| Thu 07-16 | Front lawn | 10.0 | 0.00 | 0.00 | 7.1 | yes | 22 | 6+6+5+5, soak 60 | Fri 02:42, Fri 03:48, Fri 04:54, Fri 05:59 | 286 | Due |
| Fri 07-17 | Front lawn | 9.0 | 0.00 | 0.00 | 6.4 | yes | 20 | 7+7+6, soak 60 | Sat 03:45, Sat 04:52, Sat 05:59 | 260 | Due |
| Sat 07-18 | Front lawn | 8.9 | 0.00 | 0.00 | 6.3 | yes | 20 | 7+7+6, soak 60 | Sun 03:46, Sun 04:53, Sun 06:00 | 260 | Due |
| Sun 07-19 | Front lawn | 8.6 | 0.00 | 0.00 | 6.1 | yes | 19 | 7+6+6, soak 60 | Mon 03:47, Mon 04:54, Mon 06:00 | 247 | Due |

## Why v0.4.0 does not water

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
| `simulate` | Plays a weather week through the planner and returns it. Does not change the stored deficit and does not call an on/off entity. |

A later executor will call the stored entity's turn-on or open service, one zone at a time, and will not call Hydrawise APIs or `hydrawise.start_watering`. A Hydrawise zone is usable only when Home Assistant already exposes it as a valve, switch, or other on/off entity. Your existing controller schedule is unchanged. If it still waters at dawn, Smart Water will not stop it.

## What the nightly plan does

Once per local day, at or after the plan hour, each zone's bucket is updated:

`Dr = Dr + ETc − rain − irrigation` (FAO-56 style), clamped to total available water. Rain below 0.2 × ET0 is ignored. Irrigation is credited only by `mark_watered` or `set_bucket` / `reset_bucket`, not by the daily job. Calling `calculate_plan` before the plan hour commits that day's ET early; the evening update will not apply it twice.

A zone is due when its deficit has reached readily available water (RAW), or when a few days of crop ET would reach RAW. The scheduled depth is the current deficit times the adjustment percent, back toward field capacity. Runtime is `60 × (net inches / efficiency) / precipitation rate`, whole minutes unless you turn rounding off. Efficiency is the sprinkler preset (spray 0.60) unless the zone stored an override. Zones created before 0.3.0 stored 1.0.

Max cycle length is `floor(60 × NRCS intake in/hr / precipitation rate)`. Example: clay loam on a 5–8% slope (0.10 in/hr) at 1.5 in/hr is a **4 minute** cycle and a 20 mm deficit is **31 minutes**. One valve at a time; another zone may be planned during a soak. The timeline is shifted to finish by sunrise minus the buffer, after the blackout clips that deadline. If it does not fit, cycle lengths are scaled down and the plan says so.

ET0 uses FAO-56 Penman-Monteith when humidity and wind are available. Daily solar radiation is the integrated W/m² (or a daily MJ/m² sensor) when that total is above zero, otherwise the Hargreaves radiation estimate. Temperature-only days use Hargreaves ET0. A temperature sensor replaces the forecast high and low once the observed range is at least 0.5 °C, so one reading cannot zero the radiation estimate. Missing temperatures produce no ET0 and the bucket is left alone.

### Waco rules

The preset matches the City of Waco year-round outdoor rules effective 1 July 2024: odd addresses water Sunday, Tuesday, and Thursday; even addresses water Monday, Wednesday, and Saturday; Friday is off; no watering from 10:00 to 19:00. The ordinance does not restrict buried drip the same way. This integration only lets drip skip the weekday check, and only when **Drip ignores weekday limits** is on. The 10:00–19:00 blackout still applies to the shared timeline. Sources: the city water-conservation page and the outdoor watering ordinance.

## Entities

Per zone: deficit, readily available water, next planned run, plan reason, plan (scheduled or idle, with runtime, cycles, adjustment, sprinkler, and the stored on/off entity), flow status, moisture deficit, an adjustment number (0–300%), a run-now button, and an enabled switch.

Hub: mode, tonight's plan, today's ET0, rain today (effective rain and whether it was ignored), next run (preset, weekdays, blackout, whole-minute rounding), and the master auto switch. A simulation hub also has a Simulation sensor and a Run simulation button.

Bucket state, the day's weather accumulation, flow totals, adjustment, and the last plan are stored and survive a restart. Storage version stays 1; new keys are filled in when an older file is loaded.

## Develop

```bash
python3 -m pytest
```

Math tests do not import Home Assistant. Config-flow tests need `pytest-homeassistant-custom-component` matching Home Assistant 2026.10 and serialize every form the way the config HTTP API does.

## Roadmap

**Next — a generic executor.** Call the stored on/off entity (valve, switch, or input boolean, including an entity a controller integration already exposed). Do not call Hydrawise services. One zone at a time, whole minutes when that option is on, and honor dry-run, mode, and `would_execute`. Confirm the entity returned to off. Simulation hubs keep their virtual valves and are not executed.

Wind and freeze lockouts are not in this version.

## Limits

- No custom Lovelace card. A markdown card can show the simulation sensor's `markdown` attribute.
- No wind or freeze lockout.
- On/off entities are stored and never called.
- Run-now only logs the plan.
- Flow and moisture never close a valve.
- Sunrise is a civil approximation (about ten minutes), not a weather-service sunrise.
- Soil, plant, sprinkler, and sun are chosen per zone. Slope and the other derived numbers are presets until overridden.
- The Waco drip exemption is weekday-only. The blackout is shared by every zone on the timeline.
- Daytime `calculate_plan` commits a full day of ET if today's balance has not run yet.
