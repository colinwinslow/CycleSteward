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

The user can also supply the battery's **rated capacity (Wh)** at setup. Comparing
the measured wall active Wh of a full session to that rated capacity estimates the
combined charger/battery overhead (efficiency plus the unused low-end reserve), so
the model knows how many measured wall Wh correspond to a full charge. Because
naturally-occurring sessions that start near empty and run to 100% are full-span
sessions, CycleSteward can detect them automatically and reuse them as calibration
datapoints without asking the user to do anything — and, across several such
sessions at different temperatures, learn how temperature changes the measured Wh
of a full charge.

## Decision

**CycleSteward will support an initial low/display-empty-to-full calibration when
available, partial observations with uncertainty, and user-approved periodic
full-charge recalibration/maintenance sessions.** At setup the user may supply the
battery's rated capacity (Wh); CycleSteward compares it against measured full-
session active Wh to estimate charger/battery overhead. CycleSteward will also
**automatically detect naturally-occurring near-empty-to-full sessions and use
them as opportunistic calibration datapoints**, including learning the
relationship between temperature and the measured Wh of a full charge (feeding the
temperature model in ADR-0008). It must never describe display empty as true empty
and must not require deliberate deep discharge.

## Rationale

- Full low-to-full sessions provide the best denominator for active wall Wh.
- Coarse real-world observations still improve the model when stored with
  uncertainty.
- Battery capacity and charger behavior can drift over time, so recalibration is
  part of the profile lifecycle.
- A user-supplied rated capacity turns measured full-session Wh into an overhead
  estimate, which sanity-checks calibration and bounds expected full-charge Wh.
- Reusing naturally-occurring full sessions means the temperature/full-Wh
  relationship improves passively, without extra user effort.

## Consequences

**Enables:**
- Calibration that works with a 0-5 dot display.
- A future UI for "full charge once" and "periodic full maintenance".
- Capacity aging detection by comparing full-charge observations.
- Overhead/efficiency estimation from rated capacity vs. measured full Wh.
- Passive recalibration and temperature learning from auto-detected full sessions.

**Constrains:**
- The model must distinguish calibration confidence from target precision.
- Full-charge sessions must be explicit or scheduled by user policy, not hidden
  side effects of daily mode.
- Rated capacity is a user-supplied nominal value, not a measurement; the model
  must treat the derived overhead as an estimate with uncertainty.
- Opportunistic full-session detection must be conservative: a session must
  clearly start near the learned low anchor and reach completion before it is
  trusted as a full-span datapoint.

**Open:**
- Recommended default interval for full-charge maintenance.
- Whether a profile should expire after a fixed age, a number of sessions, or
  observed drift.

## References

- ADR-0002: Wattage-anchor SoC estimation with active-Wh calibration
- ADR-0004: Coarse SoC input and uncertainty
- ADR-0008: Temperature-aware charging and storage policy
- ADR-0010: Calibrating the pure core on Home Assistant history
