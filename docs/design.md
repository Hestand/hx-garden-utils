# Sprinklecast design

Version 0.14.2 ignores a sensor or weather attribute whose unit is missing or not in the accepted list, opens one repair per hub and field, and rejects that selection in the setup and options forms. The repair clears when the unit becomes valid. Config entry version stays 10. Version 0.14.1 adds example names and the accepted units to every sensor and entity selector in the setup and options forms. Config entry version stays 10. Version 0.14.0 adds a hub catch-cup sequence (`run_catch_cup_test`), a per-zone Catch-cup depth that stores precipitation rate as depth / minutes × 60, and a permanent flow baseline from that steady run. Later runs are compared with the baseline. A median of the last five runs past ±10% raises a trend alert. `reset_flow_learning` keeps the baseline unless clear baseline is on. Config entry version stays 10. Version 0.13.0 adds a per-zone Soil water level number and `sprinklecast.set_soil_water_level`. The percent is stored as depletion against that zone's total available water, including the learned factor, and the read-only soil water sensor shows the same percent. A leftover Smart Water hub is imported from Settings → Add integration → Sprinklecast when no YAML key is present. The copy reads `.storage` even if the startup file list missed it, keeps Automatic watering unless Mode was Off, and keeps each zone's deficit and history. A repair deletes a leftover `custom_components/smart_water` folder. Config entry version stays 10. Version 0.12.0 is the Sprinklecast domain (`custom_components/sprinklecast`). A leftover Smart Water config entry is copied, including subentries, `.storage`, and entity registry rows, and the entity IDs stay. Config entry version is 10. The hub mode and the recent-rain skip are gone. Automatic watering is the only valve on/off. Send plan notifications is independent of that switch. A calendar entity lists each planned burst and completed runs from history. The dashboard card is a day strip plus one row per burst. 0.11.1 lists the next watering days (one per allowed weekday, inside the year-long projection) on the schedule sensor and the dashboard card. Calendar days with no watering are left out. A day past the weather forecast sets `estimated`; the text keeps the exact date and time. 0.11.0 computes a morning irrigation plan and, when the hub's Automatic watering switch is on, runs it. A new hub turns Dynamic start time on: the run aims to finish at that day's local sunrise (astral, from Home Assistant's location, so the clock moves with the season and daylight saving). The start is sunrise minus every cycle and soak, and it never opens before Don't start before. If that floor is used, the run may finish after sunrise as long as it ends by the finish time (default 09:00); the rest waits for the next allowed day. Dynamic start time off keeps the 0.10.1 rule: open at the start time, and cycles that would pass the finish time wait. Valve time that cannot finish by then may still open as early as Don't start before, and no earlier. An existing hub is migrated with Dynamic start time explicitly off, so it is not asked to run setup again. Start, finish-by, sunrise, and the projected next watering are wall-clock times in Home Assistant's time zone, including both daylight-saving mornings. Next watering is an exact local date, projected out to about 365 days. A disabled or fully dormant zone stays unknown and says why. The flow meter is one hub setting (whole-home or irrigation-only). Soil moisture level is the raw sensor percent, and moisture and flow entities exist only when those sensors are set. Config entry version is 9. The switch is off on a new install and stays off across the upgrade, so an existing hub does not start watering by itself. `would_execute` is true only when that switch is on. Run now ignores the switch. The plan is made at the plan hour and the valves open at the start time (default 05:00), finishing by 09:00. 0.7 caps each zone on its own, waits for confident forecast rain, sends a freeze notice, and ships a Lovelace card. Flow learning and gallon totals stay.

`executor.py` turns on the entity stored in `valve_entity`. That selector accepts `switch`, `valve`, and `input_boolean`. The services are `switch.turn_on` / `turn_off`, `valve.open_valve` / `close_valve`, and `input_boolean.turn_on` / `turn_off`. It does not call a controller API or `hydrawise.start_watering`. Simulation entity ids (`simulation.*`) are never passed to a service.

## Layout

| Module | Role |
| --- | --- |
| `et.py` | FAO-56 Penman-Monteith and Hargreaves ET0 |
| `observe.py` | One local day's temperature range, rain, and solar integral |
| `balance.py` | Root-zone bucket, RAW, and the 0.2 × ET0 rain rule |
| `presets.py` | Cited soil, plant, sun, and sprinkler defaults. Blank zone fields read this module |
| `discover.py` | Suggest a weather entity and Tempest-style sensors during setup. No Home Assistant import |
| `soil.py` | Looks up the presets for the bucket and the cycle-and-soak math |
| `cycle_soak.py` | Runtime, max cycle, and soak |
| `schedule.py` | Allowed weekdays and an optional blackout. Retired day presets are migrated here |
| `skips.py` | Rain, freeze, wind, moisture, days, interval, and dormancy |
| `dormancy.py` | 7-day air-temperature mean and optional winter maintenance |
| `learn.py` | Slow available-water factor from a moisture sensor |
| `week_plan.py` | Next watering days, reusing the planner |
| `moisture.py` | Sensor deficit, correct, and override |
| `flow.py` | Delivered volume versus expected, leak and low-flow labels |
| `flow_learn.py` | Median gallons per minute, baseline comparison, and high, low, trend, and idle alerts |
| `timing.py` | Moves the dawn deadline earlier when the hourly forecast is windy |
| `usage.py` | Date log of gallons, fixed-timer baseline, and cost |
| `planner.py` | Due check, one-valve timeline, morning window, per-zone valve cap |
| `executor.py` | One sequence of on/off commands, with confirmation |
| `coordinator.py` | Hourly read, evening commit, arming, and bucket credit |
| `store.py` | Restart persistence, storage version 1 |
| `safety.py` | `would_execute` from the automatic switch |
| `calendar.py` | Planned bursts and completed runs |
| `legacy.py` | Smart Water config-entry import |
| `repairs.py` | Deletes a leftover `custom_components/smart_water` folder |

Platforms are sensor, switch, number, button, and calendar. Zones are config subentries. The hub options flow edits behavior and sensors. The only on/off service calls are in `executor.py`.

## Weather and ET

Entity sensors are preferred. The weather entity is the fallback for temperature, humidity, wind, today's rain, and tomorrow's forecast rain.

Penman-Monteith runs when humidity and wind are present. Radiation is, in order:

1. The day's integrated W/m², converted with `W/m² × hours × 0.0036 = MJ/m²`. Samples more than 6 hours apart are not joined. A Tempest solar-radiation entity is this case.
2. A sensor that already reports daily MJ/m².
3. The UV-index fallback, `UV × 100 W/m²`, integrated the same way. This factor is not from FAO-56. It is used only when the solar entity is empty.
4. The Hargreaves radiation estimate inside Penman-Monteith.

Temperature-only days use Hargreaves ET0. A temperature entity tracks the day's high and low. The range replaces the forecast only after it is at least 0.5 °C, so a single reading cannot zero the radiation estimate. Pressure is the current station-pressure reading when a sensor is set; otherwise elevation supplies it (default 219 m).

Rain accumulation:

| Kind | Behavior |
| --- | --- |
| Daily total | Replaces today's millimeters. Tempest "rain today". |
| Cumulative | First sample is a baseline and adds nothing. Later increases add. A drop (counter reset) is ignored. |
| Rate | mm/h, trapezoid between samples, 6 hour maximum gap. |

Today's bucket uses the rain-amount sensor only. Forecast precipitation is never copied into today's rain. Tomorrow's forecast is still the optional skip check, and that check is off until a threshold is set. Effective rain is the FAO-56 rule already in `balance.py`: precipitation below 0.2 × ET0 is ignored. The rain sensor publishes the raw total, the effective total, and whether the day was ignored.

Positive rain deltas are stored as events and kept for about 48 hours, including across midnight. The recent-rain skip no longer reads them. Measured rain is credited in the bucket. A daily-total decrease corrects only events from that same calendar day. A midnight reset to zero does not erase yesterday.

When the weather entity is unavailable and a temperature sensor has a usable range, the "weather unavailable" error is cleared so the sensor path can stand alone.

## Bucket

For each zone, total available water is available-water capacity times root depth. A stored available-water override wins. Otherwise the soil preset is used (the FAO-56 Table 19 midpoint, except where the table below says a source has no row). MAD (`p`) is the stored depletion or the plant preset, then the FAO ET adjustment. Kc is the stored override, which replaces both the plant coefficient and the sun factor, or the monthly turf coefficient (annual average when the month is unknown) times the sun factor. ETc is Kc × ET0.

The evening update, or an early `calculate_plan`, commits one day:

`Dr = clamp(Dr + ETc − effective rain − irrigation, 0, TAW)`

The same calendar day does not commit twice. A finished cycle subtracts the net depth that was actually applied: minutes/60 × precipitation rate × efficiency, converted to millimeters, unless a flow total increased during the cycle. In that case the credit is gallons / (area × 0.623) × efficiency. `mark_watered` and the bucket services still adjust the deficit directly. The daily job does not credit a plan that has not run.

A zone is due when deficit ≥ RAW, or ≥ a target depth when the zone sets one. The plan look-ahead defaults to 0, so tomorrow's ET does not make tonight due. The depth placed on the timeline is the current deficit times the adjustment percent. After a zone is due, the minimum interval still applies: 3 days for turf, 7 for shrubs, trees, native plantings, and drip beds, 2 for vegetables and flowers. A zone with no `last_watered` date is not blocked by the interval. The live coordinator passes the interval. The simulation week does not, so the example weeks stay a weather exercise.

## Moisture

Optional, per zone, default off.

Relative readings are percent of available water. 100 (or 1.0) is field capacity. 0 is wilting. A reading in 0–1 is a fraction. Deficit = TAW × (1 − percent/100).

Volumetric water content needs field capacity. Readings above 1.5 are treated as percent. Deficit = max(0, (θFC − θ) × Zr in meters × 1000).

**Override** replaces the bucket on every coordinator update. **Correct** blends once, on the update that commits the daily balance: `(1 − weight) × bucket + weight × sensor`, weight default 0.5. The moisture sensor shows the sensor deficit even when the mode is correct and today's balance has not committed yet.

## Flow

Optional, per zone. A total or a rate is integrated like rain (baseline on the first total, trapezoid for a rate, reset at local midnight). Units convert to US gallons.

Expected gallons prefer precipitation rate × area × 0.623 gallons per inch-square-foot. Otherwise they use zone GPM × runtime minutes. Classification is a label only:

| Status | When |
| --- | --- |
| `not_configured` | No flow entity |
| `no_data` | No expected volume and nothing meaningful delivered |
| `pending` | A run is on the timeline and now is still inside its window |
| `low_flow` | After the window, delivered/expected is below the low ratio (default 0.5) |
| `leak` | Ratio above the leak ratio (default 1.5), or at least 1 gallon delivered with nothing scheduled |
| `ok` | Otherwise, once the window has passed |

## Planner

Runtime minutes = 60 × (net inches / efficiency) / precipitation rate. Net inches are the adjusted deficit. Efficiency is the stored value or, when that field is blank, the sprinkler preset. Whole-minute rounding is on unless the hub turns it off; off keeps 0.1 minute.

Precipitation rate is the stored inches per hour, otherwise `96.25 × GPM / area` when both are set, otherwise the sprinkler preset. A bubbler has no published rate, so the form requires one of the first two. Intake is the stored inches per hour or the NRCS table at the stored slope (blank slope is 0%, the 0–5% band). Root depth is the stored inches or the plant preset.

Max cycle = floor(60 × NRCS intake in/hr / precipitation rate), at least 1. The design example is clay loam, 5–8% slope, intake 0.10 in/hr, sprays at 1.5 in/hr: a 4 minute cycle. A 20 mm deficit at efficiency 1 is 31 minutes (31.5 if rounding is off). Soak is 30 minutes for every soil, including clay, clay loam, and compact silt loam. Through 0.10.1 those three used 60 minutes. A zone that leaves Soak blank uses this preset, so an existing zone that never stored a soak picks up 30. A stored soak replaces it. Drip and bubbler soak 0 unless the zone sets an override. A pooling test can override cycle and soak.

Cycles share one timeline. A zone cannot start its next cycle until its soak has elapsed. Another zone may run in that gap. With Dynamic start time off, the block starts at the target start (default 05:00). Soak gaps do not pull that start earlier. If the valve time would pass the finish time (default 09:00), it may open earlier, down to Don't start before (default 04:00), and the rest is carried. With Dynamic start time on, the block is placed so the last cycle ends at that morning's sunrise. The start is never before Don't start before. If the floor is used, the run may end after sunrise and must still end by the finish time. Today's plan and the projection use the same rule. A later morning that catches up deferred minutes uses it too.

`clip_blackout` then keeps a single interval that still ends at the finish time:

- If the finish time falls inside `[start, end)`, it moves back to `start:00`.
- A finish in the morning (before the blackout, or exactly at its start) may begin at midnight, but not earlier than Don't start before.
- A finish after the blackout may begin at the blackout end.

Allowed weekdays are checked against the first cycle, the morning the valves open. None means every day. An empty selection means no day. Drip skips the weekday check only when the hub option is on. It does not get its own timeline, so the blackout still applies.

If the timeline is longer than the window, the prefix that fits is kept and the rest stays in the bucket. Soak times are not scaled. A daily runtime cap still scales cycle lengths. The plan carries a warning instead of pretending a soak-bound timeline fits.

## Allowed days

The form is a multi-select of Monday through Sunday. A new hub selects every day. The blackout hours stay optional.

Config version 4 migration rewrites hub options and does not rewrite zone numbers. A stored odd-address preset becomes Sunday, Tuesday, and Thursday with blackout 10:00–19:00. A stored even-address preset becomes Monday, Wednesday, and Saturday with the same blackout. Any other value, including a missing preset, allows every day and keeps a blackout the user already saved. The dry-run option is dropped. Automatic watering is a store flag, default false, and is not copied from dry-run.

## Skips

`skip_reason` returns the first match: disabled, flow lock, skipped-until, rain sensor, currently raining, temperature or forecast low at or below the freeze limit, wind at or above the sprinkler limit, moisture fuller than the threshold, then a forecast deferral when the zone is due, then the older forecast-depth skip, a day that is not allowed, a closed window, the minimum interval, dormancy without maintenance due, then not due. The deferral sentence is `Deferred for forecast rain (70% / 0.4 in).` Expected rain is probability times depth over the forecast window (default 48 hours), counting only slots at or above 60%. It waits at most 2 mornings. Forecast depth is never subtracted from the bucket. Manual run-now sets `include_schedule` false, so it still applies the safety checks and skips the day, window, interval, and dormancy stop. It does not wait for forecast rain.

Defaults, and the citations, are in the README. Freeze is 40°F. Recent rain is 2.5 mm in 12 hours, a practical default rather than a published duration. Wind is 10 / 12 / 15 mph for spray, MP rotator, and rotor. Drip and bubbler have no wind skip. The moisture threshold is `1 − p` unless the zone sets a percent. Forecast skip stays unset.

The executor calls the same checks again immediately before each cycle, and scales or skips the cycle when rain since the plan was armed has already covered part of that zone's net depth.

## Dormancy

`dormancy.classify` needs at least three distinct daily mean air temperatures and then uses up to seven. Warm-season grasses (Bermuda, Zoysia, Buffalo, and the generic warm-season row) are slow below 55°F and dormant below 50°F. St. Augustine is slow below 60°F and dormant below 55°F, five degrees higher because AgriLife ranks it as more winter-injury susceptible. That shift is a judgment, not a separate published cutoff. Cool-season turf is slow at a 7-day mean of 80°F or more and has no temperature-only full stop. Anything that is not turf stays active. Slow multiplies that day's crop ET by 0.5. Dormant removes the zone from the regular plan.

Winter maintenance is off unless the zone enables it. When it is on, a dormant zone that is also at RAW, under the recent-rain limit, and at least 21 days since the last watering (or never watered) is capped at 0.25 inch. The air mean is a proxy for soil temperature.

## Learning

When a moisture sensor is present and learning is not turned off, one update per day adjusts an available-water factor. Model fraction full is `1 − deficit / (TAW × factor)`. TAW in that formula is the unscaled total; the factor scales it. The step is `0.05 × (sensor full − model full)`, clamped to 0.7–1.3. Those bounds are engineering limits. Confidence is `min(1, samples / 14)`. The update is skipped when today's rain is at least 2.5 mm, when the zone was watered today or yesterday, or when today's sample was already applied. It is computed before the plan and stored after the plan, so it affects the next day. It is not written into the available-water override. `reset_learning` sets the factor to 1, confidence to 0, and the sample count to 0.

## Executor

One task runs the timeline in order. Soak gaps are already in the automatic start times, so automatic jobs do not add a second soak sleep. A manual run places soak sleeps between its own cycles. Two entities are never on together.

Each command is confirmed against the entity state. Valve `opening` and `closing` count as success. Up to three attempts, one second apart. A failure is logged. If turn-on never confirms, that cycle is not slept and the result says the entity could not be turned on. The `finally` of a cycle turns the entity off, including when the task is cancelled. Startup calls `async_quiesce` before the first refresh and turns off `watering_entity` when one was saved. Home Assistant's stop event, entry unload, and `stop_all` do the same.

The per-zone cap (default 60 minutes, hub option `zone_max_run_min`, overridable on the zone as `max_run_min`) is valve-on minutes for that zone on that morning. Soak does not count. An optional hub total (`hub_nightly_cap_min`) is off unless set; it limits every zone together after each zone's own cap. Version 6 copies a stored `max_run_min` onto `zone_max_run_min` and does not turn the hub total on. The planner keeps the higher-priority cycles that fit before the finish time. Unapplied minutes stay in the deficit. The next allowed day continues only when the remainder is still at RAW; otherwise the minimum interval starts. A cycle is also shortened so it ends by `finish_by`. Under half a minute after shortening, the cycle is skipped. Manual runs and catch-cup audits have no `finish_by` and still stop at the zone cap.

An empty automatic job list does not call `start`, so a quiet night does not cancel a manual run that is already going. Bucket credit runs outside the build lock and refreshes the snapshot without starting another sequence.

## Overrides

| Control | Stored effect |
| --- | --- |
| Skip until a date | `skipped_until`, inclusive of that morning |
| Pause N days | `skipped_until = today + N`. Zero clears it |
| Adjustment percent | Scales planned net depth. Does not change the stored deficit. 0 means not scheduled. Also a number entity, 0–300, step 1 |
| Set / reset bucket | Absolute deficit, clamped to TAW |
| Mark watered | Subtracts a net depth, or refills when the depth is omitted |
| Run now | Builds cycle-and-soak for the adjusted deficit and runs it, even when automatic watering is off. Credits each cycle. Still applies freeze, wind, rain, and moisture. The button calls the same method |
| Stop all | Cancels the sequence and turns the recorded entity off |
| Reset learning | Factor 1, confidence 0, samples 0 |
| Reset flow learning | Clears GPM samples, the learned rate, the alert, and `flow_locked`. An empty zone also clears the hub lock |
| Automatic watering | Store flag. On and off do not write options. Off stops the executor. The evening plan notification is a separate option |

## Flow learning and gallons

`flow_learn.py` keeps up to 12 positive samples and uses their median. Alerts wait until `flow_learn_runs` samples exist (default 3). High is default +30% of that median, low is −25%. A sample above 2× or below 0.4× the median, once the median exists, raises the alert and is not appended. Idle flow is default 0.5 gal/min on a rate sensor, or a 1 gallon increase on a total, and only while `watering_entity` and the executor's current zone are both empty. The same main-leak alert does not fire twice on the same date.

Actions are per alert type, default `notify`. `stop` sets `flow_locked` on that zone, or on the hub for a main leak, and `skip_reason` then says a flow alert is waiting for reset. The main-leak stop is scheduled only after the coordinator releases its lock, so it cannot deadlock with cycle credit. Events: `smart_water_flow_alert`, `smart_water_budget_alert`, `smart_water_weekly_summary`. The repair translation key is `flow_alert`.

Lifetime gallons are `total_increasing` in gal with device class water. Day, week, and month are attributes of a date log (`water_days`, 400 days). A period that resets is not `total_increasing`. Cost is lifetime gallons / 1000 × `cost_per_1000_gal`, and the sensor is created only when that option is set. The fixed-timer baseline is 15 minutes × 3 days a week unless the zone stores `baseline_minutes` or `baseline_days`. Saved gallons are baseline minus the last 7 days. The weekly budget alerts once per ISO week. The Monday summary is off unless `weekly_summary` is set, and it runs at or after the plan hour.

Zone order in the scheduler is priority, then a larger deficit, then name. `timing.calm_finish` walks the finish time back to the start of a trailing windy hour when the hourly forecast at that hour is at or above the strictest `wind_limit_mph` of zones that will run. Drip and bubbler limits are null and do not count. The run stays inside the earliest start and the finish time. Hourly wind is applied to day 0 of the week projection only.

## Persistence and config

`SmartWaterStore` uses Home Assistant `Store` version 1, key `sprinklecast.{entry_id}`. The file holds per-zone deficit, balance date, skip, enabled, adjustment, flow cursor, last run-now text, moisture deficit, the last plan, the last ET0, and the weather-day accumulator. Loading merges each zone over `fresh_zone()` and the weather dict over `fresh_day()`, so a 0.1 file gains the new keys without a migration. Storage version is not bumped, because a bump without a migration drops the file.

The config entry version is 10. `async_migrate_entry` bumps an older entry. Versions below 4 still rewrite schedule options through `migrate_options`. The steps from 4 onward do not, so days the user already chose stay put. Version 6 only moves the old hub runtime cap onto the per-zone default. Version 7 replaces the sunrise buffer and earliest hour with a 05:00 start, a 09:00 finish, and a 04:00 earliest start. Version 8 moves the first zone flow sensor onto the hub. Version 9 writes `dynamic_start` false so an existing hub keeps the fixed start. Version 10 drops mode and the recent-rain options. Mode off stores automatic watering off. It does not rewrite zone data. Root depth, depletion, efficiency, slope, and precipitation rate saved by the 0.2 forms stay overrides, so an old efficiency of 1.0 is not replaced by the sprinkler preset. New zones leave those keys out. Storage version is still 1. The store file may also hold `automatic` (default false), `watering_entity`, `temp_history`, `armed_date`, `plan_marked_at`, and a `simulation` object. Loading treats a missing key as the fresh-hub default, so an older file does not come back with automatic watering on.

Setup starts with a menu. A live hub is one form (name, optional weather, collapsed sensors, collapsed location and schedule) and two zone steps (the on/off entity plus four dropdowns, then collapsed overrides). A simulation hub drops the weather entity and the on/off entity and adds optional area and slope on the zone step. Suggested values are used only for entities the discovery step found and for numbers the zone already stored. Preset numbers are description text. Writing them into the inputs would save them and blank would stop meaning preset.

Config forms use `homeassistant.helpers.selector` selectors. Number steps are at least 0.001. Latitude and longitude use step `"any"` because Home Assistant 2026.10 rejects a smaller step before the form exists, and that exception becomes a plain `400: Bad Request`.

## Defaults

Every number is in `presets.py` with the source string used to choose it. Ranges below are copied from the cited table. The value used is the midpoint unless the note says a source has no row.

### Soil

Available water is θFC − θWP from FAO-56 Table 19, m³/m³ (the same as in/in). Intake is inches per hour at NRCS slope bands 0–5 / 5–8 / 8–12 / 12–16, from the NRCS suggested maximum application rates reproduced by Michigan State University (`NRCSIrrMngmt.pdf`). The upper edge of a band stays in that band. Steeper than 16% uses the 12–16% rate.

| Soil | AWC | Intake (in/hr) | Note |
| --- | --- | --- | --- |
| Sand | 0.08 | 2.0, 1.5, 1.0, 0.50 | Table 19 sand 0.05–0.11. NRCS coarse sandy soil to 6 ft |
| Sandy loam | 0.13 | 1.0, 0.80, 0.60, 0.40 | Table 19 sandy loam 0.11–0.15. NRCS light sandy loams |
| Loam | 0.155 | 0.50, 0.40, 0.30, 0.20 | Table 19 loam 0.13–0.18. No NRCS loam row, so the silt-loam-to-6-ft intake is used |
| Silt loam | 0.16 | 0.50, 0.40, 0.30, 0.20 | Table 19 silt loam 0.13–0.19 |
| Silt loam, compact subsoil | 0.16 | 0.30, 0.25, 0.15, 0.10 | No FAO row. AWC is the silt-loam midpoint. Intake is the NRCS compact-subsoil row |
| Clay loam | 0.16 | 0.15, 0.10, 0.08, 0.06 | No FAO clay-loam row. AWC uses the clay range 0.12–0.20 because NRCS groups heavy clays and clay loams. NRCS NEH Part 652 lists a typical clay-loam AWC near 0.20 in/in; set the override to 0.20 to use that. Not averaged in |
| Clay | 0.16 | 0.15, 0.10, 0.08, 0.06 | Table 19 clay 0.12–0.20. Same NRCS intake row |

FAO-56 says fine soil can lower the depletion fraction 5–10% and coarse soil can raise it 5–10%. That adjustment is not applied. MAD is a plant property.

### Plants

Turf crop coefficients are the monthly landscape coefficients from Meyer, Gibeault, and Youngner (1985), as republished by UC ANR, not FAO-56 Table 12 (cool-season mid 0.95, warm-season mid 0.85). The published annual averages are 0.80 cool and 0.60 warm. Texas A&M AgriLife's water-wise checklist says to replace about 60% of reference ET on a warm-season lawn and to water to about 6 inches. That 6 inches is the managed depth. FAO-56 Table 22 lists turf rooting at 0.5–1.0 m.

Warm-season monthly Kc, January–December: 0.55, 0.54, 0.76, 0.72, 0.79, 0.68, 0.71, 0.71, 0.62, 0.54, 0.58, 0.55. Cool-season: 0.61, 0.64, 0.75, 1.04, 0.95, 0.88, 0.94, 0.86, 0.74, 0.75, 0.69, 0.60. January warm-season is 0.55, matching the UC ANR PDF tables. One HTML copy of the same table prints 0.61.

| Plant | Kc | p | Root depth | Source for the choice |
| --- | --- | --- | --- | --- |
| St. Augustine | warm monthly, annual 0.60 | 0.50 | 6 in | Meyer warm-season group, which includes St. Augustine. ASABE S623 / UC ANR plant factor 0.6. A Texas A&M lysimeter thesis (Wherley, 2021–2022) measured well-watered St. Augustine nearer 0.8–0.9; raise the override for that. FAO-56 Table 22 warm-season turf names St. Augustine, p=0.50. Peacock and Dudeck 1985 found about 91% of roots in the top 30 cm |
| Bermuda | warm monthly, annual 0.60 | 0.50 | 6 in | Same Meyer table. The lysimeter work found Tifway and TifTuf near 0.6. AgriLife 2010 TTREEE found roots at 10–20 in; managed depth stays 6 in |
| Zoysia | warm monthly, annual 0.60 | 0.50 | 6 in | Meyer warm-season group. The lysimeter work called zoysia intermediate. AgriLife 2010 found few matrella zoysia roots at 10–20 in |
| Buffalo | warm monthly, annual 0.60 | 0.50 | 6 in | Not in the Meyer species list. UC ANR / ASABE S623 group it with the other warm-season grasses at 0.6, so it uses that table. FAO-56 Table 22 names buffalo grass |
| Warm-season grass | warm monthly, annual 0.60 | 0.50 | 6 in | Same table. Matches AgriLife's "about 60% of reference ET" |
| Cool-season grass | cool monthly, annual 0.80 | 0.40 | 6 in | Meyer cool-season trial (tall fescue, ryegrass, bentgrass, Kentucky bluegrass). Table 22 p=0.40 |
| Shrubs | 0.50 | 0.50 | 24 in | ASABE S623 woody-plant factor 0.5. p=0.50 is FAO-56 Chapter 8's common value; Table 22 has no landscape-shrub row. 24 in is the berries/bushes lower bound, 0.6 m, rounded |
| Flower bed / annuals | 0.80 | 0.50 | 12 in | ASABE annuals and bedding plants, plant factor 0.8. No FAO bedding-plant row. 12 in is the 0.3 m shallow-vegetable scheduling depth |
| Vegetables | 1.00 | 0.50 | 12 in | ASABE home vegetable crops, plant factor 1.0. Table 12 mid-season values are often 1.05–1.15. Table 22 p runs from about 0.20 to 0.50; 0.50 is the Chapter 8 common value. Tomato's lower bound is about 0.7 m (28 in) |
| Trees | 0.50 | 0.50 | 39 in | ASABE woody-plant factor 0.5. 39 in is the Table 22 fruit-tree lower bound, 1.0 m, rounded. Ornamental shade trees are not a row |
| Drip bed | 0.50 | 0.50 | 24 in | Mixed ornamental bed uses the woody-plant factor. Switch to flowers or vegetables when those are what is planted |
| Native / desert-adapted | 0.30 | 0.50 | 24 in | ASABE desert-adapted plant factor 0.3. Depth matches the shrub scheduling depth |

Sun is a WUCOLS microclimate factor (Costello and Jones): average kmc 1.0, low/protected 0.5–0.9. Full sun is 1.0. Part sun is 0.9, the top of the low range. Shade is 0.7, the midpoint of 0.5–0.9. The high/exposed range 1.1–1.4 is not applied automatically.

### Sprinklers

Efficiency is the net/gross fraction, the same role as a lower-quarter distribution uniformity. It is a literature default, not an audit of a yard.

| Type | Precipitation | Efficiency | Source for the choice |
| --- | --- | --- | --- |
| Spray | 1.25 in/hr | 0.60 | Midpoint of 1.0–1.5 in/hr. The Irrigation Association Homeowner's Guide (2017) says fixed sprays apply two to three times a rotor's half inch. Efficiency is the midpoint of the IA 2004 BMP minimum spray DU (0.55) and the EPA WaterSense draft spray-nozzle DULQ (0.65) |
| Rotor | 0.50 in/hr | 0.70 | IA Homeowner's Guide: gear-drive rotors apply about one-half inch per hour. A city handout has listed rotors at 0.8 in/hr; that is an override, not the default. Efficiency is the IA 2004 BMP minimum rotor DU |
| MP rotator | 0.40 in/hr | 0.65 | Hunter MP Rotator design guide, standard nozzles, about 0.4 in/hr. MP800 is about 0.8 and must be typed in. Efficiency uses the WaterSense draft DULQ; ASABE/ICC 802 classes multi-stream nozzles with sprays. The rotor BMP 0.70 is the alternative if you audit them as rotors |
| Drip | 0.50 in/hr | 0.875 | A municipal average-rate sheet assumes two 2 gph emitters over an 800 sq ft canopy. Not a universal drip rate. Efficiency is the midpoint of 0.85 surface and 0.90 subsurface from the 2021 IWAC landscape-efficiency webinar. EPA's "20–50% less than sprays" is not used as a number |
| Bubbler | none | 1.0 | No published precipitation rate or distribution uniformity was found in FAO-56, the Irrigation Association guides, or the MP Rotator design note. Adjustable bubblers are sold around 0.25–2 gpm, which is not a rate without area. Efficiency stays 1.0 so an unpublished uniformity is not assumed |

## Simulation

A simulation hub is a separate config entry (`data.simulation` true), chosen from the first menu. It stores no weather entity. Zone on/off ids are `simulation.<slug>` labels created by the zone flow, including when an existing simulation zone is edited. The week runner calls `daily_et0`, `apply_daily_balance`, `build_zone_request`, and `build_plan`. Crop ET and total available water for the bucket step come from `build_zone_request`, so a stored override is the one the live coordinator would use. After a scheduled night the in-memory deficit loses `net_mm`, the same subtraction as `mark_watered`. That credit is not written to the live deficit.

Cloudiness is FAO-56 equation 35. Relative sunshine is `1 − cloud`, and solar radiation is `(0.25 + 0.50 × n/N) × Ra`. The named weeks are example days with round numbers. They are not climate normals. Starting soil is field capacity, half of total available water, or readily available water (table depletion, because the starting deficit is computed with no ET0).

The first refresh of a simulation hub that already has zones and an empty stored week runs the preset so the sensor is populated. Later refreshes do not rerun it. `sprinklecast.simulate` replaces the stored week and returns the same dict (`supports_response`). The Simulation sensor publishes the markdown and the day list. A live hub can call the service too. That call does not change its stored deficit and does not create the simulation sensor.

## What is stored and what is actuated

Stored: `valve_entity`, the bucket, last run, the learned factor, dormancy, and `watering_entity` while a cycle is on.

Computed and published: ET0, rain and effective rain, deficit, RAW, the nightly timeline, the next-run timestamp, the watering-day schedule, currently watering, the per-zone plan, last run, dormancy, flow status, moisture deficit, adjustment.

Actuated, and only from `executor.py`: the zone's switch, valve, or input boolean. Other `hass.services.async_call` sites are `weather.get_forecasts` and the user-configured notify target. A simulation hub never reaches the executor with a real entity id. `would_execute` on a simulated week is false.
