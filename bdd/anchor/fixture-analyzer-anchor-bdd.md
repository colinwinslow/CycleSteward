# Anchor: Fixture analyzer profile summary - BDD

## Status

Draft. Paired with [docs/specs/fixture-analyzer-anchor.md](../../docs/specs/fixture-analyzer-anchor.md).

## Why this BDD exists

This pins down the first concrete artifact: a CSV charge-session fixture becomes
a deterministic profile-summary JSON that can be inspected on disk.

## Scenarios

### Scenario A - happy path: low-to-full fixture produces a profile summary

**Given** a CSV fixture with timestamped wall-power samples for a synthetic
low-to-full CC/CV-like charge session and a known idle power baseline
**When** the fixture analyzer runs against that CSV
**Then** it writes a JSON profile summary containing sample count, idle power,
positive active full Wh, peak power, peak timestamp, taper candidate, completion
candidate, and no fatal warnings

### Scenario B - idle subtraction prevents standby power from becoming charge energy

**Given** a fixture that begins and ends with standby/idle readings
**When** the analyzer integrates active Wh
**Then** the summary's active Wh is computed from `max(power_w - idle_w, 0)` and
standby-only rows do not add charge energy

### Scenario C - malformed fixture fails visibly

**Given** a CSV fixture missing `timestamp` or `power_w`
**When** the analyzer runs
**Then** it exits with a validation error and does not write a successful profile
summary

### Scenario D - non-monotonic or interrupted sessions carry warnings

**Given** a fixture with a long interruption or unexpected shape
**When** the analyzer runs
**Then** it still reports parseable session statistics when possible, but writes
a warning indicating the profile should not be trusted for calibration

## Evidence

The implementing slice produces an evidence file at
`bdd/anchor/fixture-analyzer-anchor-evidence.md` containing raw outputs (not
summaries) for each scenario.
