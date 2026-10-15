# Smart Water design

Version 0.2.0 computes a nightly irrigation plan and exposes it as sensors. It does not water. `safety.EXECUTION_IMPLEMENTED` is false, so `would_execute` is false for every mode, including auto with dry-run off.

A later executor will turn on the entity stored in `valve_entity`. That selector accepts `switch`, `valve`, and `input_boolean`, which covers a Home Assistant valve, a switch, or a controller zone that Home Assistant already exposes as one of those. The executor must call that entity. It must not call Hydrawise APIs or `hydrawise.start_watering`.

## Layout

| Module | Role |
| --- | --- |
| `et.py` | FAO-56 Penman-Monteith and Hargreaves ET0 |
| `observe.py` | One local day's temperature range, rain, and solar integral |
| `balance.py` | Root-zone bucket, RAW, and the 0.2 × ET0 rain rule |
| `soil.py` | FAO available water, NRCS intake, plant Kc and MAD |
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

For each zone, total available water is available-water capacity times root depth. Available water defaults to the midpoint of the FAO-56 Table 19 range for the soil. MAD (`p`) and Kc come from the plant preset unless the zone overrides them. Sun exposure scales Kc (full 1.0, part 0.8, shade 0.6). ETc is Kc × ET0.

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

Runtime minutes = 60 × (net inches / efficiency) / precipitation rate. Net inches are the adjusted deficit. Efficiency defaults to 1. Whole-minute rounding is on unless the hub turns it off; off keeps 0.1 minute.

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

The config entry version stays 1. New option and zone keys are optional or defaulted in code: schedule `none`, round minutes on, sprinkler spray, moisture off, adjustment 100, no flow entity. An existing install does not need a reconfigure to keep planning.

Config forms use `homeassistant.helpers.selector` selectors. Number steps are at least 0.001. Latitude and longitude use step `"any"` because Home Assistant 2026.10 rejects a smaller step before the form exists, and that exception becomes a plain `400: Bad Request`.

## What is stored and what is actuated

Stored and unused by any service call: `valve_entity`.

Computed and published: ET0, rain and effective rain, deficit, RAW, the nightly timeline, the next-run timestamp, the per-zone plan, flow status, moisture deficit, adjustment.

Actuated: nothing. The only `hass.services.async_call` sites are `weather.get_forecasts` and the user-configured notify target.
