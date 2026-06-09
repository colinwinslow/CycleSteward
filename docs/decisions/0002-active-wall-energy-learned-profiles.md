---
id: 0002
title: Active wall energy learned profiles
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [estimation, calibration, profile]
---

# ADR-0002: Active wall energy learned profiles

## Context

A fixed wattage threshold can work for one charger/battery pair, but it does not
transfer across systems. For a CC/CV-like charger, integrating the wall-power
curve over a low-to-full charge gives a repeatable profile of that system's
charging behavior. Raw wall energy includes charger overhead and losses, so it
must be treated as a proxy rather than stored battery energy.

## Decision

**CycleSteward will use per-profile active wall Wh as the primary charge-progress
metric, computed by subtracting learned idle power from measured wall power and
integrating over time.** Curve landmarks supplement this estimate for alignment,
classification, and anomaly detection.

## Rationale

- Active wall Wh is available from common metering smart plugs.
- It is more robust than one instantaneous wattage threshold.
- A per-profile model can absorb charger efficiency, standby loads, and meter
  quirks well enough for repeatable user-facing automation.
- Curve landmarks remain useful for identifying phase transitions and rejecting
  abnormal sessions.

## Consequences

**Enables:**
- Targets such as "charge to the learned 80% point" without needing BMS access.
- Calibration from a full low-to-full session and refinement from later sessions.
- A simple anchor artifact: read a fixture, subtract idle, integrate Wh, output
  a profile summary.

**Constrains:**
- Charge targets must be described as estimates.
- Changing charger, battery, or meter invalidates the learned profile.
- The estimator must preserve uncertainty when the session start is unknown or
  only coarsely reported.

**Open:**
- What default tolerance should be advertised after one calibration session?
- How should profile aging be detected as battery capacity changes?

## References

- ADR-0003: CC/CV curve feature learning
- ADR-0004: Coarse SoC input and uncertainty
- ADR-0007: Calibration lifecycle and full-charge maintenance
