---
status: draft
date: 2026-06-08
depends-on-adrs: [0002, 0003, 0004, 0007]
---

# Calibration: Learned charger profile

## Status

Draft. Defines how CycleSteward learns and updates a charger/battery/meter
profile.

## Related docs

- [bdd/calibration/profile-calibration-bdd.md](../../bdd/calibration/profile-calibration-bdd.md) - observable behavior and scenarios
- [docs/specs/fixture-analyzer-anchor.md](fixture-analyzer-anchor.md) - first anchor artifact

## Context

The integration needs a denominator and curve signature for estimating later
charge sessions. A natural low/display-empty-to-full session is the best initial
observation, but partial observations with coarse user-reported SoC should also
be stored.

## Behavior contract

A calibration profile stores:

- profile identity: charger label, battery label, meter entity identity
- idle power baseline and confidence
- full active Wh observations with timestamps and quality flags
- curve landmarks and confidence
- SoC input reports with coarseness metadata
- profile state: uncalibrated, calibrating, calibrated, stale, faulted
- unresolved warnings such as missing samples or abnormal taper

Profile updates never overwrite a high-confidence full calibration with a lower-
confidence partial observation. Partial observations refine ranges.

## Anchor artifact

A profile JSON showing one full calibration observation plus one coarse SoC
observation.

## Implementation order

1. Build on the fixture analyzer profile summary.
2. Add profile persistence model.
3. Add calibration quality scoring.
4. Add partial observation ingestion.
5. Add profile stale/drift flags.

## Proof requirements

1. Unit tests for full calibration, partial observations, coarse SoC reports,
   and rejected bad data.
2. BDD scenarios in `bdd/calibration/profile-calibration-bdd.md` pass.
3. Evidence includes profile JSON before and after observation ingestion.

## Non-goals

- Guaranteeing absolute BMS SoC.
- Forcing users to deep-discharge before calibration.
- Supporting non-lithium charging profiles in the first version.

## References

- ADR-0002
- ADR-0003
- ADR-0004
- ADR-0007
