# STATUS.md

**Last updated:** 2026-06-09 (profile-calibration slice F-H implemented and verified)
**Phase:** Phase 1 - pure core
**Next bounded packet:** Profile-calibration slice I (or next slice TBD): runtime SoC estimator that uses the wattage anchors + `target_wattage()` to emit an estimated charge percentage from a live power reading; session-control state machine (start/stop/cutoff); or guardrails slice depending on priority. Review `docs/specs/` and agree the next packet before coding.
**Current readiness:** READY-FOR-NEXT-PACKET

## Recent sessions (rolling, last 5)

- **2026-06-09** - Profile-calibration slice F-H - Inrush settling (F2): `detect()` now scans forward from onset to the first stable consecutive pair so `watts_at_low` reflects the settled CC wattage, fixing the 65.7→69.7 W Swoop artifact. Relay-cutoff detection (G3): `taper_floor_w` is set to None with a `TAPER_AMBIGUOUS` warning when the apparent floor is >35% of peak active, also fixing the Swoop artifact. Opportunistic classification (F/G/G2/G3): `classify_opportunistic_session()` promotes a near-anchor completed session and stores `(temperature_c, active_wh)` in `temperature_observations` for ADR-0008 fitting; rejects on CALIBRATION_DISTRUST, TAPER_AMBIGUOUS, or proximity failure. HA-history import (H): demonstrated via real-swoop-asm-charge.csv (actual HA export) with no homeassistant import. 16 new tests (65 total), 2 new fixtures, ruff clean. BDD F/F2/G/G2/G3/H evidence written; architecture review OK; review-bdd-evidence verdict OK.
- **2026-06-09** - Profile-calibration slice A-E - Added `CalibrationProfile` model (`src/cyclesteward/calibration.py`): full-session ingest stores wattage anchors + taper floor + active Wh; `target_wattage()` linearly interpolates the 80% cutoff wattage along the CC ramp; `SocReport` stores dot-count inputs as coarse intervals (not exact %) per invariant #6; partial sessions record without overwriting the full-Wh denominator; bad-data sessions (CALIBRATION_DISTRUST) are stored but not promoted to trusted; rated-capacity → overhead ratio with `confidence: low`. 21 new tests (49 total), ruff clean. BDD A-E evidence written; review-bdd-evidence verdict OK (one prose fix applied).
- **2026-06-08** - Fixture analyzer anchor slice - Built the pure core (`src/cyclesteward/`: samples/energy/landmarks/profile/cli) turning a charge-session CSV (or exported HA history) into a deterministic profile-summary JSON with the wattage anchors + active Wh + landmarks. 28 tests pass, ruff clean. Grew the fixture library (clean/noisy/interrupted/malformed/unknown) and added a real Swoop ASM session; integrated active Wh matched the plug's energy meter to ~1%. BDD A-D evidence written; review-bdd-evidence verdict OK.
- **2026-06-08** - Calibration & rescue refinements - Added rated-capacity input + overhead estimation and opportunistic near-empty-to-full calibration (incl. temperature/full-Wh learning) to ADR-0007; added ADR-0010 for calibrating the pure core on imported Home Assistant history; made low-battery probe/rescue a toggleable, off-by-default feature (ADR-0005). Updated the calibration/rescue/setup specs + BDDs and the architecture doc.
- **2026-06-08** - Design reconciliation - Folded the prior e-bike chat design into the docs: reframed ADR-0002 to wattage-anchor SoC estimation (active Wh demoted to calibration/guardrail), required a dedicated metering plug in ADR-0001, added ADR-0008 (temperature policy) and ADR-0009 (modes/scheduling/safe defaults), updated CLAUDE.md invariant #4, expanded the calibration/session-control/guardrails/setup specs + BDDs, and added the HA-adapter-lessons research note.

## Active work

### Profile-calibration slice F-H (DONE 2026-06-09)

- [x] Opportunistic full-session detection: `classify_opportunistic_session()` accepts a near-anchor completed session (F) and stores `(temperature_c, active_wh)` in `temperature_observations`.
- [x] Inrush settling (F2): `watts_at_low` uses the first stable consecutive pair, not the onset sample.
- [x] Rejection: session starting too far from anchor → not promoted (G).
- [x] Rejection: incomplete/CALIBRATION_DISTRUST session → not promoted (G2).
- [x] Relay-cutoff disambiguation (G3): `taper_floor_w` set to None + TAPER_AMBIGUOUS warning when floor > 35% of peak.
- [x] HA-history import (H): demonstrated via real-swoop-asm-charge.csv; no homeassistant import.
- [x] Both carried real-data artifacts fixed: Swoop onset 65.7→69.7 W settled; Swoop relay cutoff detected.
- [x] BDD evidence F/F2/G/G2/G3/H written; architecture review OK; review-bdd-evidence verdict OK.

### Profile-calibration slice A-E (DONE 2026-06-09)

- [x] CalibrationProfile model with `ingest_full_session`, `ingest_partial_session`, `target_wattage`, `to_json`.
- [x] SocReport stores coarse intervals (dots, display_empty), never exact percentages.
- [x] Partial observations do not overwrite the full active-Wh denominator.
- [x] Bad-data sessions (CALIBRATION_DISTRUST) are stored but not promoted to trusted; state → CALIBRATING.
- [x] Rated capacity → overhead_ratio with `confidence: low` and uncertainty note.
- [x] BDD evidence A-E written and review-bdd-evidence verdict OK.

### Fixture analyzer anchor artifact (DONE 2026-06-08)

- [x] Define the CSV fixture input schema in code and tests.
- [x] Implement idle-subtracted active Wh integration for one low-to-full fixture (calibration aid).
- [x] Extract the wattage anchors: `watts_at_low` (CC-start), `watts_at_transition` (CC->CV peak), `taper_floor_w`.
- [x] Detect basic curve landmarks: start power band, peak/knee candidate, taper, completion threshold.
- [x] Emit a profile-summary JSON artifact (anchors + active Wh + landmarks) and read it back in evidence.
- [x] Produce BDD evidence for `bdd/anchor/fixture-analyzer-anchor-bdd.md`.

## Open queue (non-blocking)

- (a) Decide the Home Assistant domain slug (name resolved: CycleSteward; `docs/research/naming.md`).
- (b) Tune default values for the temperature thresholds/coefficient (ADR-0008) and the morning-reset/scheduled-start times (ADR-0009).
- (f) Decide the remaining Home Assistant entity/service surface after the core model is proven.
- (c) Research how often users should be prompted for full calibration/balancing charges.
- (d) Decide default probe cadence and relay-cycle limits for low-battery detection.
- (e) Grow the charge-session fixture library further (seeded: clean/noisy/interrupted/malformed/unknown synthetics + one real Swoop ASM session; want more real sessions at varied temperatures and a full taper-to-completion session).

## Blockers

- None for the first anchor slice. Later Home Assistant integration slices need decisions on entity naming, setup-flow UX, and persistent storage schema.
