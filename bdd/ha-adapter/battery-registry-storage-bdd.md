# Multi-battery: battery registry and profile-library storage — BDD

## Status

Draft. Paired with [docs/specs/battery-registry-storage.md](../../docs/specs/battery-registry-storage.md).

## Why this BDD exists

Pins down that existing calibration data survives the v1→v2 storage migration
untouched, and that one battery charged through two meters yields one registry
identity with two independent learned profiles (ADR-0014, invariant 3).

## Scenarios

### Scenario A — happy path: fresh install stores a v2 library and one registry identity

**Given** a new config entry with `battery_label: "Swoop battery"` and no
prior stored data
**When** `async_setup_entry` completes
**Then** the entry's store holds a v2 payload with
`active_battery_id: "swoop_battery"` and one profile under `profiles`, the
registry holds one matching identity, and the coordinator runs against that
profile exactly as a single-profile install does today.

### Scenario B — migration: existing v1 calibration data is wrapped, never discarded

**Given** a persisted v1 store payload containing a calibrated profile
(non-trivial anchors, full observations, temperature observations)
**When** the store loads under `STORAGE_VERSION = 2`
**Then** the payload becomes
`{"active_battery_id": <slug of its battery_label>, "profiles": {<slug>: <old payload>}}`
where the wrapped profile dict is **byte-identical** to the v1 payload, and
setup reconciliation creates the matching registry identity from the
profile's own persisted labels.

### Scenario C — two meters, one battery: one identity, two independent profiles

**Given** entry M1 with a calibrated profile for `battery_label: "Swoop
battery"` and a second entry M2 configured with the same label
**When** M2 completes setup and persists its (fresh) profile
**Then** the registry holds exactly one `swoop_battery` identity, M2's store
holds an uncalibrated profile under that id, and M1's stored anchors are
byte-identical to their pre-M2 values.

### Scenario D — round-trip: library and active selection survive reload

**Given** an entry whose store holds two profiles with
`active_battery_id` set to the second
**When** the store is saved, dropped, and loaded again
**Then** both profiles and the active id read back equal to what was saved.

### Scenario E — idempotence: a v2 payload is never re-wrapped

**Given** a store already holding a v2 payload
**When** it is loaded again
**Then** the migration path does not run and the payload is unchanged (no
double nesting, `active_battery_id` preserved).

## Evidence

The implementing slice produces an evidence file at
`bdd/ha-adapter/battery-registry-storage-evidence.md` containing raw outputs
(not summaries) for each scenario, and the anchor trace at
`bdd/ha-adapter/battery-registry-storage-trace.json` (migration,
reconciliation, and two-meter legs).
