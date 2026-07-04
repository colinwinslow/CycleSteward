---
status: accepted
date: 2026-07-03
depends-on-adrs: [0014, 0007, 0002]
---

# Multi-battery: battery registry and profile-library storage

## Status

Accepted 2026-07-04. Defines the storage contract for ADR-0014 slice 1: the domain-level
battery registry, the per-entry profile library, and the v1→v2 migration.
Coordinator profile-swap and the `active_battery` select entity are later
slices (see Non-goals).

## Related docs

- [bdd/ha-adapter/battery-registry-storage-bdd.md](../../bdd/ha-adapter/battery-registry-storage-bdd.md) — observable behavior
- [docs/decisions/0014-multi-battery-profile-registry.md](../decisions/0014-multi-battery-profile-registry.md) — the decision this implements
- [STATUS.md](../../STATUS.md) — current phase and active work

## Context

ADR-0014 splits CycleSteward's 1:1:1 chain into: config entry = one
meter+plug; battery identities in a domain-level registry; learned profiles
keyed (battery identity, entry). This slice builds only the storage layer for
that split, shaped so runtime behavior is **unchanged for existing users**:
setup still loads exactly one profile into the coordinator — now the library's
active profile instead of the store's only profile. Existing calibration data
migrates in place; nothing is discarded.

## Behavior contract

### Embedded decisions

- **D1 — Registry home:** a domain-level HA `Store` with key
  `cyclesteward.registry` (its own `STORAGE_VERSION = 1`), independent of any
  config entry. Loaded once per HA run and shared via `hass.data[DOMAIN]`.
  (Resolves ADR-0014 open item "registry storage home".)
- **D2 — Battery IDs are deterministic slugs of `battery_label`**
  (`homeassistant.util.slugify`; collision at registration appends `-2`,
  `-3`, …). Determinism makes migration idempotent and — deliberately — makes
  two entries that persisted the same `battery_label` converge on the *same*
  registry identity: that is the same physical battery seen from two meters,
  exactly the ADR-0014 scenario. Renaming a battery changes its display
  labels, never its `battery_id`.
- **D3 — Store migration is pure data-shape; registry reconciliation is setup
  logic.** The per-entry store migrates v1→v2 inside
  `Store._async_migrate_func` (no cross-store access). `async_setup_entry`
  then reconciles: any `battery_id` present in the entry's library but absent
  from the registry gets an identity created from that profile's own
  persisted labels (`charger_label`, `battery_label`, `rated_capacity_wh` —
  all present in v1 payloads).

### New module: `custom_components/cyclesteward/battery_registry.py`

```python
@dataclass
class BatteryIdentity:
    battery_id: str                      # slug key, stable across renames
    charger_label: str
    battery_label: str
    rated_capacity_wh: Optional[float] = None
    target_soc_dots: Optional[int] = None  # coarse, invariant 6

    def to_dict(self) -> Dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BatteryIdentity: ...

class BatteryRegistry:
    """Domain-level identity store; HA imports deferred (ha_stubs-testable)."""
    def __init__(self, hass) -> None: ...          # Store(hass, 1, "cyclesteward.registry")
    async def async_load(self) -> None: ...        # populates in-memory dict
    @property
    def identities(self) -> Dict[str, BatteryIdentity]: ...
    def get(self, battery_id: str) -> Optional[BatteryIdentity]: ...
    async def async_register(self, identity: BatteryIdentity) -> str: ...
                                                   # returns final battery_id (D2 collision rule)
    async def async_ensure(self, identity: BatteryIdentity) -> str: ...
                                                   # register iff battery_id absent; reconciliation path
```

Registry payload: `{"identities": {battery_id: identity_dict}}`.

### Changed module: `custom_components/cyclesteward/profile_store.py`

`STORAGE_VERSION` 1 → 2. `ProfileStore` subclasses (or wraps a subclass of)
HA `Store` to supply `_async_migrate_func`.

v2 payload:

```json
{
  "active_battery_id": "<battery_id or null>",
  "profiles": { "<battery_id>": { /* CalibrationProfile.to_dict() */ } }
}
```

Migration v1→v2: the old payload is a bare `CalibrationProfile` dict; derive
`battery_id = slugify(old["battery_label"])` and return
`{"active_battery_id": id, "profiles": {id: old}}`. The wrapped profile dict
is byte-identical to the v1 payload (anchors, observations, temperature data
untouched).

New API (old `async_load`/`async_save` single-profile signatures are
replaced; all callers are in this repo):

```python
class ProfileStore:
    async def async_load(self) -> None: ...       # loads + migrates the library
    @property
    def active_battery_id(self) -> Optional[str]: ...
    @property
    def battery_ids(self) -> List[str]: ...
    def get_profile(self, battery_id: str) -> Optional[CalibrationProfile]: ...
    async def async_set_active(self, battery_id: str) -> None: ...   # persists
    async def async_save_profile(
        self, battery_id: str, profile: CalibrationProfile
    ) -> None: ...
```

### Changed wiring: `custom_components/cyclesteward/__init__.py`

`async_setup_entry`:

1. Load (or create) the shared `BatteryRegistry` under
   `hass.data[DOMAIN]["registry"]` (created on first entry, reused after).
2. Load the entry's `ProfileStore` (migration runs here if needed).
3. Reconcile (D3): `async_ensure` an identity for every `battery_id` in the
   library, built from that profile's persisted labels.
4. Fresh install (empty library): build a `CalibrationProfile` from
   `entry.data` exactly as today, register its identity, store it as the
   active profile.
5. Load the **active** profile into the coordinator — one coordinator, one
   watcher, one active profile, exactly as today.

`HASensorWatcher` calibration saves go through
`async_save_profile(active_battery_id, profile)`.

Coordinator, watcher, entities, services, config flow: **unchanged**.

## Anchor artifact

`bdd/ha-adapter/battery-registry-storage-trace.json` — raw before/after
storage payloads, read back from disk:

1. **migration leg**: a real v1 payload (labels + calibrated anchors) and the
   v2 payload the migration function returns for it.
2. **reconciliation leg**: the registry payload after setup over that
   migrated store — one identity, id slugified from the persisted label.
3. **two-meter leg**: registry + both entries' v2 payloads after a second
   entry stores a fresh profile under the same `battery_id` — one identity,
   two independent profile dicts; the first entry's anchors byte-identical to
   leg 1.

## Implementation order

1. Pure migration function + test feeding a realistic v1 dict; write the
   trace's migration leg from its real output.
2. `BatteryIdentity` / `BatteryRegistry` module + tests (ha_stubs harness).
3. `ProfileStore` v2 (subclass, migrate func, new API) + tests, including
   migration-idempotence (a v2 payload is never re-wrapped).
4. `__init__.py` wiring (registry load, reconciliation, fresh-install path,
   active-profile load) + `watcher` save path; tests via `test_ha_wiring.py`
   patterns.
5. Remaining trace legs + evidence file.

## Proof requirements

1. New unit tests green in the offline suite (`python -m pytest`); all 302
   existing tests still green; ruff clean.
2. BDD scenarios A–E in
   `bdd/ha-adapter/battery-registry-storage-bdd.md` pass, with raw outputs in
   `bdd/ha-adapter/battery-registry-storage-evidence.md`.
3. Anchor trace verified on disk: migration leg's wrapped profile dict is
   byte-identical to the v1 input; two-meter leg shows one identity, two
   profiles.

## Non-goals

- Coordinator profile-swap and its mid-session guard (ADR-0014 slice 2).
- The `active_battery` select entity, "add new battery" UX, and moving
  identity fields out of `config_flow.py` (slice 3).
- Cross-meter anchor transfer/seeding (ADR-0014 defers; needs evidence).
- Curve-fingerprint battery detection (ADR-0014 defers).
- Real-HA (`tests_ha/`) coverage of migration — offline harness proves this
  slice; the smoke suite gains multi-battery legs when the entity surface
  lands.

## References

- ADR-0014: Multi-battery support via a battery registry and per-meter profiles
- ADR-0007: Calibration lifecycle (rated capacity as identity-level fact)
- ADR-0002: Wattage-anchor SoC estimation (why anchors must not cross meters)
- `custom_components/cyclesteward/profile_store.py`
- `custom_components/cyclesteward/__init__.py`
- `docs/specs/config-entry-plumbing.md` (the wiring this extends)
