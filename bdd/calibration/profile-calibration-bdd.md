# Calibration: Learned charger profile - BDD

## Status

Draft. Paired with [docs/specs/profile-calibration.md](../../docs/specs/profile-calibration.md).

## Why this BDD exists

This defines how calibration data becomes a reusable charger profile without
pretending wall-power data is exact BMS SoC.

## Scenarios

### Scenario A - display-empty to full calibration stores the wattage anchors

**Given** a user starts calibration from a named `display_empty` anchor and lets
the OEM charger finish normally
**When** CycleSteward processes the complete session
**Then** the profile stores `WATTS_AT_LOW` (CC-start wattage), `WATTS_AT_TRANSITION`
(CC->CV peak), the taper floor, idle power, full active Wh, curve landmarks, and a
calibration quality flag

### Scenario A2 - active Wh locates the target wattage

**Given** a full calibration session with the two wattage anchors and the active
Wh integral across the session
**When** CycleSteward derives the 80% target
**Then** it records the wattage along the CC ramp that corresponds to 80%, so the
runtime cutoff can be a wattage threshold rather than an integrated-Wh target

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

### Scenario E - rated capacity yields an overhead estimate

**Given** the user supplied a rated battery capacity and a full session produced a
measured active Wh
**When** CycleSteward processes the full session
**Then** it stores `overhead_ratio = measured_active_full_wh / rated_capacity_wh`
as an estimate with uncertainty, not as exact truth

### Scenario F - a naturally-occurring near-empty-to-full session is reused

**Given** a calibrated profile and a later session that starts near the learned low
anchor and runs to completion, with a temperature reading
**When** CycleSteward classifies the completed session
**Then** it promotes the session to an opportunistic full-span datapoint and
updates the temperature/full-Wh relationship, without prompting the user

### Scenario G - a partial session is not mistaken for a full-span datapoint

**Given** a later session that does not clearly start near the low anchor or does
not reach completion
**When** CycleSteward classifies it
**Then** it is not promoted to a full-span datapoint and the full calibration is
unchanged

### Scenario H - calibration runs on imported Home Assistant history

**Given** Home Assistant power (and optional temperature) history exported into the
plain sample format
**When** the pure core ingests those rows for calibration
**Then** it produces the same kind of profile output as a synthetic fixture,
without importing Home Assistant

## Evidence

The implementing slice produces an evidence file at
`bdd/calibration/profile-calibration-evidence.md` containing raw outputs (not
summaries) for each scenario.
