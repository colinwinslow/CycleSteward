---
status: draft
date: 2026-06-08
depends-on-adrs: [0001, 0002, 0004, 0005, 0006, 0007, 0008, 0009, 0010]
---

# Home Assistant: Setup flow and profile creation

## Status

Draft. Defines the intended setup contract after the pure core exists.

## Related docs

- [bdd/setup/setup-flow-bdd.md](../../bdd/setup/setup-flow-bdd.md) - observable behavior and scenarios
- [STATUS.md](../../STATUS.md) - current phase and active work

## Context

Users should be able to point CycleSteward at their own dedicated metering smart
plug, optional temperature provider, charger/battery description, and SoC display
format. The setup flow must make the scope and limits of the learned profile
clear. A **dedicated metering smart plug is required** (ADR-0001): the switch and
power sensor come from the same plug, which powers only the charger, so there is
no shared-circuit baseline to subtract.

## Behavior contract

The setup flow captures:

- charger profile name
- the dedicated metering smart plug: its switch entity (AC control) and its power
  sensor entity (W) — both from the same plug
- rated battery capacity (Wh), used to estimate charger/battery overhead during
  calibration (ADR-0007)
- optional temperature sensor, plus its configurable sensor-location offset,
  compensation coefficient, baseline, freeze threshold, heat-delay threshold and
  deadline, and heat-storage threshold/duration (ADR-0008); all temperature
  behavior is disabled when no sensor is selected
- SoC reporting mode: percent, N-of-M segments/dots, explicit range, named
  anchor, or unknown
- SoC report coarseness/resolution
- charge mode defaults and target percent, configurable scheduled start time, and
  configurable morning reset time (ADR-0009)
- enable low-battery probe/rescue (default off), and if enabled its bounds (ADR-0005)
- default fail behavior on sensor/plug failure: fail-normal or fail-off
- guardrail defaults: max runtime, max active Wh, minimum meter freshness,
  relay-cycle limits

Calibration can run on a guided session or on Home Assistant history imported into
the core's plain sample format (ADR-0010); the import is a calibration action, not
a setup field.

The flow creates a disabled/untrusted profile until calibration evidence exists.

## Anchor artifact

A setup-flow debug dump or test fixture showing a stored profile configuration
with a 0-5 dot SoC reporting mode and optional temperature provider.

## Implementation order

1. Define pure configuration dataclasses in the core.
2. Add Home Assistant config-flow adapter around those dataclasses.
3. Validate entity capabilities and report missing power/switch capabilities.
4. Persist the profile configuration.

## Proof requirements

1. Unit tests for config validation.
2. BDD scenarios in `bdd/setup/setup-flow-bdd.md` pass.
3. Evidence includes the stored configuration read back from disk or HA storage
   test harness.

## Non-goals

- Calibration math.
- Charging control.
- Manufacturer-specific battery protocol integrations.

## References

- ADR-0001
- ADR-0004
- ADR-0005
- ADR-0006
- ADR-0007
- ADR-0008
- ADR-0009
- ADR-0010
