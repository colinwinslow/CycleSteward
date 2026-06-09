---
title: Unresolved design questions
status: open
date: 2026-06-08
---

# Research: Unresolved design questions

## Question

Which decisions from the initial design conversation still need human or agent
follow-up?

## Context

The seed ADRs intentionally lock the basic architecture, but several product and
algorithm details should remain open until fixtures and implementation evidence
exist.

Note: some items below are now decided and only their *default values* remain
open. The estimation method is settled (ADR-0002, wattage anchors); temperature
policy is settled (ADR-0008); charge modes, scheduling, and safe defaults are
settled (ADR-0009). Where a bullet below is covered by one of those, treat it as
"tune the defaults," not "decide the approach."

## Notes

### Calibration and estimation

- How close is active wall-Wh percent to the user's intended SoC target across
  real e-bike chargers?
- How many full calibration sessions should be required before the integration
  advertises a profile as calibrated?
- How often should users be nudged to run a full charge for recalibration or BMS
  maintenance?
- Should calibration quality degrade based on time, cycle count, battery age, or
  observed drift?

### Coarse SoC reports

- For N-of-M dot displays, should the default segment intervals be equal width
  or learned from later observations?
- What should the UI call zero dots when assist stops but lights/shifting still
  work: `display_empty`, `assist_cutoff_empty`, or something user-editable?
- Should users be allowed to enter a display range such as "between 1 and 2
  dots"?

### Low-battery rescue and probing

- Should the default mode be fail-normal, fail-off, or probe mode?
- How often may probe mode briefly turn on the plug without causing unacceptable
  relay wear or repeated charger inrush?
- Before calibration exists, should low-battery rescue be disabled, time-based,
  or use a conservative default active-Wh cap?

### Home Assistant product decisions

- Which entities should be exposed first: sensor estimated charge, sensor
  confidence, switch automation enabled, button charge full once, select target
  mode, number target percent?
- Should the integration require a combined switch+power smart plug, or allow
  separate switch and power sensor entities?
- How should profile data be stored and migrated across versions?
- Should the integration emit persistent notifications, repairs issues, logbook
  entries, events, or all of them for faults?

### Compatibility

- Which non-CC/CV or multi-stage charger shapes should be explicitly unsupported?
- Do fast chargers need stricter temperature or calibration requirements?
- How should chargers with fan loads or strong standby/trickle behavior be
  modeled?

## Open sub-questions

All notes above remain open until promoted to ADRs/specs.

## Resolution

Open.
