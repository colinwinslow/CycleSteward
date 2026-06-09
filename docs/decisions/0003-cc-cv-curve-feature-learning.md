---
id: 0003
title: CC/CV curve feature learning
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [cc-cv, curve-learning, generalization]
---

# ADR-0003: CC/CV curve feature learning

## Context

The Shimano reference setup shows wall power rising from a lower value on a
low battery, reaching a peak near the CC/CV transition, and then tapering down.
Other lithium-ion chargers may have different wattage levels, precharge phases,
thermal derating, fans, power-factor behavior, or fast-charge stages. The common
thread is not a fixed watt value; it is a repeatable curve shape.

## Decision

**CycleSteward will model charge sessions as learned CC/CV-like wall-power
signatures, using features such as idle level, active-start level, rising bulk
region, peak/knee candidate, taper, and completion threshold.** It must not use
hard-coded manufacturer wattage thresholds as general rules.

## Rationale

- Generalization depends on learning the shape of the user's own charger.
- The CC/CV pattern is common for lithium-ion charging, but fast chargers and
  deeply discharged packs may introduce precharge, current steps, or thermal
  limits.
- Treating unexpected shapes as uncertain or abnormal is safer than forcing them
  into a fixed model.

## Consequences

**Enables:**
- Support for Shimano and non-Shimano chargers that share a learnable curve.
- Compatibility with both slow and fast chargers when their signatures are
  stable enough.
- A future model that can classify multi-stage curves instead of assuming a
  single smooth rise and taper.

**Constrains:**
- The first implementation should use fixtures and visible artifacts before HA
  entity plumbing.
- The estimator must represent confidence and abnormal shape detection.
- Fast chargers remain a research topic until fixture coverage exists.

**Open:**
- How many calibration sessions are required before a profile is considered
  reliable?
- Which fast-charge behaviors should be accepted as compatible vs flagged as
  unsupported?

## References

- Texas Instruments, "Precise constant current regulation helps advance fast-charging": https://www.ti.com/document-viewer/lit/html/sszta38
- Battery University, "BU-409: Charging Lithium-ion": https://batteryuniversity.com/learn/article/charging_lithium_ion_batteries
- ADR-0002: Active wall energy learned profiles
