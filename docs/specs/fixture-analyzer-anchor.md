---
status: draft
date: 2026-06-08
depends-on-adrs: [0001, 0002, 0003, 0006, 0007]
---

# Anchor: Fixture analyzer profile summary

## Status

Draft. Defines the first concrete artifact for proving the core estimation
model before Home Assistant plumbing.

## Related docs

- [bdd/anchor/fixture-analyzer-anchor-bdd.md](../../bdd/anchor/fixture-analyzer-anchor-bdd.md) - observable behavior and scenarios
- [STATUS.md](../../STATUS.md) - current phase and active work
- [docs/architecture/cyclesteward-architecture.md](../architecture/cyclesteward-architecture.md)

## Context

The project needs proof that a wall-power session can be turned into useful
profile data. The first visible artifact should be simple: feed in a CSV fixture
and write a JSON profile summary with the two wattage anchors (the primary signal
under ADR-0002), the idle-subtracted active Wh used to calibrate them, and basic
curve landmarks. Because a dedicated metering plug is assumed (ADR-0001),
`idle_power_w` is only the charger's own standby.

## Behavior contract

The anchor implementation accepts a CSV charge-session fixture with at least:

```text
timestamp,power_w
```

Optional first-slice columns:

```text
temperature_c
```

The analyzer outputs JSON containing at least:

```json
{
  "schema_version": 1,
  "profile_id": "fixture:<name>",
  "sample_count": 0,
  "idle_power_w": 0.0,
  "anchors": {
    "watts_at_low": null,
    "watts_at_transition": null,
    "taper_floor_w": null
  },
  "active_full_wh": 0.0,
  "landmarks": {
    "active_start_timestamp": null,
    "peak_power_w": null,
    "peak_timestamp": null,
    "taper_start_timestamp": null,
    "completion_timestamp": null
  },
  "warnings": []
}
```

`watts_at_low` is the CC-start active wattage, `watts_at_transition` is the
wattage at the CC->CV peak, and `taper_floor_w` is the settled near-idle wattage
before completion. These are the wattage anchors (ADR-0002); `active_full_wh` is
the calibration aid, not the headline metric.

Exact schema may evolve, but the artifact must be inspectable and deterministic
for a fixture.

## Anchor artifact

A generated `profile-summary.json` file created from
`fixtures/synthetic-low-to-full.csv` and read back during evidence collection.

## Implementation order

1. Define fixture parser and validation errors.
2. Implement idle-power estimation or accept an explicit idle value for the
   first slice.
3. Integrate active Wh with timestamp deltas.
4. Detect peak and simple taper/completion landmarks.
5. Emit deterministic JSON.
6. Produce BDD evidence with the command, raw output, and file contents read
   back.

## Proof requirements

1. Unit tests for parsing, idle subtraction, Wh integration, and malformed CSVs.
2. BDD scenarios in `bdd/anchor/fixture-analyzer-anchor-bdd.md` pass.
3. The generated profile-summary JSON is read back from disk in evidence.

## Non-goals

- Home Assistant config flow or entities.
- Precise SoC estimation.
- Advanced multi-stage fast-charger classification.
- Real-world Shimano fixture validation.

## References

- ADR-0002
- ADR-0003
- ADR-0006
- ADR-0007
