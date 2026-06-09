# Calibration: Learned charger profile - BDD

## Status

Draft. Paired with [docs/specs/profile-calibration.md](../../docs/specs/profile-calibration.md).

## Why this BDD exists

This defines how calibration data becomes a reusable charger profile without
pretending wall-power data is exact BMS SoC.

## Scenarios

### Scenario A - display-empty to full calibration stores full active Wh

**Given** a user starts calibration from a named `display_empty` anchor and lets
the OEM charger finish normally
**When** CycleSteward processes the complete session
**Then** the profile stores full active Wh, idle power, completion behavior,
curve landmarks, and a calibration quality flag

### Scenario B - zero dots is not true zero percent

**Given** a user reports `0 of 5 dots` at session start
**When** the calibration observation is stored
**Then** the report is represented as a coarse segment or `display_empty` anchor
with uncertainty, not as exact 0% SoC

### Scenario C - partial observation refines but does not overwrite

**Given** a calibrated profile already has a high-confidence full active Wh
observation
**When** the user adds a later session starting from `3 of 5 dots`
**Then** CycleSteward records a partial observation with uncertainty and does not
replace the full calibration denominator

### Scenario D - bad sample data is rejected for calibration

**Given** a session has stale meter samples or a missing taper/completion region
**When** CycleSteward attempts to use it for full calibration
**Then** the profile records a warning and does not promote that session to a
trusted full calibration

## Evidence

The implementing slice produces an evidence file at
`bdd/calibration/profile-calibration-evidence.md` containing raw outputs (not
summaries) for each scenario.
