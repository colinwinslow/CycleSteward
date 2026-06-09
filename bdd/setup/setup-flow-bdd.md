# Home Assistant: Setup flow and profile creation - BDD

## Status

Draft. Paired with [docs/specs/setup-flow.md](../../docs/specs/setup-flow.md).

## Why this BDD exists

This pins down the user-visible setup behavior for selecting a metered plug,
optional temperature provider, and SoC reporting coarseness.

## Scenarios

### Scenario A - user creates a profile for a dedicated metering smart plug

**Given** Home Assistant has a controllable switch entity and a wattage sensor
entity that belong to the same dedicated smart plug powering only the charger
**When** the user configures CycleSteward with those entities and a profile name
**Then** CycleSteward stores a new uncalibrated profile scoped to that switch,
power sensor, charger label, and battery label, with no shared-circuit baseline
option offered

### Scenario B - user records a 0-5 dot SoC display

**Given** the user's bike reports charge as 0-5 dots instead of a percentage
**When** the user selects `segments` with 5 maximum segments
**Then** CycleSteward stores SoC reports as coarse intervals or named anchors,
not exact percentages

### Scenario C - optional temperature provider is configured

**Given** a temperature sensor is available
**When** the user selects it during setup and sets the sensor-location offset,
compensation coefficient/baseline, and freeze/heat thresholds
**Then** CycleSteward stores it as a guardrail and compensation input without
requiring it for core profile learning

### Scenario C2 - no temperature provider disables temperature behavior

**Given** the user configures a profile without selecting a temperature sensor
**When** setup completes
**Then** CycleSteward records that temperature compensation and gating are disabled,
and charging proceeds uncompensated and ungated

### Scenario C3 - rated battery capacity is captured for overhead estimation

**Given** the user knows the battery's rated capacity in Wh
**When** they enter it during setup
**Then** CycleSteward stores the rated capacity so a later full session can derive
the charger/battery overhead estimate

### Scenario C4 - low-battery probe/rescue is off by default

**Given** the user completes setup without enabling low-battery probe/rescue
**When** the profile is stored
**Then** the probe/rescue feature is disabled, so CycleSteward will not energize
the plug to probe until the user opts in

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
