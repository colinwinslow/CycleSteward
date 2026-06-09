---
status: draft
date: 2026-06-08
depends-on-adrs: [0001, 0005, 0008]
---

# Guardrails: Automation fault detection

## Status

Draft. Defines the safety-adjacent automation guardrails required before real
charger control is enabled.

## Related docs

- [bdd/guardrails/guardrails-bdd.md](../../bdd/guardrails/guardrails-bdd.md) - observable behavior and scenarios

## Context

The OEM charger/BMS remains the battery safety layer, but Home Assistant control
can still fail in annoying or harmful ways: stale wattage, a stuck smart plug,
wrong entity selection, relay chatter, or a target calculation that no longer
matches reality.

## Behavior contract

CycleSteward enforces:

- maximum session runtime
- maximum active Wh per session
- **freeze lockout**: refuse to start charging below the configured freeze
  threshold (with sensor-location offset); this is a hard safety stop, not a
  delay (ADR-0008)
- **heat delay**: above the configured heat-delay threshold, hold off starting
  and retry until it cools, skipping with notification past the deadline — a
  distinct, non-fault waiting state (ADR-0008)
- stale meter timeout
- switch command confirmation
- minimum on/off durations and relay-cycle limit
- off-after-target latch
- abnormal curve shape fault
- **robustness to `unknown`/`unavailable`**: a transient missing/non-numeric
  reading must default safely (treat as no-progress / hold), never crash the
  evaluator
- notification/event emission for faults

Faulting should turn off the plug when possible, mark the session as faulted,
and require explicit policy or user action before resuming. Temperature gating
(freeze lockout, heat delay) prevents starting rather than faulting an active
session, except where a reading goes stale mid-session.

## Anchor artifact

A guardrail decision trace that shows the exact rule that faulted a session.

## Implementation order

1. Define guardrail config and event model in core.
2. Add evaluator to pure state machine.
3. Add tests with fake meter/switch adapters.
4. Wrap fault events in HA notifications/entities.

## Proof requirements

1. Unit tests for each guardrail.
2. BDD scenarios in `bdd/guardrails/guardrails-bdd.md` pass.
3. Evidence includes raw traces for fault and non-fault paths.

## Non-goals

- Certifying battery or charger safety.
- Replacing manufacturer temperature limits.
- Fire detection or smoke alarm integration.

## References

- ADR-0001
- ADR-0005
