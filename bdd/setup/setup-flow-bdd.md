# Home Assistant: Setup flow and profile creation - BDD

## Status

Draft. Paired with [docs/specs/setup-flow.md](../../docs/specs/setup-flow.md).

## Why this BDD exists

This pins down the user-visible setup behavior for selecting a metered plug,
optional temperature provider, and SoC reporting coarseness.

## Scenarios

### Scenario A - user creates a profile for a metered smart plug

**Given** Home Assistant has a controllable switch entity and a wattage sensor
entity for a smart plug
**When** the user configures CycleSteward with those entities and a profile name
**Then** CycleSteward stores a new uncalibrated profile scoped to that switch,
power sensor, charger label, and battery label

### Scenario B - user records a 0-5 dot SoC display

**Given** the user's bike reports charge as 0-5 dots instead of a percentage
**When** the user selects `segments` with 5 maximum segments
**Then** CycleSteward stores SoC reports as coarse intervals or named anchors,
not exact percentages

### Scenario C - optional temperature provider is configured

**Given** a temperature sensor is available
**When** the user selects it during setup
**Then** CycleSteward stores it as a guardrail input without requiring it for core
profile learning

### Scenario D - invalid entity selection blocks setup

**Given** the selected switch cannot be controlled or the selected power sensor
has no numeric wattage state
**When** the user attempts to finish setup
**Then** CycleSteward refuses to create an active profile and explains the missing
capability

## Evidence

The implementing slice produces an evidence file at
`bdd/setup/setup-flow-evidence.md` containing raw outputs (not summaries) for
each scenario.
