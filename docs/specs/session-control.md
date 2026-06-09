---
status: draft
date: 2026-06-08
depends-on-adrs: [0001, 0002, 0003, 0005]
---

# Session control: Charge to target and just-in-time scheduling

## Status

Draft. Defines the daily charging behavior once a profile exists.

## Related docs

- [bdd/session-control/session-control-bdd.md](../../bdd/session-control/session-control-bdd.md) - observable behavior and scenarios
- [docs/specs/profile-calibration.md](profile-calibration.md)

## Context

The user wants to avoid leaving the battery at 100% while still having the bike
ready on schedule. CycleSteward should stop charging at a learned target and
support just-in-time charging windows.

## Behavior contract

Given a calibrated profile and a requested target, the controller:

- establishes or estimates the session start position
- integrates active Wh while charging
- applies guardrails continuously
- turns the plug off when the target is reached
- latches off until a new session, schedule, explicit override, or configured
  probe event
- exposes uncertainty when start position is inferred rather than reported

Targets may include:

- learned active-Wh percent of full profile
- stop before learned taper
- stop at learned taper/knee
- full charge once
- maintenance/full calibration mode

## Anchor artifact

A state-machine trace showing a session moving from `CHARGE_TO_TARGET` to
`DONE_LATCHED_OFF` when active Wh crosses the target.

## Implementation order

1. Implement pure state machine with fake switch/meter adapters.
2. Add target calculation from calibrated profile.
3. Add schedule window decisions.
4. Add HA entity/service adapters.

## Proof requirements

1. Unit tests for target calculation, latch behavior, schedule windows, and
   uncertain start estimates.
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
