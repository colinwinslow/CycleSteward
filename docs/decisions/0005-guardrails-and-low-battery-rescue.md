---
id: 0005
title: Guardrails and low-battery rescue
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [guardrails, rescue, state-machine]
---

# ADR-0005: Guardrails and low-battery rescue

## Context

Because CycleSteward controls a smart plug, failures in Home Assistant, Zigbee,
entity selection, stale metering, or the learned model can cause undesirable
automation behavior even when the OEM charger remains safe. The user also wants
to avoid leaving a deeply discharged display-empty battery waiting for a later
scheduled charge window.

## Decision

**CycleSteward will include automation guardrails and a bounded low-battery rescue
path.** Guardrails include maximum runtime, maximum active Wh, temperature bounds,
stale-meter detection, plug command verification, no rapid relay cycling, and an
off-after-target latch. Low-battery rescue uses a bounded probe to classify the
initial charging signature and, when it resembles a learned very-low state, adds
a small bounded amount of active Wh before returning to normal scheduling.

## Rationale

- Guardrails protect against automation mistakes, not against charger/BMS
  electrical failure.
- A small rescue charge is consistent with the goal of avoiding storage at very
  low state while still preserving just-in-time charging.
- Periodic dumb pulsing should be avoided or tightly bounded to reduce relay
  wear and repeated charger inrush events.

## Consequences

**Enables:**
- Safer failure behavior for stuck-on, stale-sensor, or wrong-profile sessions.
- A probe mode that can detect a depleted battery without leaving the charger on
  indefinitely.
- User-selectable fail-normal, fail-off, and probe-oriented behavior.

**Constrains:**
- The integration must track session states explicitly.
- Charging control must verify that commands took effect or fault.
- Rescue behavior must be energy-bounded, runtime-bounded, and profile-aware.

**Open:**
- What default rescue amount should be used before a profile exists?
- What probe cadence is acceptable for common smart plugs and chargers?

## References

- ADR-0001: Smart plug wrapper
- ADR-0007: Calibration lifecycle and full-charge maintenance
