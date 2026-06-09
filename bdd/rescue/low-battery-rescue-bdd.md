# Rescue: Low-battery probe and bounded rescue charge - BDD

## Status

Draft. Paired with [docs/specs/low-battery-rescue.md](../../docs/specs/low-battery-rescue.md).

## Why this BDD exists

This ensures a display-empty bike does not sit low just because the normal charge
window is later, while preventing uncontrolled periodic pulsing or full charging.

## Scenarios

### Scenario A0 - feature disabled means no probing

**Given** the low-battery probe/rescue feature is off (the default)
**When** the bike is plugged in and a probe might otherwise run
**Then** CycleSteward never energizes the plug to probe and the rescue controller
stays inert; the plug is only energized by explicit modes or schedule

### Scenario A - probe detects very-low signature and performs bounded rescue

**Given** a calibrated profile has a learned very-low initial power band and the
plug is in probe mode
**When** the probe window observes stable active charging power in that band
**Then** CycleSteward enters `RESCUE_CHARGE`, adds no more than the configured
rescue active Wh or runtime, and then returns to `WAIT_FOR_SCHEDULE`

### Scenario B - probe sees normal charge signature and waits for schedule

**Given** the bike is connected but the initial power does not resemble the
learned very-low band
**When** the probe completes
**Then** CycleSteward turns the plug off and enters `WAIT_FOR_SCHEDULE`

### Scenario C - probe sees no bike or standby only

**Given** the plug turns on and power remains at or below idle
**When** the probe window ends
**Then** CycleSteward turns the plug off and returns to `OFF_IDLE`

### Scenario D - stale meter data during probe faults the session

**Given** the plug is on during a probe
**When** the power sensor stops updating past the freshness threshold
**Then** CycleSteward turns the plug off when possible and enters `FAULT`

## Evidence

The implementing slice produces an evidence file at
`bdd/rescue/low-battery-rescue-evidence.md` containing raw outputs (not
summaries) for each scenario.
