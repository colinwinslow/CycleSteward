---
id: 0007
title: Calibration lifecycle and full-charge maintenance
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [calibration, maintenance, balancing]
---

# ADR-0007: Calibration lifecycle and full-charge maintenance

## Context

An active wall-Wh model needs a known reference point. The cleanest initial
reference is a natural display-empty or low-to-full session, but users should
not be encouraged to deliberately deep-discharge a battery just for calibration.
Periodic full charges may also be desirable for charger/BMS maintenance and for
refreshing profile capacity as the pack ages.

## Decision

**CycleSteward will support an initial low/display-empty-to-full calibration when
available, partial observations with uncertainty, and user-approved periodic
full-charge recalibration/maintenance sessions.** It must never describe display
empty as true empty and must not require deliberate deep discharge.

## Rationale

- Full low-to-full sessions provide the best denominator for active wall Wh.
- Coarse real-world observations still improve the model when stored with
  uncertainty.
- Battery capacity and charger behavior can drift over time, so recalibration is
  part of the profile lifecycle.

## Consequences

**Enables:**
- Calibration that works with a 0-5 dot display.
- A future UI for "full charge once" and "periodic full maintenance".
- Capacity aging detection by comparing full-charge observations.

**Constrains:**
- The model must distinguish calibration confidence from target precision.
- Full-charge sessions must be explicit or scheduled by user policy, not hidden
  side effects of daily mode.

**Open:**
- Recommended default interval for full-charge maintenance.
- Whether a profile should expire after a fixed age, a number of sessions, or
  observed drift.

## References

- ADR-0002: Active wall energy learned profiles
- ADR-0004: Coarse SoC input and uncertainty
