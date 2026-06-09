---
id: 0002
title: Wattage-anchor SoC estimation with active-Wh calibration
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [estimation, calibration, profile]
---

# ADR-0002: Wattage-anchor SoC estimation with active-Wh calibration

## Context

For a CC/CV-like charger, the charger holds current roughly constant during the
constant-current (CC) bulk phase while pack voltage rises with state of charge.
Because `P = V x I` with `I` approximately fixed, **instantaneous wall wattage
rises roughly linearly with SoC during CC**, and a given wattage maps to a given
SoC regardless of where the charge started. When the pack reaches its voltage
ceiling the charger switches to constant-voltage (CV) taper and wattage falls
rapidly toward idle.

Two consequences shaped this decision:

- The bike is not always plugged in from empty. A metric integrated from an
  unknown starting point (such as cumulative active Wh) cannot by itself report
  absolute SoC, because the CC rise encodes elapsed time, not starting SoC.
- Instantaneous CC wattage *can* report absolute SoC, which makes a wattage
  threshold a viable cutoff without any battery-side SoC sensor.

## Decision

**CycleSteward will estimate SoC and trigger cutoff from instantaneous CC-phase
wall wattage, mapped to SoC by linear interpolation between two learned anchors:
a low anchor (`WATTS_AT_LOW` / `SOC_AT_LOW`, the CC-start wattage at a known low
display state) and a transition anchor (`WATTS_AT_TRANSITION` /
`SOC_AT_TRANSITION`, the wattage at the CC->CV peak).** Integrated active wall Wh
is retained as a calibration aid — used to locate where a target such as 80%
falls in wattage terms — and as a max-energy guardrail, not as the runtime SoC
metric.

The estimate is:

```text
SoC = SOC_AT_LOW
    + (watts - WATTS_AT_LOW) / (WATTS_AT_TRANSITION - WATTS_AT_LOW)
      * (SOC_AT_TRANSITION - SOC_AT_LOW)
```

clamped to 0-100. At or above the transition wattage the CC model no longer
applies and SoC is reported as approximately the transition anchor (~95%). When
not charging, the last estimated value is exposed as the resting estimate; there
is no separate stored-energy SoC.

## Rationale

- Absolute wattage gives current SoC from any starting point; integrated Wh does
  not.
- A two-anchor linear model is simple, inspectable, and per-profile, so it
  absorbs charger-specific wattage levels without hard-coded thresholds.
- Active Wh is still the cleanest way to measure a full low-to-full session and
  thereby calibrate the wattage that corresponds to a target percentage.
- Wattage at the CC->CV peak is, by construction, the practical full-bulk point;
  treating it as a ~95% anchor is a definitional assumption, not a measurement.

## Consequences

**Enables:**
- A wattage-threshold cutoff that lets the bike rest at the target indefinitely,
  which removes most of the need to time charging to departure.
- SoC estimates that work even when the session did not start from empty.
- Calibration from a full session that locates the target wattage.

**Constrains:**
- SoC and target are estimates and must be labeled as such.
- The model assumes a dedicated metering plug with negligible shared baseline
  (see ADR-0001); only the charger's own idle/standby is subtracted.
- The anchor SoC values (`SOC_AT_LOW`, `SOC_AT_TRANSITION`) are assumptions with
  uncertainty, not BMS truth.
- Changing charger, battery, or meter invalidates the learned anchors.
- Wattage readings need temperature compensation to stay accurate (see ADR-0008).

**Open:**
- Default `SOC_AT_LOW` / `SOC_AT_TRANSITION` assumptions and their advertised
  uncertainty.
- How to detect anchor drift as battery capacity ages.

## References

- ADR-0001: Smart plug wrapper
- ADR-0003: CC/CV curve feature learning
- ADR-0004: Coarse SoC input and uncertainty
- ADR-0007: Calibration lifecycle and full-charge maintenance
- ADR-0008: Temperature-aware charging and storage policy
