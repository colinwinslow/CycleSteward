# Session control: Charge to target and scheduling - BDD

## Status

Draft. Paired with [docs/specs/session-control.md](../../docs/specs/session-control.md).

## Why this BDD exists

This defines the daily behavior users care about: charge only when needed and
stop at a learned target with a visible state transition.

## Scenarios

### Scenario A - cut off when wattage first crosses the target threshold

**Given** a calibrated profile with a temperature-adjusted target wattage for 80%
and "Charge to target" mode active, with the bike charging (not necessarily from
empty)
**When** measured wattage first rises across the target wattage
**Then** CycleSteward turns the smart plug off on that first crossing and enters
`DONE_LATCHED_OFF`, without a separate condition that could be false at the
crossing instant, and without resuming until policy permits a new session

### Scenario B - bike rests at target, no departure timing needed

**Given** a session has reached the target and latched off
**When** time passes before the next ride
**Then** the bike sits at the target wattage/SoC indefinitely and CycleSteward
does not re-energize the plug to "top up just in time"

### Scenario C - scheduled charging starts at the configured time

**Given** the bike is plugged in and "Charge to target" mode is on, with a
configured scheduled start time
**When** the current time is before that start time
**Then** CycleSteward keeps the plug off until the configured start time, then
begins charging

### Scenario D - modes are off by default and reset each morning

**Given** the user did not set a mode (or a mode was left on overnight)
**When** the configured morning reset time passes
**Then** both modes are off, so no charging occurs until the user opts in again
(forgetting to set a mode results in no charge)

### Scenario E - manual override still honors the cutoff

**Given** the user manually overrides the plug on while "Charge to target" is active
**When** measured wattage crosses the target wattage
**Then** CycleSteward still applies the cutoff and turns the plug off, because the
cutoff watches wattage regardless of how the plug was energized

### Scenario F - "Charge to full" stop is best-effort

**Given** "Charge to full" mode is active and the OEM charger has entered CV taper
**When** measured wattage stays below the taper floor for the configured duration
**Then** CycleSteward de-energizes the idle plug; this is best-effort cleanup and
does not claim to prevent overcharge (the BMS is the terminator)

### Scenario G - uncertain SoC estimate is surfaced

**Given** SoC is estimated from instantaneous wattage with coarse or low-confidence
calibration
**When** CycleSteward reports the estimate
**Then** it exposes an uncertainty range or low-confidence flag with the value

### Scenario H - temperature gate prevents starting

**Given** an optional temperature provider reports below the freeze threshold or
above the heat-delay threshold
**When** a scheduled charge would otherwise begin
**Then** CycleSteward does not start charging and records the temperature reason
(freeze lockout faults/holds; heat enters a delay-and-retry state per ADR-0008)

## Evidence

The implementing slice produces an evidence file at
`bdd/session-control/session-control-evidence.md` containing raw outputs (not
summaries) for each scenario.
