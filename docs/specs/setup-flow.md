---
status: draft
date: 2026-06-08
depends-on-adrs: [0001, 0004, 0005, 0006]
---

# Home Assistant: Setup flow and profile creation

## Status

Draft. Defines the intended setup contract after the pure core exists.

## Related docs

- [bdd/setup/setup-flow-bdd.md](../../bdd/setup/setup-flow-bdd.md) - observable behavior and scenarios
- [STATUS.md](../../STATUS.md) - current phase and active work

## Context

Users should be able to point CycleSteward at their own metered smart plug,
optional temperature provider, charger/battery description, and SoC display
format. The setup flow must make the scope and limits of the learned profile
clear.

## Behavior contract

The setup flow captures:

- charger profile name
- switch entity used to control AC power
- power sensor entity, either from the same smart plug or a separate meter
- optional temperature sensor
- SoC reporting mode: percent, N-of-M segments/dots, explicit range, named
  anchor, or unknown
- SoC report coarseness/resolution
- default fail behavior: fail-normal, fail-off, or probe mode
- guardrail defaults: max runtime, max active Wh, temperature bounds, minimum
  meter freshness, relay-cycle limits

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
