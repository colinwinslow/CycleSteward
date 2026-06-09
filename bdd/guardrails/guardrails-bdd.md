# Guardrails: Automation fault detection - BDD

## Status

Draft. Paired with [docs/specs/guardrails.md](../../docs/specs/guardrails.md).

## Why this BDD exists

This makes the automation failure behavior reviewable before real smart-plug
control is enabled.

## Scenarios

### Scenario A - maximum runtime faults a stuck session

**Given** a charging session remains active longer than the configured maximum
runtime
**When** the guardrail evaluator runs
**Then** CycleSteward commands the plug off, records a max-runtime fault, and does
not resume automatically

### Scenario B - maximum active Wh faults an impossible session

**Given** integrated active Wh exceeds the configured maximum for the profile
**When** the guardrail evaluator runs
**Then** CycleSteward commands the plug off and records a max-active-Wh fault

### Scenario C - relay chatter is prevented

**Given** recent on/off transitions already reached the configured relay-cycle
limit or minimum dwell time has not elapsed
**When** a policy would otherwise toggle the plug
**Then** CycleSteward suppresses the toggle and records the relay guardrail reason

### Scenario D - switch command failure is visible

**Given** CycleSteward commands the smart plug off
**When** the switch entity remains on after the confirmation timeout
**Then** CycleSteward records a switch-command fault and emits a notification or
event

### Scenario E - freeze lockout refuses to start charging when cold

**Given** an optional temperature sensor reports below the configured freeze
threshold (after the sensor-location offset)
**When** a charge would otherwise start
**Then** CycleSteward refuses to energize the plug and records a freeze-lockout
reason; a battery merely sitting cold is never acted on

### Scenario F - heat delays charging rather than blocking it

**Given** the temperature is above the configured heat-delay threshold
**When** a scheduled charge would otherwise begin
**Then** CycleSteward holds in a non-fault waiting state and retries as it cools,
and only skips with a notification if it has not cooled by the configured deadline

### Scenario G - missing or non-numeric readings default safely

**Given** the power or temperature reading is `unknown`/`unavailable` or
non-numeric for a sample
**When** the guardrail evaluator runs
**Then** it treats the reading as no-progress / hold using a safe default and does
not crash or misfire a cutoff

## Evidence

The implementing slice produces an evidence file at
`bdd/guardrails/guardrails-evidence.md` containing raw outputs (not summaries)
for each scenario.
