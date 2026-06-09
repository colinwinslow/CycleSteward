# STATUS.md

**Last updated:** 2026-06-08 (design reconciled with the source e-bike chat summary)
**Phase:** Phase 0 - design seed and anchor planning
**Next bounded packet:** Implement the fixture analyzer anchor artifact: read one CSV charge-session fixture (or exported HA history), subtract the charger's idle watts, extract the wattage anchors (`watts_at_low`, `watts_at_transition`, `taper_floor_w`), compute the calibration active Wh and curve landmarks, and write a profile-summary JSON. Proof: unit tests, `bdd/anchor/fixture-analyzer-anchor-bdd.md` evidence, and generated JSON read back from disk.
**Current readiness:** READY-FOR-NEXT-PACKET

## Recent sessions (rolling, last 5)

- **2026-06-08** - Calibration & rescue refinements - Added rated-capacity input + overhead estimation and opportunistic near-empty-to-full calibration (incl. temperature/full-Wh learning) to ADR-0007; added ADR-0010 for calibrating the pure core on imported Home Assistant history; made low-battery probe/rescue a toggleable, off-by-default feature (ADR-0005). Updated the calibration/rescue/setup specs + BDDs and the architecture doc.
- **2026-06-08** - Design reconciliation - Folded the prior e-bike chat design into the docs: reframed ADR-0002 to wattage-anchor SoC estimation (active Wh demoted to calibration/guardrail), required a dedicated metering plug in ADR-0001, added ADR-0008 (temperature policy) and ADR-0009 (modes/scheduling/safe defaults), updated CLAUDE.md invariant #4, expanded the calibration/session-control/guardrails/setup specs + BDDs, and added the HA-adapter-lessons research note.
- **2026-06-08** - Workflow port + rename - Ported the agentic workflow from Codex back to native Claude Code (.claude/ commands, agents, SessionStart hook) and renamed ChargeShape to CycleSteward across the repo.
- **2026-06-08** - Seed repo - Created workflow contract, initial ADRs, draft specs, BDDs, research notes, and a minimal Python scaffold for the first implementation slice.

## Active work

### Fixture analyzer anchor artifact

- [ ] Define the CSV fixture input schema in code and tests.
- [ ] Implement idle-subtracted active Wh integration for one low-to-full fixture (calibration aid).
- [ ] Extract the wattage anchors: `watts_at_low` (CC-start), `watts_at_transition` (CC->CV peak), `taper_floor_w`.
- [ ] Detect basic curve landmarks: start power band, peak/knee candidate, taper, completion threshold.
- [ ] Emit a profile-summary JSON artifact (anchors + active Wh + landmarks) and read it back in evidence.
- [ ] Produce BDD evidence for `bdd/anchor/fixture-analyzer-anchor-bdd.md`.

## Open queue (non-blocking)

- (a) Decide the Home Assistant domain slug (name resolved: CycleSteward; `docs/research/naming.md`).
- (b) Tune default values for the temperature thresholds/coefficient (ADR-0008) and the morning-reset/scheduled-start times (ADR-0009).
- (f) Decide the remaining Home Assistant entity/service surface after the core model is proven.
- (c) Research how often users should be prompted for full calibration/balancing charges.
- (d) Decide default probe cadence and relay-cycle limits for low-battery detection.
- (e) Build synthetic and real charge-session fixture library.

## Blockers

- None for the first anchor slice. Later Home Assistant integration slices need decisions on entity naming, setup-flow UX, and persistent storage schema.
