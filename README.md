# Sprinklecast

![Sprinklecast](custom_components/sprinklecast/brand/logo.png)

Work in progress, not ready for general use.

Water-balance planner and zone controller for Home Assistant (`sprinklecast` 0.15.0).

It estimates reference evapotranspiration, tracks a soil-water deficit for each zone, and builds a cycle-and-soak plan for the next morning. The plan is made at the plan hour (default 23:00). A new hub turns **Dynamic start time** on: the run aims to finish at that day's local sunrise, and it never opens before **Don't start before** (default 04:00). If that is still too early, it starts then and may run past sunrise, but it ends by the finish time (default 09:00). Turn Dynamic start time off to open at the start time (default 05:00) instead. **Automatic watering is off after a new install.** An upgrade keeps that switch as it was, unless the old Mode was Off. Turn the hub's **Automatic watering** switch on when you want it to open valves. Until then the plan is only sensors and an optional notification. Run now is a manual action and runs even while that switch is off. A simulation hub still plays an example week and never calls a real on/off entity. The controller calls `switch`, `valve`, or `input_boolean` services only. It does not call a controller API.

The formulas follow FAO-56 (Penman-Monteith, the soil-water bucket, and the depletion fraction) and the NRCS maximum sprinkler application rates by soil and slope. Plant, soil, and sprinkler defaults, each with a source, live in `presets.py`. `docs/design.md` is the design note.

## Glossary

The screens use plain names. The technical term is here so a manual or a forum post still makes sense. Entity ids are unchanged.

| On screen | Also called | What it means |
| --- | --- | --- |
| Soil water | Bucket, percent full | How full the root zone is, from 0% to 100%. The sensor is read-only. |
| Soil water level | | The number you set, 0–100%. It writes how full the soil is. Soil water shows the same percent. |
| Water needed | Deficit, Dr | How much water the root zone is missing. |
| Soil moisture level | Moisture sensor | The raw reading from a soil sensor, in percent. Water needed stays the calculated amount. |
| Watering point | RAW, readily available water | How dry the soil may get before a watering. |
| Water loss today (reference lawn) | ET0 | How much water a reference lawn would lose today. |
| Plant water use | ETc, crop ET | Water loss today times the plant factor. |
| Plant water use factor | Kc, crop coefficient | How fast this planting uses water compared with a reference lawn. |
| Allowed dry-out | MAD, management allowed depletion | The fraction of soil water that can be used before watering. |
| Water the soil can hold | AWC, TAW | Inches of water an inch of soil can store, and the total in the root zone. |
| Distribution uniformity | DU_lq | From a catch-cup test: the driest quarter of cups divided by the average cup. |
| Catch-cup depth | Precipitation rate | The average depth the cups caught. Sprinklecast turns that into inches per hour and stores it on the zone. |
| Baseline flow | | The gallons per minute from Learn flow rates, or a number you set. Until then it shows the learned flow and says so. |
| Evening plan hour | Plan hour | When today's water loss is saved and the morning plan is built. Default 23:00. |
| Dynamic start time | | On for a new hub. The morning aims to finish at local sunrise. The start is sunrise minus every cycle and soak. |
| Don't start before | Earliest start | Hard limit. Watering never starts earlier than this. Default 04:00. |

## Install on Home Assistant OS

Requires Home Assistant **2025.3** or newer (config subentries). Tested on **2026.10.1**. No extra Python packages. Number selectors use a step of at least 0.001, or `"any"` for latitude and longitude.

### HACS custom repository

1. HACS → Integrations → ⋮ → Custom repositories.
2. Add `https://github.com/Hestand/hx-garden-utils` as category **Integration**.
3. Download **Sprinklecast** (release `v0.15.0`), then restart Home Assistant.

`hacs.json` is included. This is not in the default HACS store.

### Manual copy

Copy the integration folder onto the HA config share:

```text
config/custom_components/sprinklecast/
```

That directory must contain `__init__.py` and `manifest.json`. Restart Home Assistant. Settings → Devices & services → Add integration → **Sprinklecast**.

### Upgrade from Smart Water (0.11.1 and earlier)

This release keeps the Sprinklecast name and the `sprinklecast` domain. HACS installs only one folder from `custom_components`. This repository ships `custom_components/sprinklecast` only.

HACS reads the manifest before it deletes a download. After the repository lists **Sprinklecast**, HACS → Remove deletes `config/custom_components/sprinklecast`, not `config/custom_components/smart_water`. The old folder stays and keeps loading. Do not use HACS Remove once the repository shows Sprinklecast.

Your config entry, zones, stored soil and flow history, and entity IDs stay. Do this once:

1. Leave the Smart Water config entry in place (for example **Water Test**). Do not delete it. Deleting it removes the zones and the stored history.
2. While HACS still shows **Smart Water**, use HACS → Integrations → Smart Water → ⋮ → Remove. That deletes `config/custom_components/smart_water`. Config entries, `.storage`, and the entity registry stay. If the repository already shows Sprinklecast, skip HACS Remove and delete `config/custom_components/smart_water` by hand with the File editor or Samba.
3. HACS → Integrations → ⋮ → Custom repositories. Remove `https://github.com/Hestand/hx-garden-utils` if it is still listed.
4. Add `https://github.com/Hestand/hx-garden-utils` again as category **Integration**.
5. Download **Sprinklecast** (release `v0.15.0`).
6. Restart Home Assistant.
7. Settings → Devices & services → Add integration → **Sprinklecast** → **Import my Smart Water setup**. No YAML is required. That copies data, options, zone subentries, and the `.storage` file (`smart_water.<entry id>` becomes `sprinklecast.<new id>`), including each zone's soil water and history and the Automatic watering switch. Devices and entity registry rows move. Entity IDs stay the same. The old config entry is removed.
8. If you added `sprinklecast:` to `configuration.yaml` so an older build would start, remove that key after the import. An empty `sprinklecast:` is accepted and does nothing else.
9. If a repair says the old folder is still there, submit it. Sprinklecast deletes `config/custom_components/smart_water` and asks you to restart. If Smart Water is still loaded, the copy waits until that restart. Then add Sprinklecast again and choose Import my Smart Water setup.
10. Services are `sprinklecast.*`. The old `smart_water.*` service names still call the same handlers. Event names stay `smart_water_flow_alert`, `smart_water_budget_alert`, `smart_water_weekly_summary`, and `smart_water_freeze_alert`.
11. The dashboard card type is `sprinklecast-card` (`/sprinklecast_static/sprinklecast-card.js`). An existing `smart-water-card` resource at `/smart_water_static/smart-water-card.js` still loads.

The hub **Mode** option and the Mode sensor are gone. **Automatic watering** is the only on/off for valves. If Mode was Off, automatic watering is stored off. Notify only and Auto leave that switch as it was. **Send plan notifications** is on when a notify service was set, and the evening plan is sent even while automatic watering is off. The recent-rain skip is gone. Measured rain still fills the soil bucket. A wet rain sensor, rain right now, and a confident forecast still pause or defer watering.

New entity: `calendar.<hub>_watering` (name **Watering**), for example `calendar.water_test_watering`. Removed entity: the Mode sensor (`sensor.<hub>_mode` or a renamed id). Its registry row is deleted.

### Already on Sprinklecast 0.14.8

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. Setting several zones' catch-cup depth, soil water level, or adjustment at the same time saves each one. The hub does not reload between them. **Learn flow rates** is a hub button only when a flow meter is set. It runs each enabled zone for 5 minutes after the flow meter rises (Learn flow minutes on the hub). The valve entity is not the clock: it can report open a few minutes after the water is already moving, and stay open after the meter has fallen. A meter that updates about once a minute keeps the zone on until two readings from the middle of the run are in, and the peak of those is Baseline flow (source `flow_learning`). The next zone waits until the meter falls near zero. No flow within the wait fails that zone. Watering now says Learning flow rates while it runs. A second press is ignored. Stop all watering cancels it. A catch-cup test no longer sets that baseline. It measures cup depth and credits the soil. **Flow check** is replaced by **Flow problem** (off is normal, on is outside the saved baseline). With no baseline yet it stays off, and a restart keeps the last result. A repair notes that the old sensor was removed. **Learned flow** and **Flow trend** are removed. **Baseline flow** is the expected rate: the catch-cup or saved baseline, or the rate learned from normal runs when none is saved (source `learned`). The trend status, drift, and sentence are attributes on Flow problem. **Watering schedule** keeps the date, start time, and each zone's minutes so Home Assistant can record it. Cycle times, reasons, and the markdown table are in the diagnostics download. The dashboard card shows one row per zone with its minutes. Restart after the update.

### Already on Sprinklecast 0.14.7

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. A catch-cup or normal run measures flow while the meter is up, after a short settle, instead of averaging the start and end of the scheduled clock. The window starts when the meter rises and ends when it falls, including flow from before the valve entity reports open. That entity is the fallback only when the hub has no flow sensor. The next zone waits for the meter to fall, and each catch-cup zone runs for 15 minutes from the command. A second press does not restart the test. Applied water is credited from the zone's current rate, then replaced when you enter the cup depth. If a catch-cup baseline was saved by an older version and recorder history is still there, it is recomputed on startup. Otherwise the number stays and a repair asks you to run the test again. **Flow trend** says the baseline is set and how many normal runs the trend still needs. Restart after the update.

### Already on Sprinklecast 0.14.6

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. A hand-set soil level is a one-time adjustment: it sets the bucket at that moment and does not skip the day. The full day's water loss still applies once, not a prorated remainder. If Home Assistant was down at the usual evening step, the missed days are applied on the next start, each day once. That includes 2026-10-19 on an install that set the soil level that afternoon. The soil water sensor is named **Soil moisture**. The hub adds **Average soil moisture**. Restart after the update.

### Already on Sprinklecast 0.14.5

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. Today's water loss is the calendar day's totals from recorded history: high and low temperature, mean humidity, mean wind, mean pressure, and the solar integral. A restart reads that same history. A finished day stays locked. The watering plan and the days past the forecast use that locked average, not the live reading. Restart after the update.

### Already on Sprinklecast 0.14.4

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. A restart no longer saves today's water loss from whatever sensors have loaded in the first seconds. Sprinklecast waits until Home Assistant has started, then recomputes water loss, the watering point, and the next watering when the configured sensors are available. Restart after the update.

### Already on Sprinklecast 0.14.3

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. A sensor that has not loaded yet, or is unavailable, no longer opens a unit repair. Sprinklecast waits until Home Assistant has started, then checks again when the sensor's state changes. A repair still opens when the sensor has a real state and the unit is missing or not accepted, and it clears when the unit becomes valid. Restart after the update.

### Already on Sprinklecast 0.14.2

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. The rain sensor also accepts a rain-rate sensor (`in/h` or `mm/h`). A rate above the optional threshold (default 0, in that sensor's units) counts as raining. A numeric sensor with a missing or unrecognized rate unit is ignored, and a repair stays open until the unit is valid. An existing on/off rain sensor still means raining when it is on. Restart after the update.

### Already on Sprinklecast 0.14.1

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. A sensor whose unit is missing or not in the accepted list is ignored, and a repair names that sensor until the unit is one Sprinklecast converts. Restart after the update.

### Already on Sprinklecast 0.14.0

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. There are no new entities and no storage change. Restart so the setup and options forms show the sensor names and units. A sensor with a missing or unknown unit is ignored until you set a unit Sprinklecast converts.

The catch-cup and soil-water notes below still apply if you have not done them.

### Already on Sprinklecast 0.13.0

Update to `v0.15.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

Nothing is imported again. Config entry version stays 10. Learned flow, soil water, and the automatic switch stay as they are.

A flow baseline is empty until you learn one. Until then, flow alerts keep using the learned rate, and **Baseline flow** says the source is learned. With a flow meter set, press **Learn flow rates** (or call `sprinklecast.learn_flow_rates`) when you want a permanent baseline. Put cups out and press **Run catch-cup test** when you want the precipitation rate. After you change nozzles, learn the flow again.

If you have not yet turned **Automatic watering** back on after 0.12.0, or set **Soil water level** after a bucket reset, do that too. See the 0.12.0 notes below.

### Already on Sprinklecast 0.12.0

Update to `v0.13.0` from HACS. That updates `config/custom_components/sprinklecast`. Do not remove Sprinklecast in HACS.

If `config/custom_components/smart_water` is still there, submit the repair **Delete the old Smart Water folder** and restart, or delete that folder with the File editor or Samba. Do not use HACS Remove for this. After the repository lists Sprinklecast, HACS Remove deletes the Sprinklecast folder.

Remove `sprinklecast:` from `configuration.yaml` if you added it to start 0.12.0. The hub is already imported, so that key is unused.

0.12.0 turned **Automatic watering** off even when Mode was Auto or Notify only. Turn the switch back on if you still want it to open valves.

0.12.0 could also replace each zone's stored soil water with an empty bucket, so every similar lawn showed the same percent (about 96% after one day's water loss) and the next watering moved later. 0.13.0 keeps the bucket when it imports. It cannot restore a hub that 0.12.0 already imported. Set each zone's **Soil water level**, or copy the old `deficit_mm` values out of a backup of `.storage/smart_water.<old id>` if you have one.

### Upgrading from 0.5.x, 0.4.x, 0.3.x, 0.2.x, or 0.1.x

Download 0.15.0 and restart. A Sprinklecast entry stays on config entry version 10. A Smart Water entry follows the steps above. 0.11.1 lists the next watering days on the schedule sensor and the dashboard card: one day for each allowed weekday, however far out, instead of seven calendar rows that are mostly not dry enough. Each of those days is the full morning plan. A day past the weather forecast sets `estimated`; the date and time stay exact. The bucket is refilled in the projection, so the second and third days follow the water that was already applied. The config entry moves to version 9 and writes **Dynamic start time** off, so an existing hub keeps opening at its start time until you turn the option on. A new hub defaults that option on. Clay, clay loam, and compact silt loam now soak 30 minutes unless the zone stored its own soak; a blank Soak field uses that preset. Bug-fix releases bump the patch number (0.10.0, then 0.10.1). Releases with new features bump the middle number (0.10, then 0.11). 1.0.0 is reserved for the true release. 0.10.1 keeps a short run on the configured start time. Soak time between cycles does not move that start earlier. A run whose valve time cannot finish by the finish time may still open as early as the earliest start, and the rest waits. The dashboard card shows the next watering as a date and time, such as Thu Nov 5, 5:00 AM. 0.10.0 keeps the morning window on the wall clock in Home Assistant's time zone, including the mornings when daylight saving starts or ends. A 05:00 start stays 05:00 local. Next watering is an exact local date and time, such as Sun Nov 1, 5:00 AM. Whether that date is past this week stays an `estimated` attribute and is not written into the text. The projection looks out up to a year, using the forecast and then the recent water-loss average, so a deep bed still gets a date. A disabled zone, or a zone that stays dormant for that whole year, stays unknown and the note says why. The hub's next watering is the earliest enabled zone. 0.9.0 projects the next watering out to about 60 days, so the date stays filled when nothing is due this week. The flow meter moves to the hub: one sensor, and a required choice of whole-home or irrigation-only. A whole-home meter does not alert while nothing is running. An existing per-zone flow sensor is copied onto the hub as irrigation-only, and the zone copy is removed. You are not asked to run setup again. Soil moisture level shows the sensor's own percent. That entity, and the flow entities, are created only when the sensor is set. The config entry moves to version 8. 0.8.1 renames the sensors and settings into plain English. Entity ids and history stay the same, because the unique ids did not change. Reference water loss and other technical sensors move to the diagnostic section, so the device page leads with soil water, the next watering, the last run, and water used. 0.8.0 replaces the sunrise deadline with a morning window: start at **05:00**, finish by **09:00**, and start no earlier than **04:00**. A sequence that does not fit 05:00–09:00 may start earlier, down to 04:00, and the rest stays in the bucket for the next allowed day. An allowed day is the morning the valves open. Existing hubs pick up these times on restart. They are not asked to run setup again, zone data is not rewritten, and the stored bucket (storage version 1) is kept. **Automatic watering stays off.** 0.7.2 dated each schedule row by the morning the valves open. 0.7.1 fixes forecast temperatures: a weather entity that reports °F (or °C) no longer crashes setup on the freeze check. New hubs ask how many zones to add during setup. An existing hub is left as it is. **Automatic watering stays off** until you turn the switch on, including when an older hub had dry-run off. A hub that already chose its watering days keeps those days. The old all-zones runtime cap becomes the per-zone default (a stored 60 stays 60 minutes per zone). The new hub nightly total stays off. A simulation hub is a new entry from the first menu, or an existing simulation hub keeps working and still does not call a real entity.

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

1. Settings → Devices & services → Add integration → **Sprinklecast**.
2. Choose **Live hub** or **Simulation hub**. A simulation needs no weather entity and no on/off entity. See [Simulation](#simulation).
3. On a live hub, name it. Pick a weather entity, or open **Sensors** and pick a temperature sensor. A Tempest (or WeatherFlow) station is filled in when Home Assistant has exactly one. **Morning watering** is already open: Dynamic start time is on, Don't start before is 04:00, and Finish by is 09:00. Location and schedule can stay collapsed.
4. **How many zones?** Default is 1. Zero creates the hub with no zones. Then, for each zone, enter the name, the on/off entity on a live hub (`switch`, `valve`, or `input_boolean`), and plant, soil, sprinkler, and sun. After the first zone, those four start filled in from the previous zone. Change any of them; what you submit is what is saved. The name and on/off entity are always this zone's own.
5. Advanced is not part of that loop. Open the zone afterward and leave the Advanced fields blank. Blank means the preset. A bubbler has no published precipitation rate, so enter a rate or both flow and area there.

Add, edit, or remove zones later from the hub's device page. Options edits the sensors and the schedule. Reconfigure edits the hub name and weather entity. Existing hubs are not asked to run this again.

## Configure

Add the integration once. After the hub form, it asks how many zones, then each zone's quick fields. More zones are added from the hub's device page (Add zone). Options and zone reconfigure edit the same fields. Removing a zone is the device-page delete.

### Hub

The first step is a menu: **Live hub** or **Simulation hub**. The live form is the whole hub. Name is required. Weather is required only when no temperature sensor is set. **Morning watering** is open. **Sensors** and **Location and schedule** are collapsed sections. The same morning fields are in hub options.

| Setting | Notes |
| --- | --- |
| Name | Device name. |
| Weather entity | Optional if a temperature sensor is set. Daily and hourly forecasts come from `weather.get_forecasts`. Temperatures are converted from the entity's unit (°F or °C) before the freeze check. Entity sensors win when they are set. |
| Elevation (m) | Atmospheric pressure when no pressure sensor is set. Default **219 m** is the design site (USGS ~218.6 m). Home Assistant's elevation of 0 is wrong for ET. |
| Latitude / longitude | Optional override. Blank uses the HA location. Step is `any` so 2026.10 accepts full precision. |
| Send plan notifications | On by default, and on after an upgrade when a notify service is set. Sends the evening plan even while Automatic watering is off. Freeze, flow, and budget notices are separate. |
| Notify target | Optional, `notify.mobile_app_phone` or `mobile_app_phone`. |
| Rain sensor | Optional. An on/off sensor that is on, or a rain-rate sensor above the threshold, skips every zone. | 
| Rain rate threshold | Optional. Default 0, in the rain sensor's own units. A numeric rate above this counts as raining. An on/off sensor ignores it. |
| Plan hour | Local hour when today's ET and rain are committed (default 23). The run itself is the next morning. An automatic run arms at or after this hour. |
| Dynamic start time | On for a new hub. The run aims to finish at local sunrise for that calendar day. The start is sunrise minus every cycle and soak. If that would be earlier than Don't start before, watering starts then and may run past sunrise, but it still ends by Finish by. Anything left waits for the next allowed day. Off uses Start time, and cycles that would pass Finish by wait. An upgraded hub is set to off. |
| Don't start before | Hard limit. Default **04:00**. Watering never starts earlier than this, with dynamic start, a fixed start, the projection, or a later morning catching up minutes that did not fit. What still does not fit waits. |
| Finish by | Latest the run may end. Default **09:00**. With dynamic start on, this is the buffer after sunrise. It never runs later. |
| Start time | Used only when Dynamic start time is off. Default **05:00**. Hidden while dynamic start is on. A stored time is kept. |
| Forecast rain | Wait when probability × amount over the next **48 hours** covers the deficit (or an optional depth). Only slots at or above **60%** count. Wait at most **2** mornings, then water anyway. Forecast rain is never added to the soil bucket. |
| Forecast skip depth | Optional millimeters. Empty means wait only when expected rain covers the deficit. Set it to also wait when expected rain reaches that depth. |
| Freeze skip | Skip watering at or below this air temperature, or the forecast low. Default **40°F**. |
| Freeze alert | On. One notice per cold snap when the forecast low is at or below **32°F** in the next 48 hours. **28°F** uses the hard-freeze wording. |
| Max run per zone | Valve-on minutes for one zone tonight. Default **60**. Soak does not count. The rest stays in the bucket. A zone can set its own number under Hardware; blank uses this. |
| All zones together | Optional. Empty means no hub total. Set it only to cap every zone's valve-on time on the same night. |
| Round minutes | On by default. Off keeps cycle lengths to 0.1 minute. |
| Allowed weekdays | Every day is selected by default. Clear a day to forbid it. An empty selection allows no day. |
| Blackout hours | Optional. The shared timeline stays outside this local hour range. |
| Drip ignores weekdays | Off by default. Buried drip can skip the weekday check. The blackout still clips the shared timeline. |
| Climate sensors | Optional temperature, humidity, wind, pressure, solar radiation, UV, and rain amount. |
| High / low flow | Defaults **+30%** and **−25%** from the baseline gallons per minute. With no baseline yet, from the learned rate after **3** runs. Each alert can notify only, or skip that zone until you reset flow learning. |
| Flow trend | Default **±10%** from a saved baseline, using the median of the last **5** runs. Notify only. Shown on Flow problem, not as its own sensor. |
| Idle flow | Default **0.5 gal/min** (or about 1 gallon on a volume total) while every zone is off. Notify only, or stop and skip every zone until reset. |
| Cost per 1,000 gal | Optional. Adds a water-cost sensor in dollars. |
| Weekly gallon budget | Optional. One alert per week when use goes over it. |
| Weekly summary | Off. On Monday, at or after the plan hour, one event and a notification if a notify target is set. |

### Tempest as the reference weather setup

Map the station's entities. Units are converted (temperature, mm/in, m/s, kPa, W/m² or MJ/m², gallons).

| Sprinklecast field | Typical Tempest entity |
| --- | --- |
| Temperature | Air temperature |
| Humidity | Humidity |
| Wind | Wind speed (height defaults to 2 m) |
| Pressure | Station pressure, not sea-level pressure |
| Solar radiation | Solar radiation in W/m², integrated through the day |
| UV index | Only if solar radiation is empty. About 100 W/m² per UV index, which is not an FAO factor |
| Rain amount, kind daily total | Rain today |
| Weather entity | Left as the fallback for forecast rain and for any sensor you leave empty |

Rain kinds: **daily total** replaces today's amount (Tempest rain today). A downward correction only shrinks rain recorded that same day, so a midnight reset does not erase yesterday. **Cumulative** ignores the first sample so history before install is not credited, then adds increases and ignores a counter reset. **Rate** is mm/h, trapezoid-integrated, and gaps longer than 6 hours are dropped. Positive amounts are also kept as events for about 48 hours. Measured rain is credited in the soil bucket. Effective rain follows FAO-56: a day below 0.2 × ET0 is ignored inside the bucket. Today's bucket uses the rain sensor only. Forecast rain skips a zone only when you set a threshold.

### Sensor names and units

The setup and options forms list names these entities often use in Home Assistant. The units are the ones the code converts. Any other unit, or a missing unit, shows a warning and that reading is ignored.

| Sensor | Example names | Accepted units |
| --- | --- | --- |
| Weather entity | Weather, Forecast, Home, OpenWeatherMap, Met.no, AccuWeather, National Weather Service, Tempest, WeatherFlow | Temperature: °C, C, degC, ºC, °F, F, degF, ºF (°F, F, degF, and ºF are converted automatically). Precipitation: mm, in, inch, inches (in, inch, and inches are converted automatically). Wind: m/s, mph, mi/h, km/h, kph, kmh, kn, kt, knots (converted automatically). If one of those units is missing or not in the list, that part shows a warning and is ignored. Humidity on the weather entity is percent, because Home Assistant weather entities report humidity in % and have no humidity unit. Pressure is not read from the weather entity. |
| Temperature sensor | Temperature, Outdoor temperature, Air temperature, Ambient temperature (Tempest, Ecowitt, Ambient Weather). Device class: temperature. | °C, C, degC, ºC, °F, F, degF, ºF (°F, F, degF, and ºF are converted automatically). Any other unit, or a missing unit, shows a warning and this sensor is ignored. |
| Humidity sensor | Humidity, Relative humidity, Outdoor humidity, RH (Tempest, Ecowitt, Ambient Weather). Device class: humidity. | % (required). A 0–1 fraction is not accepted. A missing unit or any other unit shows a warning and this sensor is ignored. |
| Wind sensor | Wind speed, Wind, Sustained wind, Wind average (Tempest Wind speed or Wind average, Ecowitt). Device class: wind_speed. | m/s, mph, mi/h, km/h, kph, kmh, kn, kt, knots (converted automatically). Any other unit, or a missing unit, shows a warning and this sensor is ignored. |
| Pressure sensor | Station pressure, Pressure, Barometric pressure, Atmospheric pressure (Tempest Station pressure, Ecowitt, Ambient Weather). Prefer station pressure when both exist. Device class: pressure or atmospheric_pressure. | hPa, mbar, mb, kPa, inHg, psi, mmHg, Pa (converted automatically). Any other unit, or a missing unit, shows a warning and this sensor is ignored. |
| Solar radiation sensor | Solar radiation, Irradiance, Solar irradiance, Global horizontal irradiance (GHI), Shortwave radiation (Tempest Solar radiation). Illuminance, lux, and brightness are not the same and are ignored. Device class: irradiance or solar_irradiance. | W/m², W/m2, Wm2, W/m^2 (live irradiance), or any unit containing MJ (daily total). Any other unit, including lx, or a missing unit, shows a warning and this sensor is ignored. |
| UV index sensor | UV index, UV, Ultraviolet index (Tempest UV index). Device class: uv_index. | UV index, UV, UVI, index (required). W/m² and lx are not accepted. A missing unit or any other unit shows a warning and this sensor is ignored. |
| Rain amount sensor | Rain today, Precipitation, Daily rain, Rain accumulation, Rain rate (Tempest Rain today, Ecowitt rainfall). Device class: precipitation. | mm, in, inch, inches (in, inch, and inches are converted automatically). Any other unit, or a missing unit, shows a warning and this sensor is ignored. When the rain kind is rate, that depth is per hour. in/h is not accepted. |
| Flow sensor | Flow rate, Water flow, Flow, Water total, Water usage, Irrigation flow (Flume, Moen Flo, Phyn, Rachio, Hydrawise, Ecowitt). Device class: water, volume, or volume_flow_rate. | Volume total: gal, gallon, gallons, L, liter, liters, litre, litres, m³, m3, m^3, ft³, ft3, ft^3, cuft (non-gallon units are converted automatically). Flow rate: gal/min, gpm, L/min, lpm, m³/h, m3/h, m^3/h, gal/h, gph (non-gal/min units are converted automatically). A missing unit or any other unit shows a warning and this sensor is ignored. Set Flow sensor kind to match. |
| Rain sensor | On/off: Raining, Rain sensor, Is raining, Rain detected. Rate: Rain rate, Rain intensity, Precipitation intensity, Precipitation rate. Device class: moisture for on/off; precipitation_intensity for a rate. Hub and each zone. | Units: none for on/off; in/h or mm/h for rate (converted automatically). Accepted rate units: in/h, in/hr, in/hour, inch/h, inch/hr, inch/hour, inches/h, inches/hr, inches/hour, mm/h, mm/hr, mm/hour. A rate above the threshold (default 0, in the sensor's units) means raining. Any other unit on a numeric sensor, or a missing unit, shows a warning and this sensor is ignored. |
| On/off entity | Zone, Valve, Sprinkler, Station (Hydrawise, Rachio, OpenSprinkler). Domains: switch, valve, input_boolean. | none. Switch and input boolean use on and off. A valve uses open and closed. |
| Soil moisture sensor | Soil moisture, Moisture, Soil humidity, VWC, Volumetric water content (Ecowitt, Vegetronix). Device class: moisture. | %, percent, pct, or a fraction unit (fraction, ratio, 0-1, m³/m³, m3/m3, m^3/m^3, cm³/cm³, cm3/cm3, v/v). A 0–1 number is accepted only when the unit is a fraction unit. The full-soil reading uses that same unit. Any other unit, or a missing unit, shows a warning and this sensor is ignored. |

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
| Flow meter | One sensor on the hub, volume total or rate. Choose whole-home or irrigation-only. Water used while a zone is running is counted for that zone. Whole-home does not alert while nothing is running. |
| Zone rain sensor | Binary sensor. On skips that zone. |

## Simulation

A simulation hub is the first menu choice. It does not ask for a weather entity, a sensor, or an on/off entity. Each zone is plant, soil, sprinkler, and sun, plus an optional area and slope. The on/off id is a `simulation.<name>` label. Nothing in the week calls a valve, a switch, an input boolean, or a controller.

The week uses the same functions as a live hub: Penman-Monteith ET0, the soil bucket, `build_zone_request`, and `build_plan`. After a night that would have watered, the planned net depth is subtracted from that zone's simulated deficit. The live bucket is not changed, and the week does not apply the live minimum-interval or dormancy rules.

### Run one

1. Add integration → **Sprinklecast** → **Simulation hub**.
2. Name the hub. Leave **Weather week** on Hot dry Texas summer and **Starting soil** on Full, or pick another preset (mild spring, rainy week, heat wave then storm, fall cooldown). Location and schedule can stay collapsed. Empty latitude and longitude use the Home Assistant location for ET. The morning window stays 05:00–09:00 unless you change it.
3. Name the zone. Choose plant, soil, sprinkler, and sun. Area is optional; set it when you want gallons. Leave slope blank for the 0–5% intake rate. Submit.
4. On **Advanced**, leave the fields blank unless you want to override a preset. Submit.
5. The **Simulation** sensor fills in as soon as the zone exists. Its state is the week name and the total minutes. The attributes hold each day and a markdown table.
6. To run it again, press **Run simulation** on the hub, or change the week under the hub's options and press the button. The button uses the stored preset and starting soil.

Custom days replace the preset for one run. Developer tools → Actions → `sprinklecast.simulate`. Set **Return response** if you want the week in the action result. `days` is a YAML list. `high_f` / `low_f` or `high_c` / `low_c`, `humidity` (default 50), `wind_mph` (default 8) or `wind_m_s`, `cloud` from 0 clear to 1 overcast (default 0.2), and `rain_in` or `rain_mm`. `start_date` is `YYYY-MM-DD`. Empty starts today. The same action works on a live hub and does not change that hub's stored deficit.

```yaml
action: sprinklecast.simulate
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

Computed by `run_week`, not typed by hand. Location is the design site: latitude 31.5493, longitude −97.1467, elevation 219 m, America/Chicago. The week starts Monday 13 July 2026, so July's warm-season coefficient is 0.71. The zone is 1000 sq ft. Slope is blank, so clay loam intake is 0.15 in/hr and the max cycle is 7 minutes with a 30 minute soak. The bucket starts full. This table uses the fixed start (Dynamic start time off): any day, opening at 05:00 and finishing by 09:00, with 04:00 as Don't start before. The 30 minute soak fits in that window, so the cycles stay on 05:00. Gallons are gross water from the heads (`runtime × 1.25 in/hr × 1000 sq ft × 0.623`), rounded in the table. Look-ahead is 0 days, so a morning is watered only when the deficit is already at readily available water. This simulation does not apply the 3-day turf interval. Total runtime is 128 minutes. `would_execute` is false. With Dynamic start time on, the same mornings start at 04:00 so they can finish nearer sunrise without going earlier than Don't start before.

| Day | Zone | Water loss mm | Rain in | Rain counted in | Water needed mm | Water | Minutes | Cycles | Start | Gallons | Why |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- | ---: | --- |
| Mon 07-13 | Front lawn | 9.1 | 0.00 | 0.00 | 6.5 | no | 0 | — | — | 0 | Not dry enough (water needed 6.5 mm, watering point 10.7 mm). |
| Tue 07-14 | Front lawn | 9.9 | 0.00 | 0.00 | 13.5 | yes | 42 | 7+7+7+7+7+7, soak 30 | Wed 05:00, Wed 05:37, Wed 06:14, Wed 06:51, Wed 07:28, Wed 08:05 | 545 | Due. |
| Wed 07-15 | Front lawn | 10.7 | 0.00 | 0.00 | 7.6 | no | 0 | — | — | 0 | Not dry enough (water needed 7.6 mm, watering point 9.6 mm). |
| Thu 07-16 | Front lawn | 10.0 | 0.00 | 0.00 | 14.7 | yes | 46 | 7+7+7+7+6+6+6, soak 30 | Fri 05:00, Fri 05:37, Fri 06:14, Fri 06:51, Fri 07:28, Fri 08:04, Fri 08:40 | 597 | Due. |
| Fri 07-17 | Front lawn | 9.0 | 0.00 | 0.00 | 6.4 | no | 0 | — | — | 0 | Not dry enough (water needed 6.4 mm, watering point 10.9 mm). |
| Sat 07-18 | Front lawn | 8.9 | 0.00 | 0.00 | 12.7 | yes | 40 | 7+7+7+7+6+6, soak 30 | Sun 05:00, Sun 05:37, Sun 06:14, Sun 06:51, Sun 07:28, Sun 08:04 | 519 | Due. |
| Sun 07-19 | Front lawn | 8.6 | 0.00 | 0.00 | 6.1 | no | 0 | — | — | 0 | Not dry enough (water needed 6.1 mm, watering point 11.1 mm). |

## Turn automatic watering on

The switch is **off** on a new hub and stays **off** when you upgrade. That is deliberate.

1. Update and restart.
2. Open the hub device. Turn on **Automatic watering** (`switch.<hub>_automatic_watering`). A hub named Garden is `switch.garden_automatic_watering`.
3. Leave each zone's **Enabled** switch on. Off removes that zone from the plan and from run now.
4. If the hub mode is Off, turning Automatic watering on sets the mode to Auto and reloads the hub. Notify-only does not block watering once the switch is on.
5. The plan is committed at or after the plan hour (default 23:00). With Dynamic start time on, valves open so the last cycle ends at sunrise, and never before Don't start before. With it off, they open at the start time (default 05:00). One zone runs at a time, and the last cycle ends by the finish time (default 09:00).

**Run now** (the zone button or `sprinklecast.run_now`) ignores the automatic switch, the allowed days, the minimum interval, and a dormancy stop. It still skips a wet rain sensor, current rain, recent rain, a freeze, high wind, and soil that is wetter than the moisture threshold. It still confirms on and off and it still stops at the max-run cap.

`sprinklecast.stop_all` turns off whatever this hub left on. Startup does the same for an entity recorded as on, and so does Home Assistant's stop event.

## Watering schedule

The hub sensor **Watering schedule** (`sensor.<hub>_watering_schedule`) lists the next watering days, not every calendar day. The count is the number of allowed weekdays: Monday, Wednesday, and Friday means the next three mornings when at least one zone is projected to water, even if those mornings are weeks apart. Every day allowed means the next seven watering mornings. An empty selection shows none. The search stops at about 365 days. Days when nothing waters are left out.

The state is the next watering as an exact local date and time, such as `Next watering Fri Jul 17, 5:00 AM`. A day past the weather forecast has `estimated` set on that day. The word is not written into the state. The date is the morning the valves open, and the start is the first cycle. Each day lists the zones that water and their minutes. The projection refills the bucket after each of those mornings, so the second and third days are the water still needed, not a copy of the first. Near days and later days both use the morning planner, including Dynamic start time, Don't start before, the finish time, interleaving, and the 60-minute zone cap. The `window` attribute is the start, finish, and Don't start before time. With Dynamic start time on it says the run aims to finish at sunrise.

The sensor attributes stay short so Home Assistant can record them. Cycle times, depths, gallons, soak, the per-zone reasons, and the markdown table are in the diagnostics download for the config entry (Settings → System → Repairs → the integration menu, or the diagnostics button on the hub). Attributes:

| Attribute | What it holds |
| --- | --- |
| `days` | One entry per watering day: `date`, local `start`, `estimated` when the day is past the weather forecast, and each zone that waters (`name` and `minutes`). |
| `window` | Start, finish by, and Don't start before. Default with Dynamic start time off: `Start 05:00, finish by 09:00, earliest 04:00.` |
| `alerts` | Short lines, such as a freeze notice or a flow alert. |
| `week_gal` | Gallons used this week, when the water-use sensor is not the source. |
| `saved_gal` | Gallons saved this week versus the fixed timer. |

**Watering now** is the zone that is on, or `Idle`. Each zone has a **Last run** sensor (state is the result; attributes are when, minutes, net millimeters, gallons, gallons per minute, and result) and a **Plant activity** sensor (`active`, `slow`, or `dormant`).

### Sample

Computed by `project_week`, not typed by hand. Same design site and the same Monday 13 July 2026 hot-dry day used above (ET0 9.1 mm, Penman-Monteith). St. Augustine, clay loam, spray, full sun, 1000 sq ft, slope blank, July coefficient 0.71, crop ET 6.5 mm, readily available water 10.8 mm, soak 30 minutes. The bucket starts at field capacity (deficit 0; today's ET is already in the deficit the sensor uses, and here that deficit is still 0) and the last watering is treated as today, so the 3-day interval has not elapsed. Every day is allowed, there is no blackout, and Dynamic start time is off. Later days repeat that 6.5 mm and add no rain. Each zone is capped at 60 valve-on minutes. The hub total is off. Clock times are local. Each row is dated by the first cycle, the morning the valves open. The 14th, 15th, 16th, 18th, and 19th have no watering, so the sensor leaves them out. Every day is allowed, so the list continues until it has seven watering mornings. The state is `Next watering Fri Jul 17, 5:00 AM`. The first two of those mornings:

```text
Next 7 watering days. Days with no watering are left out. Later days use the forecast or the recent water-loss average and assume no rain. Start 05:00, finish by 09:00, earliest 04:00.

2026-07-17 05:00–08:49
- Front lawn: 49 min, 0.61 in (15.6 mm), 636 gal, soak 30 min
  12 min carries to the next allowed day.
  05:00–05:07, 05:37–05:44, 06:14–06:21, 06:51–06:58, 07:28–07:35, 08:05–08:12, 08:42–08:49

2026-07-20 05:00–08:49
- Front lawn: 49 min, 0.61 in (15.6 mm), 636 gal, soak 30 min
  24 min carries to the next allowed day.
  05:00–05:07, 05:37–05:44, 06:14–06:21, 06:51–06:58, 07:28–07:35, 08:05–08:12, 08:42–08:49
```

The 17 July row is the first run. The valves open at 05:00 on the morning of the 17th. With a 30 minute soak the sequence fits the fixed start; 12 minutes still wait because of the per-zone cap. The morning of 19 July is skipped because the last run was only two days earlier, and the bucket already had the 17 July water taken out, so the 20th carries 24 minutes instead of repeating the first morning from an empty plan. The next run is the morning of the 20th.

### Six zones, one morning

Same site, Monday evening 13 July 2026, so the valves open Tuesday 14 July. ET0 is 9.1 mm. Deficits are already past readily available water. Slope is blank. No blackout, every day allowed. Each zone may use 60 valve-on minutes. The hub total is off. Dynamic start time is off. The window is 05:00–09:00, and Don't start before is 04:00. Clay loam soaks 30 minutes. Order is priority, then the larger deficit. One valve is on at a time. Valve time does not fit 05:00–09:00, so the run opens at 04:00 and stops at 09:00. It does not open earlier. Shade bed does not get a cycle; its minutes stay in the bucket.

| Zone | Plant, soil, sprinkler | Priority | Area | Water needed | Watering point | This morning |
| --- | --- | --- | --- | --- | --- | --- |
| Front lawn | St. Augustine, clay loam, spray | 1 | 1000 sq ft | 18 mm | 10.8 mm | 27 min, 0.34 in, 350 gal. 30 min carries. |
| Back lawn | Bermuda, sandy loam, rotor | 1 | 800 sq ft | 16 mm | 8.7 mm | 60 min, 0.35 in, 249 gal. 48 min carries (cap). |
| Vegetable bed | Vegetable, sand, spray | 2 | 150 sq ft | 20 mm | 8.2 mm | 60 min, 0.75 in, 117 gal. 3 min carries (cap). |
| Side strip | Warm-season turf, sand, spray | 2 | 400 sq ft | 14 mm | 5.4 mm | 44 min, 0.55 in, 228 gal. |
| Foundation shrubs | Shrub, loam, drip | 3 | 200 sq ft | 55 mm | 48.9 mm | 58 min, 0.42 in, 60 gal. 239 min carries (cap). |
| Shade bed | Flower bed, loam, MP rotator | 4 | 300 sq ft | 28 mm | 19.3 mm | Not this morning. The window was full. |

Valve-on time is 249 minutes. No zone is over 60. Clock order, local time on 14 July:

| | |
| --- | --- |
| 04:00–04:07 | Front lawn, 7 min. The run started at 04:00 so it can finish by 09:00. |
| 04:07–05:07 | Back lawn, 60 min, during the front soak |
| 05:55–06:02 | Front lawn, 7 min |
| 06:02–07:02 | Vegetable bed, 60 min |
| 07:05–07:12 | Front lawn, 7 min |
| 07:12–07:56 | Side strip, 44 min |
| 07:56–08:02 | Front lawn, 6 min |
| 08:02–09:00 | Foundation shrubs, 58 min, ending at the finish time |

## Flow

The hub has one flow meter. While a zone is running, the measured flow is that zone's. House use is not subtracted. A whole-home meter hides the idle-flow alert. An irrigation-only meter keeps it.

Each zone keeps one expected rate, **Baseline flow**. **Learn flow rates** or `set_flow_baseline` stores it, and it is kept across restarts and upgrades. The source attribute is `flow_learning` or `manual`, with the date. An older catch-cup baseline stays, with source `catch_cup`, until you learn again. Until one of those is saved, Baseline flow shows the median learned from normal runs (default 3 runs, then the last 12). A run more than twice that median, or under 0.4 times it, is left out of the median. That source attribute says `learned`. There is no separate Learned flow sensor.

A single run is compared with the baseline, not with the previous run, so a slow clog or a slow leak is not absorbed into the normal. The high and low percents are the same settings as before (default +30% and −25%). With no saved baseline yet, those alerts still wait for the learned median (default 3 runs). The last 30 per-run averages are kept. The median of the last 5 (change that on the hub) is the flow trend. It alerts when that median is more than 10% off a saved baseline. A trend alert notifies only. It does not stop the zone. The status, the drift percent, and the sentence are attributes on **Flow problem**. There is no separate Flow trend sensor.

| Alert | Default | What it means |
| --- | --- | --- |
| High flow | +30% vs baseline | Broken head or a leak in that zone. |
| Low flow | −25% vs baseline | Clog, stuck valve, or low pressure. |
| Flow trend | ±10% vs a saved baseline, median of the last 5 runs. Shown on Flow problem. | A nozzle clogging slowly, or a leak growing slowly. |
| Idle flow | 0.5 gal/min, or about 1 gallon on a volume total, while no zone is on | Main-line leak. Whole-home meters do not raise this. |

High flow and low flow are **Notify only** or **Stop and skip until reset**. Notify is the default. Stop on a zone skips that zone. Stop on idle flow skips every zone. The trend alert is notify only. `sprinklecast.reset_flow_learning` clears the samples, the alert, and the skip. It does **not** clear the baseline unless you turn on clear baseline. Leave the zone empty to reset the hub. The event is `smart_water_flow_alert`. A repair is raised with the same sentence. A notify target, if set, gets it too.

After you change nozzles, press **Learn flow rates** again, or call `sprinklecast.set_flow_baseline`. That replaces the baseline and clears the trend history so the old nozzles are not the comparison.

Sensors, only when a hub flow meter is set: **Flow problem** (a problem binary sensor: off is normal, on means the last run is outside the high/low band versus the saved baseline, or the recent trend has drifted), **Last run flow**, **Baseline flow**, and **Flow vs baseline** (percent). Flow problem stays off until a saved baseline exists, including when Baseline flow is only the learned rate. Its attributes carry the last run, the baseline, the percent difference, the reason, the high and low percents, and the trend status, drift, and sentence. The last on/off result stays across a restart. With no area, gallons use the learned rate once it exists. An entered rate still wins over flow and area. Area still wins over GPM for the gallon estimate.

## Water use

Each zone and the hub have a **Water use** sensor: lifetime gallons, `state_class: total_increasing`, unit `gal`, device class water, so the Home Assistant water dashboard can track it. Today, this week, and this month are attributes. They are sums of a date log and are not the long-term statistic, because a counter that resets cannot be `total_increasing`.

Gallons come from the flow sensor when it moved during the cycle. Otherwise they are the computed amount (precipitation × area, or GPM × minutes when there is no area).

**Water saved** is this week's gallons versus the fixed timer (default 15 minutes, 3 days a week). Positive means the plan used less than that timer. It can be negative. **Water cost** exists only after you set a price per 1,000 gallons. It is lifetime dollars, `total_increasing`.

An optional weekly gallon budget fires `smart_water_budget_alert` once per ISO week. **Weekly summary** is off until you turn it on. It fires `smart_water_weekly_summary` on Monday at or after the plan hour, once per week, and notifies when a notify target is set.

## What a run does

Once per local day, at or after the plan hour, each zone's bucket is updated:

`Dr = Dr + ETc − rain − irrigation` (FAO-56 style), clamped to total available water. Rain below 0.2 × ET0 is ignored. A finished cycle credits the bucket from the minutes the valve was actually on (net millimeters = minutes/60 × precipitation rate × efficiency × 25.4), or from the flow-total increase when that sensor moved. Calling `calculate_plan` before the plan hour commits that day's ET early; the evening update will not apply it twice. If automatic watering is on, that same refresh arms the next morning's cycles.

A zone is due when its deficit has reached readily available water (RAW), or a target depth you set. It is not watered a day early. Turf then waits at least 3 days, shrubs and trees 7, vegetables and flowers 2. The scheduled depth is the current deficit times the adjustment percent. Runtime is `60 × (net inches / efficiency) / precipitation rate`, whole minutes unless you turn rounding off. Efficiency is the sprinkler preset (spray 0.60) unless the zone stored an override. Zones created before 0.3.0 stored 1.0.

Max cycle length is `floor(60 × NRCS intake in/hr / precipitation rate)`. Example: clay loam on a 5–8% slope (0.10 in/hr) at 1.5 in/hr is a **4 minute** cycle and a 20 mm deficit is **31 minutes**. One valve at a time. Zones are ordered by priority, then by a larger deficit, then by name, so one zone's soak can hold another's cycle. The sequence starts at the start time. If it would run past the finish time, it slides earlier, down to the earliest start, and still ends by the finish time. The hourly forecast (`weather.get_forecasts`, type `hourly`) can move that finish earlier when the hour at the finish is at or above the strictest wind limit of the zones that will run. Drip and bubbler do not tighten it. The run stays inside the earliest start and the finish time. Only the first morning of the week sensor uses that forecast; later days are not given invented wind.

The cap (default 60) is valve-on minutes for one zone on that morning. Soak does not count. A zone can override it under Hardware. An optional hub total, off unless you set it, caps every zone together after each zone's own cap. The planner keeps the higher-priority cycles that fit. Minutes that do not run stay in the bucket. If the zone is still at readily available water, the next allowed day can finish them. If the partial morning drops the deficit below that line, the minimum interval starts and the leftover minute does not come back as its own run. A schedule note looks like `Deferred for forecast rain (70% / 0.4 in).` when confident rain covers the deficit. That depth is not subtracted from the bucket. If the rain sensor does not record it, the next window waters once the wait (default 2 mornings) is over.

Just before each cycle the executor checks rain since the plan was armed, the skip rules, the time left in the window, and the remaining max-run budget. Each on or off command is confirmed against the entity state and retried up to three times.

ET0 uses FAO-56 Penman-Monteith when humidity and wind are available. Daily solar radiation is the integrated W/m² (or a daily MJ/m² sensor) when that total is above zero, otherwise the Hargreaves radiation estimate. Temperature-only days use Hargreaves ET0. A temperature sensor replaces the forecast high and low once the observed range is at least 0.5 °C, so one reading cannot zero the radiation estimate. Missing temperatures produce no ET0 and the bucket is left alone.

### Skip, dormancy, and learning defaults

| Rule | Default | Source |
| --- | --- | --- |
| Freeze | At or below 40°F, current temperature or forecast low. Missing temperatures do not skip. | Oklahoma State University HLA-6610, "Do not water when temperatures are below 40°F". https://extension.okstate.edu/fact-sheets/lawn-watering-tips.html |
| Raining now | A rain sensor that is on, or the weather entity reporting rain right now. Measured rain is credited in the bucket and is not a second skip. | HLA-6610 says not to water when rain is present and does not publish a duration or a depth. |
| Wind | Spray 10 mph, MP rotator 12, rotor 15, drip and bubbler not skipped. Sustained wind at or above the limit. No reading means do not skip. | HLA-6610 says not to water in high wind and publishes no speed. University of Florida overhead guidance treats wind above about 10 mph as unsuitable. The Irrigation Association 2013 wind paper shows smaller droplets drift more. 12 mph for MP rotators is the midpoint of spray and rotor; no MP-specific cutoff was found. |
| Moisture | Skip when the sensor is fuller than `1 − p` (still wetter than MAD). | The depletion fraction already used for RAW. Override with a percent on the zone. |
| Forecast rain | Expected rain (probability × amount) over 48 hours, counting slots at or above 60%. Wait up to 2 mornings when that covers the deficit, or an optional depth. | The schedule sentence is `Deferred for forecast rain (70% / 0.4 in).` Forecast depth is never a bucket credit. Measured rain still uses the rain sensor. |
| Freeze alert | On. Forecast low at or below 32°F within 48 hours. Hard freeze at or below 28°F. | Separate from the 40°F watering skip. One event, repair, and notification per cold snap. |
| Dormancy | 7-day mean of daily mean air temperature, after at least 3 days. Warm-season (Bermuda, Zoysia, Buffalo, generic): slow below 55°F (crop ET × 0.5), dormant below 50°F (no regular irrigation). St. Augustine: slow below 60°F, dormant below 55°F. Cool-season: slow when the mean is at or above 80°F, no temperature-only full stop. Other plants stay active. | Texas A&M Forage Fax / Mississippi State: bermuda and bahia stop shoot growth below 50°F, and rhizomes and stolons need soil above about 55°F. https://foragefax.tamu.edu/impact-of-sub-freezing-temperatures-on-warm-season-perennial-grasses/ AgriLife Water-Wise Checklist: turn irrigation off when dormant, deep and infrequent, about 6 inches, no more than once or twice a week. https://aggieturf.tamu.edu/wp-content/uploads/sites/24/Water-Wise-Checklist-for-Texas-Home-Lawns-1.pdf AgriLife St. Augustine management: best growth 80–95°F, turn water off in winter. https://mytexas.ag.tamu.edu/publications/st-augustinegrass-lawn-management/ AgriLife dormant sodding: St. Augustine and centipede are the most winter-injury susceptible, then bermuda, zoysia, buffalo. The St. Augustine lines are 5°F higher from that ranking, not a separate published cutoff. Buffalo uses the group 50/55 lines. https://aggieturf.tamu.edu/wp-content/uploads/sites/24/Dormant-Sod.pdf UNL G2191: above 80°F reduces cool-season survival. https://extensionpubs.unl.edu/publication/g2191/2013/html/view The 7-day air mean is a proxy. There is no soil-temperature sensor. |
| Winter maintenance | Off. If you turn it on: every 21 days, 0.25 in, only while dormant and at RAW. Measured rain is already in the bucket. | AgriLife says turn irrigation off when dormant. The depth is the low end of the UNL 1/4–1/2 inch survival watering. |
| Deep and infrequent | Due at RAW (or your target depth), not a day ahead. Turf interval 3 days, shrubs, trees, native, and drip beds 7, vegetables and flowers 2. A zone that has never been watered is not blocked by the interval. | AgriLife: about 6 inches, no more than 1–2 times a week. Three days is the short end of twice a week. |
| Moisture learning | On when a sensor is set. The available-water factor starts at 1 and moves by `0.05 × (sensor full − model full)`, clamped to 0.7–1.3. Confidence reaches 1 after 14 samples. Skipped when rain today is at least 2.5 mm, and on the watering day and the day after. One update per day, applied to the next plan. `sprinklecast.reset_learning` sets it back to 1. | The bounds and the step are engineering limits, not an agronomy citation. The factor is not written into the available-water override. |

## Services

| Service | Effect |
| --- | --- |
| `calculate_plan` | Commit today's balance if needed, then rebuild the plan. If automatic watering is on, this can arm tonight's run. |
| `reset_bucket` / `set_bucket` | Water needed 0, or a set amount that cannot exceed what the soil can hold. |
| `set_soil_water_level` | Set how full the soil is (0–100%) or the water it still needs, in millimeters, inches, or Home Assistant's precipitation unit. A zone name, a list of zones, or a zone entity picks the target. Leave the zone empty to set every zone on the hub. The bucket is saved, the plan, next watering, schedule, and calendar are rebuilt, and the change is kept in the soil history. The Soil water sensor shows the same percent. Does not open a valve. |
| `mark_watered` | Credit net irrigation already applied. Empty depth refills the bucket. |
| `skip_zone` | Skip through a date. Default is the next local morning. |
| `pause_zone` | Skip N local days. Zero clears the pause. |
| `set_adjustment` | Percent of the calculated depth. 100 is unchanged. 0 keeps the zone off the timeline. The number entity does the same thing. |
| `run_now` | Runs that zone's cycle-and-soak now, even when automatic watering is off. Credits the bucket from the time it actually ran. |
| `stop_all` | Turns off the entity this hub turned on. |
| `reset_learning` | Sets that zone's moisture factor back to 1 and clears its confidence. |
| `reset_flow_learning` | Clears learned flow, the alert, and a skip that is waiting for reset. The baseline stays unless clear baseline is on. An empty zone resets the whole hub. |
| `run_catch_cup_test` | Runs each selected zone once for the minutes you pass (default 15). Empty zone means every enabled zone. No soak, no cap, no soil credit until you enter the depth. |
| `set_catch_cup_result` | Zone, depth, and optional minutes. Stores the precipitation rate (depth / minutes × 60) and credits the soil by that depth. |
| `set_flow_baseline` | Saves gallons per minute as the permanent baseline. Empty gallons per minute uses the last run. Clears the trend history. |
| `start_audit` | Runs one zone for the minutes you pass, as a manual run. Freeze, wind, rain, moisture, and the zone cap still apply. |
| `submit_audit` | Cup readings in inches, or millilitres plus a cup diameter. Stores the measured rate and scheduling efficiency. |
| `simulate` | Plays a weather week through the planner and returns it. Does not change the stored deficit and does not call an on/off entity. |

A zone is usable when Home Assistant already exposes it as a valve, switch, or input boolean. Your existing controller schedule is unchanged. If it still waters at dawn, Sprinklecast will not stop it.

## Entities

Per zone, on the device page: soil water (percent full, read-only), **Soil water level** (a number, 0–100%, step 1), **Catch-cup depth** (a number, inches or millimeters), water needed, next watering, why this plan, today's run, last run, plant activity, water used, water saved, a watering-amount number (0–300%), a run-now button, and an enabled switch. Setting Soil water level writes the water still needed as that percent of the water the soil can hold, saves it, and rebuilds the plan. The value you set is today's soil water. The next plan hour applies the following day's water loss. Catch-cup depth stores the measured average and the date, minutes, and rate as attributes. The watering point is diagnostic. Soil moisture level is diagnostic and exists only when that zone has a moisture sensor. Flow problem, last run flow, baseline flow, and flow vs baseline exist only when the hub has a flow meter.

The hub has **Run catch-cup test**. It runs every enabled zone, one at a time, for 15 minutes. **Learn flow rates** is on the hub only when a flow meter is set. It runs each enabled zone and saves that zone's baseline.

Hub: today's plan, rain today, next watering, watering schedule, watering now, water used, water saved, water cost when a price is set, the Automatic watering switch, and a Watering calendar (`calendar.<hub>_watering`). Water loss today (reference lawn) is diagnostic. A simulation hub also has a Sample week sensor and a Run simulation button. Entity ids are the ones created with the old names; renaming the label does not change them. The Mode sensor is removed.

Bucket state, the day's weather accumulation (including rain events), flow totals, adjustment, last run, the learned factor, and the last plan are stored and survive a restart. Storage version stays 1; new keys are filled in when an older file is loaded. On startup, an entity this hub recorded as on is turned off.

## Dashboard card

The integration serves a Lovelace card and registers it when the frontend is loaded. After a restart, add a card and choose **Sprinklecast**, or use YAML:

```yaml
type: custom:sprinklecast-card
entity: sensor.garden_watering_schedule
```

`entity` is the hub watering-schedule sensor. The name follows the hub, so a hub named Garden is `sensor.garden_watering_schedule`.

The card opens with a horizontal strip of the upcoming watering days. Tap a day to list that morning's runs. Each burst is its own row: a colored bar for the zone (the same color every time that zone appears), the local time range (`5:00 am - 5:18 am`), the zone name, and the minutes, inches, soak, and cycle. A weather icon shows rain, wind, freeze, or a wet soil sensor when the plan says so. Times stay on the Home Assistant clock. Below that, each zone still has its soil-water bar (percent full, with a tick at the watering point), the last run, a soil chart, the skip reason, and Run now, Skip, and Pause. The hub row has the Automatic watering toggle, what is watering now, this week's gallons and gallons saved, and alerts. The editor is a schedule-entity list and a history checkbox.

An entities card shows a timestamp such as Next watering as a relative phrase ("in 2 weeks") unless you ask for the clock time:

```yaml
type: entities
entities:
  - entity: sensor.garden_next_watering
    format: datetime
  - entity: sensor.front_yard_next_watering
    format: datetime
```

`format: datetime` is the entities-card option. It applies to the hub Next watering sensor and to each zone's Next watering sensor.

If the card does not appear, add a dashboard resource by hand: **Settings → Dashboards → Resources → Add resource**, URL `/sprinklecast_static/sprinklecast-card.js`, type **JavaScript module**. The markdown card above still works and does not need the custom card.

## Catch-cup test

Put cups out in the zone, between the heads, in the overlap and in the gaps. Then press **Run catch-cup test**, or call `sprinklecast.run_catch_cup_test`.

Each selected zone runs once, for exactly the minutes you choose. The default is 15, and the default zones are every enabled zone. One zone at a time. There is no cycle-and-soak split, no skip for the nightly runtime cap, and no soil credit while the valve is open. Rain right now, a wet rain sensor, freeze, wind, and a wet soil sensor still skip that zone. **Stop all watering** cancels the sequence. It is manual only. The morning plan never starts it.

When the zone turns off, read the cups and average the depth. Set **Catch-cup depth** (inches or millimeters, whichever Home Assistant uses), or call `sprinklecast.set_catch_cup_result` with the zone, the depth, and the minutes if you need to override them. The precipitation rate is `depth / minutes × 60` in inches per hour. That rate is saved on the zone and replaces the sprinkler preset. The date, minutes, and depth stay on the number as attributes. The soil is credited by the depth you entered. If you correct the number, only the difference is credited.

A repair reminds you to enter the cup depths. The catch-cup test does not set **Baseline flow**. That rate comes from **Learn flow rates**, or from `sprinklecast.set_flow_baseline`.

`sprinklecast.start_audit` is the older one-zone test. It still applies the runtime cap and wants a precipitation rate first. Use it with `submit_audit` when you have at least four cups and want distribution uniformity as well as the rate. The hub button does not calculate uniformity. It uses the one average depth.

## Catch-cup audit

`sprinklecast.start_audit` runs one zone for the minutes you choose. It is a manual run: it ignores the automatic switch, allowed days, the minimum interval, and dormancy, and it still stops for a freeze, wind, rain, a wet soil sensor, or the zone's runtime cap. It is one continuous run, not cycle-and-soak. Put cups out before you start it.

Use at least 4 cups. Eight is a better short test. Sixteen in a grid is better. Space them evenly between the heads, in the overlap and in the gaps, and include cups that stay dry. Those zeros count. Sprays need about 10 minutes. Rotors need 15–20 so the cups collect a measurable depth.

Then call `sprinklecast.submit_audit` with the readings. Inches need no diameter. Millilitres need the inside diameter of the cup. The result is the precipitation rate in inches per hour, the low-quarter distribution uniformity (average of the lowest quarter of the cups, divided by the average of every cup), and the scheduling efficiency, which is that same fraction. Both the rate and the efficiency are stored on the zone as overrides, marked **measured** next to the sprinkler preset, and the last 12 audits are kept.

## Develop

```bash
python3 -m pytest
```

Math tests do not import Home Assistant. Config-flow tests need `pytest-homeassistant-custom-component` matching Home Assistant 2026.10 and serialize every form the way the config HTTP API does.

## Limits

- The dashboard card loads with the frontend and lists the next watering days. A markdown card can still show the watering schedule or the simulation sensor's `markdown` attribute.
- A flow alert notifies, or skips until you reset it, according to the hub action. It does not change another integration's own schedule.
- Dynamic start time aims to finish at local sunrise and never opens before Don't start before (default 04:00). It still ends by Finish by (default 09:00). Turn it off to open at Start time (default 05:00). Latitude is used for sunrise and for ET.
- Soil, plant, sprinkler, and sun are chosen per zone. Slope and the other derived numbers are presets until overridden.
- Drip can ignore weekdays only. The blackout is shared by every zone on the timeline.
- Daytime `calculate_plan` commits a full day of ET if today's balance has not run yet, and it can start watering when automatic watering is on.
- The 7-day schedule repeats today's crop ET and assumes no future rain. A skip on a later morning can move the real run.
- Dormancy uses air temperature, not soil temperature.
