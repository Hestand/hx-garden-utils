# Smart Water design

Version 0.3.0 computes a nightly irrigation plan and exposes it as sensors. It does not water. `safety.EXECUTION_IMPLEMENTED` is false, so `would_execute` is false for every mode, including auto with dry-run off.

A later executor will turn on the entity stored in `valve_entity`. That selector accepts `switch`, `valve`, and `input_boolean`, which covers a Home Assistant valve, a switch, or a controller zone that Home Assistant already exposes as one of those. The executor must call that entity. It must not call Hydrawise APIs or `hydrawise.start_watering`.

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
| `schedule.py` | Allowed weekdays and blackout, including the Waco preset |
| `moisture.py` | Sensor deficit, correct, and override |
| `flow.py` | Delivered volume versus expected, leak and low-flow labels |
| `planner.py` | Due check, one-valve timeline, sunrise finish |
| `coordinator.py` | Hourly read, evening commit, snapshots |
| `store.py` | Restart persistence, storage version 1 |
| `safety.py` | The execution guard |

Platforms are sensor, switch, number, and button. Zones are config subentries. The hub options flow edits behavior and sensors. Nothing in those platforms calls an on/off service.

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

If a rain-amount sensor is configured, forecast rain is not used for today's bucket even when the sensor is briefly unavailable. Tomorrow's forecast is still the skip check. Effective rain is the FAO-56 rule already in `balance.py`: precipitation below 0.2 × ET0 is ignored. The rain sensor publishes the raw total, the effective total, and whether the day was ignored.

When the weather entity is unavailable and a temperature sensor has a usable range, the "weather unavailable" error is cleared so the sensor path can stand alone.

## Bucket

For each zone, total available water is available-water capacity times root depth. A stored available-water override wins. Otherwise the soil preset is used (the FAO-56 Table 19 midpoint, except where the table below says a source has no row). MAD (`p`) is the stored depletion or the plant preset, then the FAO ET adjustment. Kc is the stored override, which replaces both the plant coefficient and the sun factor, or the monthly turf coefficient (annual average when the month is unknown) times the sun factor. ETc is Kc × ET0.

The evening update, or an early `calculate_plan`, commits one day:

`Dr = clamp(Dr + ETc − effective rain − irrigation, 0, TAW)`

The same calendar day does not commit twice. Irrigation during the day is only `mark_watered` or a manual bucket set. The daily job does not credit the plan as if it had run.

A zone is due when deficit ≥ RAW, or when deficit plus the look-ahead days of ETc would reach RAW. The depth placed on the timeline is the current deficit times the adjustment percent, not the extra projected days.

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

Max cycle = floor(60 × NRCS intake in/hr / precipitation rate), at least 1. The design example is clay loam, 5–8% slope, intake 0.10 in/hr, sprays at 1.5 in/hr: a 4 minute cycle. A 20 mm deficit at efficiency 1 is 31 minutes (31.5 if rounding is off). Soak is 60 minutes for clay, clay loam, and compact silt loam, otherwise 30. Drip and bubbler soak 0 unless the zone sets an override. A pooling test can override cycle and soak.

Cycles share one timeline. A zone cannot start its next cycle until its soak has elapsed. Another zone may run in that gap. The block is shifted so the last cycle ends at the deadline.

The deadline starts as the next sunrise minus the buffer (default 30 minutes). `clip_blackout` then keeps a single interval that still ends at that deadline:

- If the deadline falls inside `[start, end)`, it moves back to `start:00`.
- A deadline in the morning (before the blackout, or exactly at its start) may begin at midnight.
- A deadline after the blackout may begin at the blackout end.

Allowed weekdays are checked against that clipped deadline. An empty list means every day. Drip skips the weekday check only when the hub option is on. It does not get its own timeline, so the blackout still applies.

If the timeline is longer than the window, cycle lengths scale down and soak is kept. A daily runtime cap scales the same way. The plan carries a warning instead of pretending a soak-bound timeline fits.

## Schedule presets

| Preset | Days | Blackout |
| --- | --- | --- |
| `none` | Any | Optional hours from the form |
| `custom` | The selected weekdays, or any day if none are selected | Optional hours from the form |
| `waco_odd` | Sun, Tue, Thu | 10:00–19:00, fixed |
| `waco_even` | Mon, Wed, Sat | 10:00–19:00, fixed |

Waco follows the City of Waco year-round outdoor rules effective 1 July 2024. Friday is not a watering day. The city does not apply the same weekday limit to buried drip. This integration's drip exception is weekday-only and defaults off. A yard that is only drip can stay on preset `none`.

## Overrides

| Control | Stored effect |
| --- | --- |
| Skip until a date | `skipped_until`, inclusive of that morning |
| Pause N days | `skipped_until = today + N`. Zero clears it |
| Adjustment percent | Scales planned net depth. Does not change the stored deficit. 0 means not scheduled. Also a number entity, 0–300, step 1 |
| Set / reset bucket | Absolute deficit, clamped to TAW |
| Mark watered | Subtracts a net depth, or refills when the depth is omitted |
| Run now | Logs the current plan and stores `last_run_now`. Does not credit the bucket and does not call the on/off entity. The button calls the same method |

## Persistence and config

`SmartWaterStore` uses Home Assistant `Store` version 1, key `smart_water.{entry_id}`. The file holds per-zone deficit, balance date, skip, enabled, adjustment, flow cursor, last run-now text, moisture deficit, the last plan, the last ET0, and the weather-day accumulator. Loading merges each zone over `fresh_zone()` and the weather dict over `fresh_day()`, so a 0.1 file gains the new keys without a migration. Storage version is not bumped, because a bump without a migration drops the file.

The config entry version is 2. `async_migrate_entry` bumps a version 1 entry and does not rewrite zone data. Root depth, depletion, efficiency, slope, and precipitation rate saved by the 0.2 forms stay overrides, so an old efficiency of 1.0 is not replaced by the sprinkler preset. New zones leave those keys out. Storage version is still 1.

Setup is one hub form (name, optional weather, collapsed sensors, collapsed location and schedule) and two zone steps (the six required fields, then collapsed overrides). Suggested values are used only for entities the discovery step found and for numbers the zone already stored. Preset numbers are description text. Writing them into the inputs would save them and blank would stop meaning preset.

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

## What is stored and what is actuated

Stored and unused by any service call: `valve_entity`.

Computed and published: ET0, rain and effective rain, deficit, RAW, the nightly timeline, the next-run timestamp, the per-zone plan, flow status, moisture deficit, adjustment.

Actuated: nothing. The only `hass.services.async_call` sites are `weather.get_forecasts` and the user-configured notify target.
