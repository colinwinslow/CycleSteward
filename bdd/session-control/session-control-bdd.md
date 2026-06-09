# Session control: Charge to target and just-in-time scheduling - BDD

## Status

Draft. Paired with [docs/specs/session-control.md](../../docs/specs/session-control.md).

## Why this BDD exists

This defines the daily behavior users care about: charge only when needed and
stop at a learned target with a visible state transition.

## Scenarios

### Scenario A - charge to learned active-Wh target and latch off

**Given** a calibrated profile with full active Wh and a daily target of 80% of
the learned profile
**When** a session starts from a known or estimated start position and integrated
active Wh reaches the target
**Then** CycleSteward turns the smart plug off and enters `DONE_LATCHED_OFF`
without resuming until policy permits a new session

### Scenario B - just-in-time schedule waits when battery is not low

**Given** the bike is plugged in before the configured charge window and the
initial probe does not look very low
**When** CycleSteward evaluates the schedule
**Then** it turns or keeps the plug off until the just-in-time charging window
opens

### Scenario C - uncertain start position is surfaced

**Given** the session start is inferred from initial wattage rather than an exact
user SoC report
**When** CycleSteward estimates the target stop point
**Then** it exposes an uncertainty range or low-confidence flag with the estimate

### Scenario D - temperature gate delays charging

**Given** an optional temperature provider reports a value outside the configured
charging range
**When** a scheduled charge would otherwise begin
**Then** CycleSteward does not start charging and records the temperature guardrail
as the reason

## Evidence

The implementing slice produces an evidence file at
`bdd/session-control/session-control-evidence.md` containing raw outputs (not
summaries) for each scenario.
