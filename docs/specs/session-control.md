---
status: draft
date: 2026-06-08
depends-on-adrs: [0001, 0002, 0003, 0005, 0008, 0009]
---

# Session control: Charge to target and scheduling

## Status

Draft. Defines the daily charging behavior once a profile exists.

## Related docs

- [bdd/session-control/session-control-bdd.md](../../bdd/session-control/session-control-bdd.md) - observable behavior and scenarios
- [docs/specs/profile-calibration.md](profile-calibration.md)

## Context

The user wants to avoid leaving the battery at high SoC while keeping the bike
usable. Because the cutoff is a wattage threshold (ADR-0002), the bike can rest
at the target indefinitely once it is reached, so charging does not need to be
timed to finish at departure. Scheduling exists to pick *when* charging starts
(e.g. overnight), not to land the finish on a deadline.

## Behavior contract

The controller runs two mutually-exclusive modes (ADR-0009): "Charge to target"
(daily) and "Charge to full" (pre-ride), both off by default and auto-reset at a
configurable morning time. Given an active mode and a calibrated profile, the
controller:

- estimates SoC from instantaneous CC-phase wattage (no need to know the start
  position), exposing uncertainty/low-confidence when appropriate
- **cuts off when wattage first crosses the target threshold** (the
  temperature-adjusted target wattage), not by integrating from a known start.
  The cutoff fires on the first crossing; it must not be double-gated by a
  separate condition that can be false at the crossing instant
- applies guardrails continuously (ADR-0005), including temperature gating
  (ADR-0008)
- latches off after the target until a new session, schedule, override, or probe
- starts scheduled charging at a configurable time
- honors a manual override that toggles the plug directly, **but still applies
  the active mode's wattage cutoff**, because the cutoff watches wattage
  regardless of how the plug was energized

Target/mode behavior:

- "Charge to target": stop at the temperature-adjusted target wattage (default
  ~80%), then rest
- "Charge to full": let the OEM charger run into CV; stop is best-effort, when
  wattage stays below the taper floor for a configured time. The BMS is the real
  terminator; this only de-energizes the idle plug, it does not prevent overcharge
- maintenance/full calibration mode (per ADR-0007)

## Anchor artifact

A state-machine trace showing a session moving from `CHARGE_TO_TARGET` to
`DONE_LATCHED_OFF` when measured wattage first crosses the temperature-adjusted
target wattage.

## Implementation order

1. Implement pure state machine with fake switch/meter adapters.
2. Add target-wattage calculation from the calibrated profile (temperature-adjusted).
3. Add mode handling (mutually exclusive, off-by-default, morning reset) and the
   configurable schedule.
4. Add manual override that still applies the cutoff.
5. Add HA entity/service adapters.

## Proof requirements

1. Unit tests for target-wattage calculation, first-crossing cutoff, latch
   behavior, mode reset/exclusivity, manual-override-honors-cutoff, schedule
   start, and uncertain SoC estimates.
2. BDD scenarios in `bdd/session-control/session-control-bdd.md` pass.
3. Evidence includes a trace artifact with exact samples and state transitions.

## Non-goals

- Optimization across electricity price or solar production.
- Directly reading Shimano/Bosch/Yamaha battery SoC.
- Deciding long-term battery-care policy without user settings.

## References

- ADR-0001
- ADR-0002
- ADR-0003
- ADR-0005
