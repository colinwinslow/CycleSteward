# STATUS.md

**Last updated:** 2026-06-08 (seed repository created from design conversation)
**Phase:** Phase 0 - design seed and anchor planning
**Next bounded packet:** Implement the fixture analyzer anchor artifact: read one CSV charge-session fixture, subtract idle watts, compute active Wh and curve landmarks, and write a profile-summary JSON. Proof: unit tests, `bdd/anchor/fixture-analyzer-anchor-bdd.md` evidence, and generated JSON read back from disk.
**Current readiness:** READY-FOR-NEXT-PACKET

## Recent sessions (rolling, last 5)

- **2026-06-08** - Seed repo - Created workflow contract, initial ADRs, draft specs, BDDs, research notes, and a minimal Python scaffold for the first implementation slice.

## Active work

### Fixture analyzer anchor artifact

- [ ] Define the CSV fixture input schema in code and tests.
- [ ] Implement idle-subtracted active Wh integration for one low-to-full fixture.
- [ ] Detect basic curve landmarks: start power band, peak/knee candidate, taper, completion threshold.
- [ ] Emit a profile-summary JSON artifact and read it back in evidence.
- [ ] Produce BDD evidence for `bdd/anchor/fixture-analyzer-anchor-bdd.md`.

## Open queue (non-blocking)

- (a) Decide final integration name and domain slug.
- (b) Decide Home Assistant entity/service surface after the core model is proven.
- (c) Research how often users should be prompted for full calibration/balancing charges.
- (d) Decide default probe cadence and relay-cycle limits for low-battery detection.
- (e) Build synthetic and real charge-session fixture library.

## Blockers

- None for the first anchor slice. Later Home Assistant integration slices need decisions on entity naming, setup-flow UX, and persistent storage schema.
