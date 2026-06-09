# Charge session fixtures

Small CSV files used by the pure-core analyzer before real Home Assistant
entities exist. Each row is `timestamp,power_w[,temperature_c]`; `power_w` is
wall power from the dedicated metering smart plug (ADR-0001), and the analyzer
subtracts the charger's idle watts before integrating active Wh. The same plain
row shape is what Home Assistant history exports into (ADR-0010), so these
fixtures and real exported history run through the identical code path.

## Library

| File | Shape | Exercises |
|---|---|---|
| `synthetic-low-to-full.csv` | Clean CC ramp 69->84 W, CV taper to ~18 W, completion to idle | Happy path: anchors + active Wh + landmarks, no warnings (BDD A/B) |
| `synthetic-noisy-low-to-full.csv` | Same shape with +/-1-2 W measurement noise and temperature jitter | Detection robustness to realistic noise |
| `synthetic-interrupted.csv` | Low-to-full with a 4-hour gap mid-session | Interruption warning; not trusted for calibration (BDD D) |
| `malformed-missing-power.csv` | Header lacks `power_w` | Structural validation error (BDD C) |
| `synthetic-with-unknown-rows.csv` | Contains `unknown` / empty / `unavailable` cells | Robust-to-unknown row skipping (ADR-0010 / guardrails) |
| `real-swoop-asm-charge.csv` | **Real** Swoop ASM session: 0/5 dots (assist cutoff) up past the CC->CV transition, cut off mid-taper | First real-data validation of detection + the ADR-0010 import path |

Timestamps are valid ISO-8601 with offsets; sessions that cross midnight roll
the date forward (e.g. `...T23:50` -> next day `...T00:00`) rather than using
invalid hours like `24:00`.

## The real fixture

`real-swoop-asm-charge.csv` is derived from a Home Assistant history export
(`entity_id,state,last_changed` long format). The analyzer-ready file keeps the
`sensor.utility_smartplug_1_power` series (watts) as `power_w`, forward-fills the
`sensor.garage_sensor_temperature` reading (converted from degF to degC) as
`temperature_c`, and drops the pre-session row before the relay turned on. UTC
millisecond `...Z` timestamps are kept verbatim (the parser handles them).

Real-world findings this fixture surfaced (documented in
`tests/test_real_fixture.py`, not yet "fixed"):

1. **Onset/inrush:** `watts_at_low` latches onto the inrush ramp (~65.7 W) rather
   than the settled CC value (~69.7 W). Onset robustness is a calibration-slice
   refinement.
2. **Mid-taper cutoff:** the session was de-energized during early taper, so
   `taper_floor_w` reflects the cutoff reading, not a true CV floor, and
   "completion" is the relay-off event.
3. **Cross-check:** integrated `active_full_wh` (586.8 Wh) matches the plug's own
   cumulative energy meter delta (~580 Wh) to ~1%.

Additional real exported sessions can be dropped in the same way; gaps and
`unknown`/`unavailable` rows are expected and handled.
