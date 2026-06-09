# STATUS.md

**Last updated:** 2026-06-08 (fixture analyzer anchor artifact implemented and verified)
**Phase:** Phase 1 - pure core (anchor artifact landed)
**Next bounded packet:** Profile-calibration slice (`docs/specs/profile-calibration.md`): persist a charger profile from a full session; locate the target wattage (e.g. 80%) along the CC ramp from the wattage anchors + active-Wh integral; capture user-supplied rated capacity -> overhead estimate (ADR-0007); and harden onset detection so `watts_at_low` settles past the inrush ramp (real-data finding). Proof: unit tests, `bdd/calibration/profile-calibration-bdd.md` evidence, profile JSON read back.
**Current readiness:** READY-FOR-NEXT-PACKET

## Recent sessions (rolling, last 5)

- **2026-06-08** - Fixture analyzer anchor slice - Built the pure core (`src/cyclesteward/`: samples/energy/landmarks/profile/cli) turning a charge-session CSV (or exported HA history) into a deterministic profile-summary JSON with the wattage anchors + active Wh + landmarks. 28 tests pass, ruff clean. Grew the fixture library (clean/noisy/interrupted/malformed/unknown) and added a real Swoop ASM session; integrated active Wh matched the plug's energy meter to ~1%. BDD A-D evidence written; review-bdd-evidence verdict OK.
- **2026-06-08** - Calibration & rescue refinements - Added rated-capacity input + overhead estimation and opportunistic near-empty-to-full calibration (incl. temperature/full-Wh learning) to ADR-0007; added ADR-0010 for calibrating the pure core on imported Home Assistant history; made low-battery probe/rescue a toggleable, off-by-default feature (ADR-0005). Updated the calibration/rescue/setup specs + BDDs and the architecture doc.
- **2026-06-08** - Design reconciliation - Folded the prior e-bike chat design into the docs: reframed ADR-0002 to wattage-anchor SoC estimation (active Wh demoted to calibration/guardrail), required a dedicated metering plug in ADR-0001, added ADR-0008 (temperature policy) and ADR-0009 (modes/scheduling/safe defaults), updated CLAUDE.md invariant #4, expanded the calibration/session-control/guardrails/setup specs + BDDs, and added the HA-adapter-lessons research note.
- **2026-06-08** - Workflow port + rename - Ported the agentic workflow from Codex back to native Claude Code (.claude/ commands, agents, SessionStart hook) and renamed ChargeShape to CycleSteward across the repo.

## Active work

### Fixture analyzer anchor artifact (DONE 2026-06-08)

- [x] Define the CSV fixture input schema in code and tests.
- [x] Implement idle-subtracted active Wh integration for one low-to-full fixture (calibration aid).
- [x] Extract the wattage anchors: `watts_at_low` (CC-start), `watts_at_transition` (CC->CV peak), `taper_floor_w`.
- [x] Detect basic curve landmarks: start power band, peak/knee candidate, taper, completion threshold.
- [x] Emit a profile-summary JSON artifact (anchors + active Wh + landmarks) and read it back in evidence.
- [x] Produce BDD evidence for `bdd/anchor/fixture-analyzer-anchor-bdd.md`.

### Carried into the next slice (real-data findings)

- [ ] Onset robustness: settle `watts_at_low` past the inrush ramp (real fixture read 65.7 W vs settled ~69.7 W).
- [ ] Distinguish a true CV taper floor from a mid-taper relay cutoff (`taper_floor_w` / completion can be a cutoff artifact).

## Open queue (non-blocking)

- (a) Decide the Home Assistant domain slug (name resolved: CycleSteward; `docs/research/naming.md`).
- (b) Tune default values for the temperature thresholds/coefficient (ADR-0008) and the morning-reset/scheduled-start times (ADR-0009).
- (f) Decide the remaining Home Assistant entity/service surface after the core model is proven.
- (c) Research how often users should be prompted for full calibration/balancing charges.
- (d) Decide default probe cadence and relay-cycle limits for low-battery detection.
- (e) Grow the charge-session fixture library further (seeded: clean/noisy/interrupted/malformed/unknown synthetics + one real Swoop ASM session; want more real sessions at varied temperatures and a full taper-to-completion session).

## Blockers

- None for the first anchor slice. Later Home Assistant integration slices need decisions on entity naming, setup-flow UX, and persistent storage schema.
