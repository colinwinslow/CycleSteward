---
title: How temperature affects Li-ion battery charging curves
status: open
date: 2026-06-09
---

# Research: How temperature affects Li-ion battery charging curves

## Question

How does ambient/battery temperature affect the wall-power CC/CV charging curve
we observe through the smart plug, and specifically the `watts_at_low` (starting
wattage) anchor? Is the relationship linear, and is a single linear correction
coefficient adequate for use in CycleSteward's calibration model?

## Context

CycleSteward infers SoC from CC-phase wattage. The `watts_at_low` anchor is
learned from observed starting wattage when the battery is near empty.
Temperature affects cell chemistry and BMS behavior, so the same battery at
the same SoC will draw different wall power at different temperatures.

Two downstream decisions depend on this:

1. **Proximity check (calibration ingestion):** When deciding whether a
   taper-floor session started near-empty, we compare the trace's starting
   wattage to the profile's stored `watts_at_low` anchor. If cold weather shifts
   that wattage, we risk incorrectly rejecting a genuine near-empty session as
   "started mid-charge," or vice versa.

2. **SoC estimation:** `target_wattage()` interpolates between `watts_at_low`
   and `watts_at_transition`. If temperature shifts these anchors, the real-time
   SoC estimate will drift.

Related: `ADR-0008` (temperature compensation), `ADR-0002` (wattage as primary
SoC signal), `docs/specs/ha-calibration-ingestion.md`.

## Notes

### What temperature does to the CC phase

Li-ion cells at lower temperatures have higher internal resistance. At a given
SoC, the charger must work harder to push current through the cell. Two separate
effects result:

**Effect 1 — BMS/charger current reduction (dominant at cold temps)**
Modern BMSes protect cells from lithium plating at low temperatures by reducing
or stepping down the CC charge current. This is the dominant effect in practice
for e-bike BMSes:
- Below ~0°C: hard-stop — no charging (freeze lockout, already in session-control).
- ~0°C to ~10°C: BMS may step down CC current significantly (in discrete stages,
  not continuously). Literature reports standard CC-CV reaching only ~48% of
  normal capacity at −10°C; multistage strategies help but still fall short.
- ~5°C to ~45°C: Shimano's recommended charging window. Within this window the
  BMS allows charging but may still throttle near the lower bound.

**Key consequence for CycleSteward:** A cold session starting from near-empty
will show a *lower* `watts_at_low` than the same session at room temperature,
because the BMS has reduced the CC current. This means cold near-empty sessions
look *more* like empty starts (lower wattage), not less. The risk of incorrectly
rejecting a cold session as "started mid-charge" is therefore lower than
initially assumed — but the calibration anchor (`watts_at_low`) will be
systematically biased downward by cold-weather sessions if we don't correct.

**Effect 2 — Higher internal resistance raises terminal voltage (minor)**
Higher resistance at cold temps means for the same current, terminal voltage is
higher. From the wall perspective this slightly increases power. However, since
Effect 1 (current reduction) dominates, the net wall-power signature at cold
temperatures is generally *lower* in the CC phase, not higher.

### Is the relationship linear?

**In the charging-allowed range (~5°C to 45°C):** Roughly linear as a first
approximation. A single coefficient (W/°C) is a reasonable model.

**Near the lower bound (~5°C to ~15°C):** BMS stepping introduces non-linearity.
Discrete current steps mean the wattage vs. temperature curve is more
step-function than linear in this zone. A linear model will have higher error
here.

**Below 5°C / above 45°C:** Existing guardrails (freeze lockout, heat delay)
prevent charging, so the calibration model never needs to handle these regions.

**Practical conclusion:** Linear correction in the 5°C–45°C window is the right
tool for this integration. It's an approximation — it will underfit near 5°C
where BMS stepping occurs — but the freeze lockout means we never operate below
the worst-fit zone, and real-world variation between sessions at the same
temperature will likely swamp the linearity error anyway.

### Magnitude of the temperature effect

No Shimano-specific data found. General Li-ion literature suggests the CC
wattage shift is on the order of 1–3% per 10°C across the operating range,
but this varies significantly by BMS design and cell chemistry. The existing
`temp_coefficient_w_per_c` default in ADR-0008 was set conservatively; it may
need empirical tuning from real charge logs at varied temperatures.

### Seasonal averaging and de-weighting

One practical strategy: de-weight calibration observations older than ~12 months.
This averages out seasonal temperature variation and also accounts for battery
aging (capacity/resistance drift). Combined with a temperature correction
applied at ingestion time, this reduces the error from both sources:
- Recent observations at the current season's temperatures are most relevant.
- Old observations at very different temperatures contribute less.

The de-weighting is a calibration model concern (inside `CalibrationProfile`),
not a watcher concern. It is deferred to a future calibration slice.

### Implications for the proximity check

The proximity check (deciding "did this session start near-empty?") should
temperature-correct the observed `watts_at_low` before comparing to the profile
anchor. Specifically:

```
corrected_watts_at_low = observed_watts_at_low + coefficient * (ref_temp - session_temp)
```

Where `ref_temp` is the reference temperature at which the profile anchor was
learned (stored in the profile), and `session_temp` is the temperature reading
from the current session (if available).

If no temperature reading is available, the raw wattage is used and the proximity
tolerance should be widened slightly (a session might be incorrectly demoted to
partial, which is a conservative/safe failure mode — it doesn't corrupt anchors).

## Open sub-questions

- What is the actual W/°C coefficient for the Shimano ASM system? Need real
  charge logs at ≥3 different temperatures (e.g., 5°C, 15°C, 25°C) with the
  same bike at similar SoC to measure empirically.
- Does Shimano's BMS step current in discrete stages or smoothly? This would
  tell us how much the linear model errs near 5°C.
- Should the profile store the reference temperature at which `watts_at_low` was
  calibrated, so that temperature correction can be applied consistently?
  Currently it doesn't.
- Is there a warm-end analogue? At >35°C the BMS may also throttle (heat
  protection). Relevant if charging outdoors in summer.

## Resolution

Open. Findings so far support linear correction in 5°C–45°C range as adequate
for slice 3. Deferred questions (empirical coefficient, profile reference temp
storage) may promote to an ADR-0008 amendment or a future calibration slice.
