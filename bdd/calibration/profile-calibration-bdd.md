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

**Given** a calibrated profile with a known `watts_at_low` anchor and a later
completed session whose starting wattage falls within a conservative proximity
tolerance of that anchor (e.g. within 10% of `watts_at_low`), and a temperature
reading is available for the session
**When** CycleSteward classifies the completed session
**Then** it promotes the session to an opportunistic full-span datapoint; stores
the `(temperature_c, active_wh)` pair alongside the existing calibration data for
later temperature/full-Wh compensation fitting; and does not prompt the user

### Scenario F2 - inrush settling yields a representative watts_at_low

**Given** a charge session whose first samples show a brief inrush spike — wattage
momentarily above the steady CC phase — before settling to a stable bulk-charge
wattage
**When** CycleSteward extracts `watts_at_low`
**Then** it uses the settled CC wattage (after the inrush period, not the spike),
so the anchor reflects the wattage the charger sustains at the known SoC anchor
point rather than an artefact of startup transient

### Scenario G - a session that starts too far from the low anchor is rejected

**Given** a calibrated profile and a later completed session whose starting
wattage is substantially above the learned `watts_at_low` anchor (i.e. it clearly
did not start near display-empty)
**When** CycleSteward classifies it
**Then** it is not promoted to a full-span datapoint, the `active_full_wh`
denominator is unchanged, and the profile records why it was skipped

### Scenario G2 - an incomplete session is not promoted even if it starts near the anchor

**Given** a calibrated profile and a later session that starts near `watts_at_low`
but ends before reaching the taper/completion region (interrupted, or relay cut
off mid-CC)
**When** CycleSteward classifies it
**Then** it is not promoted to a full-span datapoint; the profile records the
rejection reason (no completion detected)

### Scenario G3 - a sharp mid-taper relay cutoff is not mistaken for a natural taper floor

**Given** a session whose power drops sharply to zero while still mid-taper (a
relay cutoff artefact rather than a natural CV settling to near-idle)
**When** CycleSteward analyses the completion region
**Then** `taper_floor_w` is not assigned from the cutoff artefact; the profile
records a warning that completion is ambiguous; and the session is not promoted as
a trusted full-span datapoint

### Scenario H - calibration runs on imported Home Assistant history

**Given** Home Assistant power (and optional temperature) history exported into
the plain sample format (same row shape as synthetic fixtures: timestamp,
power_w, and optionally temperature_c), with gaps and `unknown`/`unavailable`
rows tolerated
**When** the pure core ingests those rows for calibration
**Then** it produces the same kind of profile output as a synthetic fixture —
wattage anchors, taper floor, active Wh, and any quality flags — without
importing Home Assistant

## Evidence

The implementing slice appends a new section to
`bdd/calibration/profile-calibration-evidence.md` covering scenarios F, F2, G,
G2, G3, and H with raw outputs (not summaries) for each scenario.
