---
id: 0001
title: Smart plug wrapper
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [architecture, home-assistant, safety-boundary]
---

# ADR-0001: Smart plug wrapper

## Context

The motivating system is a normal e-bike charger plugged into a metered Zigbee
smart plug. The user wants just-in-time charging and partial-charge cutoff, but
does not want to modify the bike, charger, or battery. The integration must be
generalizable beyond Shimano while respecting each manufacturer's charger and
BMS.

## Decision

**CycleSteward will be a charger wrapper that controls AC power to a user-selected
metered plug and observes power/temperature sensors; it will not replace,
emulate, or bypass the OEM charger/BMS.** The metered plug must be a **dedicated
plug that powers only the charger**, so all wall power is attributable to the
charger and shared-circuit baseline subtraction is unnecessary and unsupported.

## Rationale

- The OEM charger/BMS is the correct layer for overvoltage, overcurrent,
  termination, and battery thermal protection.
- A metered smart plug gives enough information to learn a repeatable wall-side
  charging signature without reverse-engineering manufacturer protocols.
- Keeping the integration at the AC-control boundary makes it broadly applicable
  to many charger/battery systems.
- Requiring a dedicated plug keeps the wattage signal clean: wall power equals
  charger power, so the wattage-anchor SoC model (ADR-0002) needs no fragile
  estimation of an unrelated shared-circuit baseline.

## Consequences

**Enables:**
- Support for many chargers that expose a repeatable wall-power curve.
- A safer and simpler initial implementation than direct battery protocol access.
- User-selectable fail behavior such as fail-normal, fail-off, or probe mode.

**Constrains:**
- Charge state is an estimate, not BMS truth.
- The integration cannot know cell balance, true pack voltage, or real pack SoC
  unless a future data source provides those directly.
- The integration must handle smart-plug and sensor failures conservatively.
- A dedicated metering smart plug per charger is required; shared-circuit
  metering with baseline subtraction is out of scope.

**Open:**
- Which fail behavior should be the default for new users?
- Should the integration block unsupported plugs with poor metering update rates?

## References

- ADR-0002: Active wall energy learned profiles
- ADR-0005: Guardrails and low-battery rescue
