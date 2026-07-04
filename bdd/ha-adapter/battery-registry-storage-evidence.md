# Battery registry and profile-library storage — BDD evidence

Run date: 2026-07-04
Spec: [docs/specs/battery-registry-storage.md](../../docs/specs/battery-registry-storage.md) (accepted)
BDD: [battery-registry-storage-bdd.md](battery-registry-storage-bdd.md)
Anchor trace: [battery-registry-storage-trace.json](battery-registry-storage-trace.json)

Environment: offline suite (Python 3.12.3, pytest 8.4.2, HA stubbed via
`tests/ha_stubs.py`; the stub `Store` mirrors the real version-aware
migration contract — mismatched stored version routes through
`_async_migrate_func` without persisting, as real HA storage does).

## Scenario → test mapping and raw output

- **A** fresh install → `TestSetupWiring::test_scenario_a_fresh_install`
- **B** migration never discards → `TestProfileStoreMigration::test_scenario_b_v1_payload_wrapped_never_discarded`, `TestSetupWiring::test_scenario_b_reconciliation_builds_identity_from_stored_labels`, plus `TestMigrateV1Payload` (pure-function legs)
- **C** two meters, one identity → `TestSetupWiring::test_scenario_c_two_meters_one_identity_two_profiles`
- **D** round-trip → `TestProfileStoreMigration::test_scenario_d_library_round_trip`, `test_ha_wiring.py::TestProfileStore::test_save_then_reload_round_trips`
- **E** idempotence → `TestProfileStoreMigration::test_scenario_e_v2_payload_not_rewrapped`

```text
$ python3 -m pytest tests/test_battery_registry_storage.py tests/test_ha_wiring.py::TestProfileStore -v
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-8.4.2, pluggy-1.6.0 -- /usr/bin/python3
rootdir: /home/claude/repos/cyclesteward
configfile: pyproject.toml
collecting ... collected 19 items

tests/test_battery_registry_storage.py::TestMigrateV1Payload::test_wraps_under_slug_of_battery_label PASSED [  5%]
tests/test_battery_registry_storage.py::TestMigrateV1Payload::test_inner_profile_dict_is_untouched PASSED [ 10%]
tests/test_battery_registry_storage.py::TestMigrateV1Payload::test_deterministic PASSED [ 15%]
tests/test_battery_registry_storage.py::TestBatteryRegistry::test_load_empty PASSED [ 21%]
tests/test_battery_registry_storage.py::TestBatteryRegistry::test_register_and_round_trip PASSED [ 26%]
tests/test_battery_registry_storage.py::TestBatteryRegistry::test_register_collision_appends_dash_suffix PASSED [ 31%]
tests/test_battery_registry_storage.py::TestBatteryRegistry::test_ensure_is_idempotent_and_existing_wins PASSED [ 36%]
tests/test_battery_registry_storage.py::TestProfileStoreMigration::test_scenario_b_v1_payload_wrapped_never_discarded PASSED [ 42%]
tests/test_battery_registry_storage.py::TestProfileStoreMigration::test_scenario_e_v2_payload_not_rewrapped PASSED [ 47%]
tests/test_battery_registry_storage.py::TestProfileStoreMigration::test_scenario_d_library_round_trip PASSED [ 52%]
tests/test_battery_registry_storage.py::TestSetupWiring::test_scenario_a_fresh_install PASSED [ 57%]
tests/test_battery_registry_storage.py::TestSetupWiring::test_scenario_b_reconciliation_builds_identity_from_stored_labels PASSED [ 63%]
tests/test_battery_registry_storage.py::TestSetupWiring::test_dangling_active_id_falls_back_deterministically PASSED [ 68%]
tests/test_battery_registry_storage.py::TestSetupWiring::test_scenario_c_two_meters_one_identity_two_profiles PASSED [ 73%]
tests/test_battery_registry_storage.py::test_generate_battery_registry_storage_trace PASSED [ 78%]
tests/test_ha_wiring.py::TestProfileStore::test_load_empty_yields_empty_library PASSED [ 84%]
tests/test_ha_wiring.py::TestProfileStore::test_save_then_reload_round_trips PASSED [ 89%]
tests/test_ha_wiring.py::TestProfileStore::test_load_reconstructs_all_fields PASSED [ 94%]
tests/test_ha_wiring.py::TestProfileStore::test_set_active_requires_stored_profile PASSED [100%]

============================== 19 passed in 0.07s ==============================
```

Full suite (existing 302 unaffected; 16 tests added or reworked, including
the trace-generation test and the dangling-active-id fallback test added
after architecture review):

```text
$ python3 -m pytest -q
318 passed in 0.54s
```

## Anchor trace: generation and on-disk verification

The trace is written and verified by
`tests/test_battery_registry_storage.py::test_generate_battery_registry_storage_trace`
(repo convention, same as the probe-disambiguation trace): it drives the real
migration function, `async_setup_entry`, and `ProfileStore` against the stub
storage backing, dumps the raw persisted payloads, then reads the file back
and asserts every leg's claims. Inputs are deterministic (fixed timestamps in
`_calibrated_v1_payload()`), so regeneration is:

```text
$ python3 -m pytest tests/test_battery_registry_storage.py::test_generate_battery_registry_storage_trace -v
```

Read-back verification, raw output:

```text
$ python3 - <<'EOF'
import json
t = json.load(open("bdd/ha-adapter/battery-registry-storage-trace.json"))
legs = t["legs"]
m = legs["migration"]
print("active id:", m["v2_payload"]["active_battery_id"])
print("anchors in wrapped profile:",
      m["v2_payload"]["profiles"]["swoop_battery"]["watts_at_low"],
      m["v2_payload"]["profiles"]["swoop_battery"]["watts_at_transition"])
print("byte-identical flag:", m["inner_profile_byte_identical_to_v1"])
print("registry identity:",
      json.dumps(legs["reconciliation"]["registry_payload"]["identities"], indent=1))
tm = legs["two_meter"]
p2 = tm["entry_m2_payload"]["profiles"]["swoop_battery"]
print("m2 state:", p2["state"], "| m2 watts_at_low:", p2["watts_at_low"])
print("m1 calibrated watts:",
      tm["entry_m1_payload"]["profiles"]["swoop_battery"]["watts_at_transition"]["watts"])
print("m1 unchanged:", tm["m1_payload_unchanged_by_m2_setup"],
      "| identities:", tm["registry_identity_count"])
EOF
active id: swoop_battery
anchors in wrapped profile: {'watts': 69.7, 'assumed_soc_label': 'display-empty', 'confidence': 'high'} {'watts': 127.4, 'assumed_soc_label': 'cc-cv-peak', 'confidence': 'high'}
byte-identical flag: True
registry identity: {
 "swoop_battery": {
  "battery_id": "swoop_battery",
  "charger_label": "Shimano EC-E6000",
  "battery_label": "Swoop battery",
  "rated_capacity_wh": 504.0,
  "target_soc_dots": 4
 }
}
m2 state: uncalibrated | m2 watts_at_low: None
m1 calibrated watts: 127.4
m1 unchanged: True | identities: 1
```

Leg-by-leg claims, each backed by a field in the trace JSON:

1. **Migration leg** — `legs.migration.inner_profile_byte_identical_to_v1: true`;
   the wrapped `profiles.swoop_battery` dict equals the v1 input including all
   nested anchors, one full observation (`elapsed_seconds: 14520.0`), one
   temperature observation, and the seeded warning string.
2. **Reconciliation leg** — `legs.reconciliation.registry_payload` holds
   exactly one identity, built from the *persisted profile's* labels (not
   entry defaults), with the entry's coarse `target_soc_dots: 4` attached.
3. **Two-meter leg** — `legs.two_meter.registry_identity_count: 1` (no
   `swoop_battery-2` fork); `entry_m2_payload` is a fresh uncalibrated
   profile under the shared id; `m1_payload_unchanged_by_m2_setup: true`
   (M1's calibrated anchors byte-identical before/after M2's setup).

## Notes

- Ruff: clean for all files touched by this slice. One pre-existing F401 in
  `tests_ha/test_real_ha_smoke.py` (unused `pytest` import) is flagged by
  ruff ≥ 0.14 but predates this packet and is left for a separate commit.
- The real-HA (`tests_ha/`) suite gains multi-battery legs when the entity
  surface lands (spec non-goal for slice 1).
