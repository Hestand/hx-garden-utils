# Smart Water

Work in progress, not ready for general use.

Water-balance planner and zone controller for Home Assistant (`smart_water` 0.7.1).

It estimates reference evapotranspiration, tracks a soil-water deficit for each zone, and builds a nightly cycle-and-soak plan that finishes before sunrise. **Automatic watering is off after a new install and after an upgrade.** Turn the hub's **Automatic watering** switch on when you want it to open valves. Until then the plan is only sensors and an optional notification. Run now is a manual action and runs even while that switch is off. A simulation hub still plays an example week and never calls a real on/off entity. The controller calls `switch`, `valve`, or `input_boolean` services only. It does not call a controller API.

The formulas follow FAO-56 (Penman-Monteith, the soil-water bucket, and the depletion fraction) and the NRCS maximum sprinkler application rates by soil and slope. Plant, soil, and sprinkler defaults, each with a source, live in `presets.py`. `docs/design.md` is the design note.

## Install on Home Assistant OS

Requires Home Assistant **2025.3** or newer (config subentries). Tested on **2026.10.1**. No extra Python packages. Number selectors use a step of at least 0.001, or `"any"` for latitude and longitude.

### HACS custom repository

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/Hestand/hx-garden-utils` as category **Integration**.
3. Download **Smart Water** (release `v0.7.1`), then restart Home Assistant.

`hacs.json` is included. This is not in the default HACS store.

### Manual copy

Copy the integration folder onto the HA config share:

```text
config/custom_components/smart_water/
```

That directory must contain `__init__.py` and `manifest.json`. Restart Home Assistant. Settings → Devices & services → Add integration → **Smart Water**.

### Upgrading from 0.5.x, 0.4.x, 0.3.x, 0.2.x, or 0.1.x

Download 0.7.1 and restart. The config entry stays at version 6. Zone data is not rewritten, and the stored bucket (storage version 1) is kept. You do not reconfigure an existing hub. 0.7.1 fixes forecast temperatures: a weather entity that reports °F (or °C) no longer crashes setup on the freeze check. New hubs ask how many zones to add during setup. An existing hub is left as it is. **Automatic watering stays off** until you turn the switch on, including when an older hub had dry-run off. A hub that already chose its watering days keeps those days. The old all-zones runtime cap becomes the per-zone default (a stored 60 stays 60 minutes per zone). The new hub nightly total stays off. A simulation hub is a new entry from the first menu, or an existing simulation hub keeps working and still does not call a real entity.

0.7 caps each zone on its own, can wait for confident forecast rain, warns before a freeze, and includes a dashboard card. Flow alerts still notify only until you change that. The weekly summary is off. Cost and the weekly gallon budget stay empty until you set them.

An older odd-address day preset becomes Sunday, Tuesday, and Thursday with a 10:00–19:00 blackout. An older even-address preset becomes Monday, Wednesday, and Saturday with the same blackout. Any other schedule, including none, allows every day and keeps a blackout you already saved. The dry-run option is removed.

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
4. **How many zones?** Default is 1. Zero creates the hub with no zones. Then, for each zone, enter the name, the on/off entity on a live hub (`switch`, `valve`, or `input_boolean`), and plant, soil, sprinkler, and sun. **Same as previous zone** copies those four. The name and on/off entity are always this zone's own.
5. Advanced is not part of that loop. Open the zone afterward and leave the Advanced fields blank. Blank means the preset. A bubbler has no published precipitation rate, so enter a rate or both flow and area there.

Add, edit, or remove zones later from the hub's device page. Options edits the sensors and the schedule. Reconfigure edits the hub name and weather entity. Existing hubs are not asked to run this again.

## Configure

Add the integration once. After the hub form, it asks how many zones, then each zone's quick fields. More zones are added from the hub's device page (Add zone). Options and zone reconfigure edit the same fields. Removing a zone is the device-page delete.

### Hub

The first step is a menu: **Live hub** or **Simulation hub**. The live form is the whole hub. Name is required. Weather is required only when no temperature sensor is set. **Sensors** and **Location and schedule** are collapsed sections.

| Setting | Notes |
| --- | --- |
| Name | Device name. |
| Weather entity | Optional if a temperature sensor is set. Daily and hourly forecasts come from `weather.get_forecasts`. Temperatures are converted from the entity's unit (°F or °C) before the freeze check. Entity sensors win when they are set. |
| Elevation (m) | Atmospheric pressure when no pressure sensor is set. Default **219 m** is the design site (USGS ~218.6 m). Home Assistant's elevation of 0 is wrong for ET. |
| Latitude / longitude | Optional override. Blank uses the HA location. Step is `any` so 2026.10 accepts full precision. |
| Mode | `auto`, `notify_only` (default), or `off`. Notify-only still waters once Automatic watering is on. Off does not. |
| Notify target | Optional, `notify.mobile_app_phone` or `mobile_app_phone`. |
| Rain sensor | Optional binary sensor. On means skip every zone. |
| Plan hour | Local hour when today's ET and rain are committed (default 23). An automatic run arms at or after this hour. |
| Earliest hour / sunrise buffer | Watering window. The last cycle ends at sunrise minus the buffer (default 30 min). If the hourly forecast is windy at that hour, the deadline moves earlier, and not before the earliest hour. |
| Forecast rain | Wait when probability × amount over the next **48 hours** covers the deficit (or an optional depth). Only slots at or above **60%** count. Wait at most **2** mornings, then water anyway. Forecast rain is never added to the soil bucket. |
| Forecast skip depth | Optional millimeters. Empty means wait only when expected rain covers the deficit. Set it to also wait when expected rain reaches that depth. |
| Freeze skip | Skip watering at or below this air temperature, or the forecast low. Default **40°F**. |
| Freeze alert | On. One notice per cold snap when the forecast low is at or below **32°F** in the next 48 hours. **28°F** uses the hard-freeze wording. |
| Recent rain | Skip when at least this much rain fell in the last N hours. Defaults **2.5 mm** and **12 hours**. |
| Max run per zone | Valve-on minutes for one zone tonight. Default **60**. Soak does not count. The rest stays in the bucket. A zone can set its own number under Hardware; blank uses this. |
| All zones together | Optional. Empty means no hub total. Set it only to cap every zone's valve-on time on the same night. |
| Round minutes | On by default. Off keeps cycle lengths to 0.1 minute. |
| Allowed weekdays | Every day is selected by default. Clear a day to forbid it. An empty selection allows no day. |
| Blackout hours | Optional. The shared timeline stays outside this local hour range. |
| Drip ignores weekdays | Off by default. Buried drip can skip the weekday check. The blackout still clips the shared timeline. |
| Climate sensors | Optional temperature, humidity, wind, pressure, solar radiation, UV, and rain amount. |
| High / low flow | Defaults **+30%** and **−25%** from the learned gallons per minute, after **3** runs. Each alert can notify only, or skip that zone until you reset flow learning. |
| Idle flow | Default **0.5 gal/min** (or about 1 gallon on a volume total) while every zone is off. Notify only, or stop and skip every zone until reset. |
| Cost per 1,000 gal | Optional. Adds a water-cost sensor in dollars. |
| Weekly gallon budget | Optional. One alert per week when use goes over it. |
| Weekly summary | Off. On Monday, at or after the plan hour, one event and a notification if a notify target is set. |

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

Rain kinds: **daily total** replaces today's amount (Tempest rain today). A downward correction only shrinks rain recorded that same day, so a midnight reset does not erase yesterday. **Cumulative** ignores the first sample so history before install is not credited, then adds increases and ignores a counter reset. **Rate** is mm/h, trapezoid-integrated, and gaps longer than 6 hours are dropped. Positive amounts are also kept as events for about 48 hours so the recent-rain skip can see across midnight. Effective rain follows FAO-56: a day below 0.2 × ET0 is ignored inside the bucket. Today's bucket uses the rain sensor only. Forecast rain skips a zone only when you set a threshold.

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
| Flow and area | Optional. Together they override the precipitation preset (`96.25 × GPM / area`). An entered rate still wins. With no area, gallons use the configured GPM, or the learned GPM once it exists |
| Fixed-timer baseline | Blank uses **15 minutes**, **3 days** a week. Gallons saved is that timer minus this week's use. It is a comparison, not a recommendation |

Plant choices cover St. Augustine, Bermuda, Zoysia, Buffalo, a generic warm-season grass, cool-season grass, shrubs, flower beds, vegetables, trees, drip beds, and native plantings. The short tables and the citations are in `docs/design.md`.

| Optional zone field | What it does |
| --- | --- |
| On/off entity | Required for a new zone. `switch`, `valve`, or `input_boolean`. Called with `switch.turn_on` / `turn_off`, `valve.open_valve` / `close_valve`, or `input_boolean.turn_on` / `turn_off`. A zone saved before 0.3.0 without one still loads and is not run. |
| Enabled | Per-zone switch. Off keeps that zone out of the plan and out of run now. |
| Minimum days, target depth, freeze, wind, moisture skip, dormancy lines, winter maintenance, moisture learning | Optional. Blank uses the defaults in the next section. |
| Soil moisture | Relative percent (or a 0–1 fraction) or volumetric water content. **Correct** blends toward the sensor once on the day the bucket commits, weight default 0.5. **Override** replaces the deficit on every update. VWC needs field capacity: deficit = max(0, (θFC − θ) × root depth in meters × 1000). |
| Flow sensor | Any entity, volume total or rate. Records delivered gallons and sets the flow sensor to `pending`, `ok`, `low_flow`, `leak`, `no_data`, or `not_configured`. Default low ratio 0.5, leak ratio 1.5. A flow label does not shut a valve off. If a total rises during a cycle, that gallon increase is what gets credited to the bucket. |
| Zone rain sensor | Binary sensor. On skips that zone. |

## Simulation

A simulation hub is the first menu choice. It does not ask for a weather entity, a sensor, or an on/off entity. Each zone is plant, soil, sprinkler, and sun, plus an optional area and slope. The on/off id is a `simulation.<name>` label. Nothing in the week calls a valve, a switch, an input boolean, or a controller.

The week uses the same functions as a live hub: Penman-Monteith ET0, the soil bucket, `build_zone_request`, and `build_plan`. After a night that would have watered, the planned net depth is subtracted from that zone's simulated deficit. The live bucket is not changed, and the week does not apply the live minimum-interval or dormancy rules.

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

Computed by `run_week`, not typed by hand. Location is the design site: latitude 31.5493, longitude −97.1467, elevation 219 m, America/Chicago. The week starts Monday 13 July 2026, so July's warm-season coefficient is 0.71. The zone is 1000 sq ft. Slope is blank, so clay loam intake is 0.15 in/hr and the max cycle is 7 minutes with a 60 minute soak. The bucket starts full. The schedule is any day, finishing 30 minutes before sunrise. Gallons are gross water from the heads (`runtime × 1.25 in/hr × 1000 sq ft × 0.623`), rounded in the table. Look-ahead is 0 days, so a morning is watered only when the deficit is already at readily available water. This simulation does not apply the 3-day turf interval. Total runtime is 128 minutes. `would_execute` is false.

| Day | Zone | ET0 mm | Rain in | Effective in | Deficit mm | Water | Minutes | Cycles | Start | Gallons | Why |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- | ---: | --- |
| Mon 07-13 | Front lawn | 9.1 | 0.00 | 0.00 | 6.5 | no | 0 | — | — | 0 | Below RAW (deficit 6.5 mm, RAW 10.7 mm). |
| Tue 07-14 | Front lawn | 9.9 | 0.00 | 0.00 | 13.5 | yes | 42 | 7+7+7+7+7+7, soak 60 | Wed 00:21, Wed 01:28, Wed 02:35, Wed 03:42, Wed 04:49, Wed 05:56 | 545 | Due |
| Wed 07-15 | Front lawn | 10.7 | 0.00 | 0.00 | 7.6 | no | 0 | — | — | 0 | Below RAW (deficit 7.6 mm, RAW 9.6 mm). |
| Thu 07-16 | Front lawn | 10.0 | 0.00 | 0.00 | 14.7 | yes | 46 | 7+7+7+7+6+6+6, soak 60 | Thu 23:18, Fri 00:25, Fri 01:32, Fri 02:39, Fri 03:46, Fri 04:52, Fri 05:58 | 597 | Due |
| Fri 07-17 | Front lawn | 9.0 | 0.00 | 0.00 | 6.4 | no | 0 | — | — | 0 | Below RAW (deficit 6.4 mm, RAW 10.9 mm). |
| Sat 07-18 | Front lawn | 8.9 | 0.00 | 0.00 | 12.7 | yes | 40 | 7+7+7+7+6+6, soak 60 | Sun 00:26, Sun 01:33, Sun 02:40, Sun 03:47, Sun 04:54, Sun 06:00 | 519 | Due |
| Sun 07-19 | Front lawn | 8.6 | 0.00 | 0.00 | 6.1 | no | 0 | — | — | 0 | Below RAW (deficit 6.1 mm, RAW 11.1 mm). |

## Turn automatic watering on

The switch is **off** on a new hub and stays **off** when you upgrade. That is deliberate.

1. Update and restart.
2. Open the hub device. Turn on **Automatic watering** (`switch.<hub>_automatic_watering`). A hub named Garden is `switch.garden_automatic_watering`.
3. Leave each zone's **Enabled** switch on. Off removes that zone from the plan and from run now.
4. If the hub mode is Off, turning Automatic watering on sets the mode to Auto and reloads the hub. Notify-only does not block watering once the switch is on.
5. The run arms at or after the plan hour (default 23:00), one zone at a time, and the last cycle ends before sunrise minus the buffer.

**Run now** (the zone button or `smart_water.run_now`) ignores the automatic switch, the allowed days, the minimum interval, and a dormancy stop. It still skips a wet rain sensor, current rain, recent rain, a freeze, high wind, and soil that is wetter than the moisture threshold. It still confirms on and off and it still stops at the max-run cap.

`smart_water.stop_all` turns off whatever this hub left on. Startup does the same for an entity recorded as on, and so does Home Assistant's stop event.

## Watering schedule

The hub sensor **Watering schedule** (`sensor.<hub>_watering_schedule`) lists the next 7 days for every zone. Its state is a short line such as `2 waterings · next 2026-07-15 Front lawn`, or `No watering in the next 7 days`. Attributes:

| Attribute | What it holds |
| --- | --- |
| `days` | One entry per date, and inside it each zone: start times, minutes, inches, millimeters, gallons when the area is known, and the skip reason when it will not run. |
| `markdown` | The same rows as a table. |
| `note` | Later days repeat today's crop ET and assume no rain. |

A markdown card, for a hub named Garden:

```yaml
type: markdown
title: Watering schedule
content: "{{ state_attr('sensor.garden_watering_schedule', 'markdown') }}"
```

**Currently watering** is the zone that is on, or `Idle`. Each zone has a **Last run** sensor (state is the result; attributes are when, minutes, net millimeters, gallons, gallons per minute, and result) and a **Dormancy** sensor (`active`, `slow`, or `dormant`).

### Sample

Computed by `project_week`, not typed by hand. Same design site and the same Monday 13 July 2026 hot-dry day used above (ET0 9.1 mm, Penman-Monteith). St. Augustine, clay loam, spray, full sun, 1000 sq ft, slope blank, July coefficient 0.71, crop ET 6.5 mm, readily available water 10.7 mm. The bucket starts at field capacity (deficit 0; today's ET is already in the deficit the sensor uses, and here that deficit is still 0). Every day is allowed, there is no blackout, and the turf minimum interval is 3 days. Later days repeat that 6.5 mm and add no rain. Each zone is capped at 60 valve-on minutes. The hub total is off. Clock times are local. A long soak sequence can start the evening of the row's date and finish before the next sunrise. The sensor state for this week is `2 waterings · next 2026-07-15 Front lawn`.

```text
Next 7 days. Later days repeat today's crop ET and assume no rain.

| Date | Zone | Starts | Minutes | Depth | Gallons | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-13 | Front lawn | — | — | — | — | Below RAW (deficit 0.0 mm, RAW 10.7 mm). |
| 2026-07-14 | Front lawn | — | — | — | — | Below RAW (deficit 6.5 mm, RAW 10.7 mm). |
| 2026-07-15 | Front lawn | 00:23, 01:30, 02:37, 03:44, 04:51, 05:58 | 41 | 0.51 in (13.0 mm) | 532 |  |
| 2026-07-16 | Front lawn | — | — | — | — | Below RAW (deficit 6.5 mm, RAW 10.7 mm). |
| 2026-07-17 | Front lawn | — | — | — | — | Minimum 3 days between waterings (2 since the last run). |
| 2026-07-18 | Front lawn | 21:06, 22:13, 23:20, 00:27, 01:34, 02:41, 03:48, 04:55, 06:01 | 60 | 0.75 in (19.1 mm) | 779 | 1 min carries to the next allowed day. |
| 2026-07-19 | Front lawn | — | — | — | — | Below RAW (deficit 6.8 mm, RAW 10.7 mm). |
```

July 17 is already past readily available water and is still skipped, because the last run was only two days earlier. July 18 is the night that used to show 61 minutes. It now stops at 60. The leftover minute would leave the bucket below readily available water, so July 19 does not schedule a one-minute run.

### Three zones, one morning

Same site, same Monday evening, ET0 9.1 mm. Deficits are set so each zone is already due (no week of accumulation). Slope is blank. No blackout, every day allowed. Each zone may use 60 valve-on minutes. The hub total is off, so this morning is not trimmed to 60 altogether. Sunrise minus 30 minutes is 06:03.

| Zone | Plant, soil, sprinkler | Area | Deficit | RAW |
| --- | --- | --- | --- | --- |
| Front lawn | St. Augustine, clay loam, spray | 1000 sq ft | 11.2 mm | 10.7 mm |
| Back lawn | St. Augustine, sand, spray | 600 sq ft | 6.0 mm | 5.4 mm |
| Vegetable bed | Vegetable, sand, spray | 200 sq ft | 9.0 mm | 8.2 mm |

Clay loam soaks 60 minutes, so the other two zones run inside that gap. One valve is on at a time. Valve-on time is 35 + 19 + 28 = 82, and no zone is over 60. The sensor state is `10 waterings · next 2026-07-13 Back lawn`. The first morning is:

```text
| Date | Zone | Starts | Minutes | Depth | Gallons | Note |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-07-13 | Back lawn | 01:35 | 19 | 0.24 in (6.0 mm) | 148 |  |
| 2026-07-13 | Front lawn | 01:28, 02:35, 03:42, 04:49, 05:56 | 35 | 0.44 in (11.2 mm) | 454 |  |
| 2026-07-13 | Vegetable bed | 01:54 | 28 | 0.35 in (9.0 mm) | 73 |  |
```

Clock order, local time on 14 July:

| | |
| --- | --- |
| 01:28–01:35 | Front lawn, 7 min |
| 01:35–01:54 | Back lawn, 19 min, during the front soak |
| 01:54–02:22 | Vegetable bed, 28 min, still inside that soak |
| 02:35–02:42 | Front lawn, 7 min |
| 03:42–03:49 | Front lawn, 7 min |
| 04:49–04:56 | Front lawn, 7 min |
| 05:56–06:03 | Front lawn, 7 min, ending at sunrise minus the buffer |

## Flow

Each zone can learn its normal gallons per minute from the flow sensor while it runs. The estimate is the median of the last 12 runs. A run more than twice the median, or under 0.4 times it, is reported and left out of the median. Alerts start after 3 runs (change that on the hub).

| Alert | Default | What it means |
| --- | --- | --- |
| High flow | +30% | Broken head or a leak in that zone. |
| Low flow | −25% | Clog, stuck valve, or low pressure. |
| Idle flow | 0.5 gal/min, or about 1 gallon on a volume total, while no zone is on | Main-line leak. |

Each alert is **Notify only** or **Stop and skip until reset**. Notify is the default. Stop on a zone skips that zone. Stop on idle flow skips every zone. `smart_water.reset_flow_learning` clears the samples, the alert, and the skip. Leave the zone empty to reset the hub. The event is `smart_water_flow_alert`. A repair is raised with the same sentence. A notify target, if set, gets it too.

Sensors: **Learned flow**, **Last run flow** (gal/min), and the existing **Flow** status (`learning`, `ok`, `high_flow`, `low_flow`, `main_leak`). With no area, gallons use the learned rate once it exists. An entered rate still wins over flow and area. Area still wins over GPM for the gallon estimate.

## Water use

Each zone and the hub have a **Water use** sensor: lifetime gallons, `state_class: total_increasing`, unit `gal`, device class water, so the Home Assistant water dashboard can track it. Today, this week, and this month are attributes. They are sums of a date log and are not the long-term statistic, because a counter that resets cannot be `total_increasing`.

Gallons come from the flow sensor when it moved during the cycle. Otherwise they are the computed amount (precipitation × area, or GPM × minutes when there is no area).

**Water saved** is this week's gallons versus the fixed timer (default 15 minutes, 3 days a week). Positive means the plan used less than that timer. It can be negative. **Water cost** exists only after you set a price per 1,000 gallons. It is lifetime dollars, `total_increasing`.

An optional weekly gallon budget fires `smart_water_budget_alert` once per ISO week. **Weekly summary** is off until you turn it on. It fires `smart_water_weekly_summary` on Monday at or after the plan hour, once per week, and notifies when a notify target is set.

## What a run does

Once per local day, at or after the plan hour, each zone's bucket is updated:

`Dr = Dr + ETc − rain − irrigation` (FAO-56 style), clamped to total available water. Rain below 0.2 × ET0 is ignored. A finished cycle credits the bucket from the minutes the valve was actually on (net millimeters = minutes/60 × precipitation rate × efficiency × 25.4), or from the flow-total increase when that sensor moved. Calling `calculate_plan` before the plan hour commits that day's ET early; the evening update will not apply it twice. If automatic watering is on, that same refresh arms the night's cycles.

A zone is due when its deficit has reached readily available water (RAW), or a target depth you set. It is not watered a day early. Turf then waits at least 3 days, shrubs and trees 7, vegetables and flowers 2. The scheduled depth is the current deficit times the adjustment percent. Runtime is `60 × (net inches / efficiency) / precipitation rate`, whole minutes unless you turn rounding off. Efficiency is the sprinkler preset (spray 0.60) unless the zone stored an override. Zones created before 0.3.0 stored 1.0.

Max cycle length is `floor(60 × NRCS intake in/hr / precipitation rate)`. Example: clay loam on a 5–8% slope (0.10 in/hr) at 1.5 in/hr is a **4 minute** cycle and a 20 mm deficit is **31 minutes**. One valve at a time. Zones are ordered by priority, then by a longer soak, then by name, so one zone's soak can hold another's cycle. The timeline is shifted so the last cycle ends at sunrise minus the buffer. The hourly forecast (`weather.get_forecasts`, type `hourly`) can move that deadline earlier when the dawn hour is at or above the strictest wind limit of the zones that will run. Drip and bubbler do not tighten it. It never moves earlier than the earliest hour. Only tonight uses that forecast; later days in the week sensor are not given invented wind.

The cap (default 60) is valve-on minutes for one zone tonight. Soak does not count. A zone can override it under Hardware. An optional hub total, off unless you set it, caps every zone together after each zone's own cap. The planner keeps the earliest cycles that fit, then shifts them so the last kept cycle still ends at the deadline. Minutes that do not run stay in the bucket. If the zone is still at readily available water, the next allowed day can finish them. If the partial night drops the deficit below that line, the minimum interval starts and the leftover minute does not come back as its own run. A schedule note looks like `Deferred for forecast rain (70% / 0.4 in).` when confident rain covers the deficit. That depth is not subtracted from the bucket. If the rain sensor does not record it, the next window waters once the wait (default 2 mornings) is over.

Just before each cycle the executor checks rain since the plan was armed, the skip rules, the time left in the window, and the remaining max-run budget. Each on or off command is confirmed against the entity state and retried up to three times.

ET0 uses FAO-56 Penman-Monteith when humidity and wind are available. Daily solar radiation is the integrated W/m² (or a daily MJ/m² sensor) when that total is above zero, otherwise the Hargreaves radiation estimate. Temperature-only days use Hargreaves ET0. A temperature sensor replaces the forecast high and low once the observed range is at least 0.5 °C, so one reading cannot zero the radiation estimate. Missing temperatures produce no ET0 and the bucket is left alone.

### Skip, dormancy, and learning defaults

| Rule | Default | Source |
| --- | --- | --- |
| Freeze | At or below 40°F, current temperature or forecast low. Missing temperatures do not skip. | Oklahoma State University HLA-6610, "Do not water when temperatures are below 40°F". https://extension.okstate.edu/fact-sheets/lawn-watering-tips.html |
| Recent rain | 2.5 mm (0.1 in) in the last 12 hours, plus a wet rain sensor. | Practical default. HLA-6610 says not to water when rain is present and does not publish a duration or a depth. |
| Wind | Spray 10 mph, MP rotator 12, rotor 15, drip and bubbler not skipped. Sustained wind at or above the limit. No reading means do not skip. | HLA-6610 says not to water in high wind and publishes no speed. University of Florida overhead guidance treats wind above about 10 mph as unsuitable. The Irrigation Association 2013 wind paper shows smaller droplets drift more. 12 mph for MP rotators is the midpoint of spray and rotor; no MP-specific cutoff was found. |
| Moisture | Skip when the sensor is fuller than `1 − p` (still wetter than MAD). | The depletion fraction already used for RAW. Override with a percent on the zone. |
| Forecast rain | Expected rain (probability × amount) over 48 hours, counting slots at or above 60%. Wait up to 2 mornings when that covers the deficit, or an optional depth. | The schedule sentence is `Deferred for forecast rain (70% / 0.4 in).` Forecast depth is never a bucket credit. Measured rain still uses the rain sensor. |
| Freeze alert | On. Forecast low at or below 32°F within 48 hours. Hard freeze at or below 28°F. | Separate from the 40°F watering skip. One event, repair, and notification per cold snap. |
| Dormancy | 7-day mean of daily mean air temperature, after at least 3 days. Warm-season (Bermuda, Zoysia, Buffalo, generic): slow below 55°F (crop ET × 0.5), dormant below 50°F (no regular irrigation). St. Augustine: slow below 60°F, dormant below 55°F. Cool-season: slow when the mean is at or above 80°F, no temperature-only full stop. Other plants stay active. | Texas A&M Forage Fax / Mississippi State: bermuda and bahia stop shoot growth below 50°F, and rhizomes and stolons need soil above about 55°F. https://foragefax.tamu.edu/impact-of-sub-freezing-temperatures-on-warm-season-perennial-grasses/ AgriLife Water-Wise Checklist: turn irrigation off when dormant, deep and infrequent, about 6 inches, no more than once or twice a week. https://aggieturf.tamu.edu/wp-content/uploads/sites/24/Water-Wise-Checklist-for-Texas-Home-Lawns-1.pdf AgriLife St. Augustine management: best growth 80–95°F, turn water off in winter. https://mytexas.ag.tamu.edu/publications/st-augustinegrass-lawn-management/ AgriLife dormant sodding: St. Augustine and centipede are the most winter-injury susceptible, then bermuda, zoysia, buffalo. The St. Augustine lines are 5°F higher from that ranking, not a separate published cutoff. Buffalo uses the group 50/55 lines. https://aggieturf.tamu.edu/wp-content/uploads/sites/24/Dormant-Sod.pdf UNL G2191: above 80°F reduces cool-season survival. https://extensionpubs.unl.edu/publication/g2191/2013/html/view The 7-day air mean is a proxy. There is no soil-temperature sensor. |
| Winter maintenance | Off. If you turn it on: every 21 days, 0.25 in, only while dormant, at RAW, and under the recent-rain limit. | AgriLife says turn irrigation off when dormant. The depth is the low end of the UNL 1/4–1/2 inch survival watering. |
| Deep and infrequent | Due at RAW (or your target depth), not a day ahead. Turf interval 3 days, shrubs, trees, native, and drip beds 7, vegetables and flowers 2. A zone that has never been watered is not blocked by the interval. | AgriLife: about 6 inches, no more than 1–2 times a week. Three days is the short end of twice a week. |
| Moisture learning | On when a sensor is set. The available-water factor starts at 1 and moves by `0.05 × (sensor full − model full)`, clamped to 0.7–1.3. Confidence reaches 1 after 14 samples. Skipped when rain today is at least 2.5 mm, and on the watering day and the day after. One update per day, applied to the next plan. `smart_water.reset_learning` sets it back to 1. | The bounds and the step are engineering limits, not an agronomy citation. The factor is not written into the available-water override. |

## Services

| Service | Effect |
| --- | --- |
| `calculate_plan` | Commit today's balance if needed, then rebuild the plan. If automatic watering is on, this can arm tonight's run. |
| `reset_bucket` / `set_bucket` | Deficit 0, or an absolute deficit clamped to total available water. |
| `mark_watered` | Credit net irrigation already applied. Empty depth refills the bucket. |
| `skip_zone` | Skip through a date. Default is the next local morning. |
| `pause_zone` | Skip N local days. Zero clears the pause. |
| `set_adjustment` | Percent of the calculated depth. 100 is unchanged. 0 keeps the zone off the timeline. The number entity does the same thing. |
| `run_now` | Runs that zone's cycle-and-soak now, even when automatic watering is off. Credits the bucket from the time it actually ran. |
| `stop_all` | Turns off the entity this hub turned on. |
| `reset_learning` | Sets that zone's moisture factor back to 1 and clears its confidence. |
| `reset_flow_learning` | Clears learned flow, the alert, and a skip that is waiting for reset. An empty zone resets the whole hub. |
| `start_audit` | Runs one zone for the minutes you pass, as a manual run. Freeze, wind, rain, moisture, and the zone cap still apply. |
| `submit_audit` | Cup readings in inches, or millilitres plus a cup diameter. Stores the measured rate and scheduling efficiency. |
| `simulate` | Plays a weather week through the planner and returns it. Does not change the stored deficit and does not call an on/off entity. |

A zone is usable when Home Assistant already exposes it as a valve, switch, or input boolean. Your existing controller schedule is unchanged. If it still waters at dawn, Smart Water will not stop it.

## Entities

Per zone: deficit, readily available water, next planned run, plan reason, plan (scheduled or idle, with runtime, cycles, adjustment, sprinkler, and the on/off entity), flow status, learned flow, last-run flow, water use, water saved, moisture deficit, last run, dormancy, an adjustment number (0–300%), a run-now button, and an enabled switch.

Hub: mode, tonight's plan, today's ET0, rain today (effective rain and whether it was ignored), next run (allowed days, blackout, whole-minute rounding), watering schedule, currently watering, water use, water saved, water cost when a price is set, and the Automatic watering switch. A simulation hub also has a Simulation sensor and a Run simulation button.

Bucket state, the day's weather accumulation (including rain events), flow totals, adjustment, last run, the learned factor, and the last plan are stored and survive a restart. Storage version stays 1; new keys are filled in when an older file is loaded. On startup, an entity this hub recorded as on is turned off.

## Dashboard card

The integration serves a Lovelace card and registers it when the frontend is loaded. After a restart, add a card and choose **Smart Water**, or use YAML:

```yaml
type: custom:smart-water-card
entity: sensor.garden_watering_schedule
```

`entity` is the hub watering-schedule sensor. The name follows the hub, so a hub named Garden is `sensor.garden_watering_schedule`.

The card shows each zone's soil-water bar (bucket percent, with a tick at readily available water), the next run and its minutes, the last run, a 7-day soil chart, the skip reason, and Run now, Skip, and Pause buttons. The hub row has the Automatic watering toggle, what is watering now, this week's gallons and gallons saved, and alerts. The editor is a schedule-entity list and a history checkbox.

If the card does not appear, add a dashboard resource by hand: **Settings → Dashboards → Resources → Add resource**, URL `/smart_water_static/smart-water-card.js`, type **JavaScript module**. The markdown card above still works and does not need the custom card.

## Catch-cup audit

`smart_water.start_audit` runs one zone for the minutes you choose. It is a manual run: it ignores the automatic switch, allowed days, the minimum interval, and dormancy, and it still stops for a freeze, wind, rain, a wet soil sensor, or the zone's runtime cap. It is one continuous run, not cycle-and-soak. Put cups out before you start it.

Use at least 4 cups. Eight is a better short test. Sixteen in a grid is better. Space them evenly between the heads, in the overlap and in the gaps, and include cups that stay dry. Those zeros count. Sprays need about 10 minutes. Rotors need 15–20 so the cups collect a measurable depth.

Then call `smart_water.submit_audit` with the readings. Inches need no diameter. Millilitres need the inside diameter of the cup. The result is the precipitation rate in inches per hour, the low-quarter distribution uniformity (average of the lowest quarter of the cups, divided by the average of every cup), and the scheduling efficiency, which is that same fraction. Both the rate and the efficiency are stored on the zone as overrides, marked **measured** next to the sprinkler preset, and the last 12 audits are kept.

## Develop

```bash
python3 -m pytest
```

Math tests do not import Home Assistant. Config-flow tests need `pytest-homeassistant-custom-component` matching Home Assistant 2026.10 and serialize every form the way the config HTTP API does.

## Limits

- The dashboard card loads with the frontend. A markdown card can still show the watering schedule or the simulation sensor's `markdown` attribute.
- A flow alert notifies, or skips until you reset it, according to the hub action. It does not change another integration's own schedule.
- Sunrise is a civil approximation (about ten minutes), not a weather-service sunrise.
- Soil, plant, sprinkler, and sun are chosen per zone. Slope and the other derived numbers are presets until overridden.
- Drip can ignore weekdays only. The blackout is shared by every zone on the timeline.
- Daytime `calculate_plan` commits a full day of ET if today's balance has not run yet, and it can start watering when automatic watering is on.
- The 7-day schedule repeats today's crop ET and assumes no future rain. A skip on a later morning can move the real run.
- Dormancy uses air temperature, not soil temperature.
