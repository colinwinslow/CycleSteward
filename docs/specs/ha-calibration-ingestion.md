# Spec: HA calibration ingestion (adapter slice 3)

## What this slice does

Detects when a `CHARGE_TO_FULL` session completes via the taper floor, feeds the
accumulated live power trace to `CalibrationProfile.ingest_full_session()`, and
persists the updated profile to HA storage via `ProfileStore`.

## Scope

- **In:** Detection of taper-floor completion in `HASensorWatcher._do_tick()`.
  Ingestion of the live trace buffer. Persistence via `ProfileStore.save()`.
- **Out:** Scheduling logic, finish-time estimation, any user-facing entity change.
  Those belong in later slices.

## Behavioural contract

### Ingestion trigger

`HASensorWatcher._do_tick()` checks, after each tick, whether all of:

1. Previous state was `CHARGING`.
2. Current state is `DONE_LATCHED_OFF`.
3. `coordinator.charge_mode == ChargeMode.CHARGE_TO_FULL`.
4. `coordinator.session_reason` contains `"taper floor"`.

When all four hold, ingestion runs.

### Ingestion path

1. Call `coordinator.ingest_from_trace(trace_buffer)` — a new coordinator method
   that:
   a. Converts the `(datetime, float)` trace buffer to `Sample` objects and calls
      `analyze()` to produce a `ProfileSummary`.
   b. Decides *which* ingest method to call (see "Full vs. partial decision" below).
   c. Returns the updated profile.
2. Call `profile_store.save(updated_profile)` — persists to HA storage.

`HASensorWatcher` receives a `ProfileStore` reference at construction time for
use in step 2.

### Full vs. partial decision

`ingest_from_trace()` implements the full/partial decision inline with temperature
correction. Note: `CalibrationProfile.classify_opportunistic_session()` exists as a
separate path for opportunistic (non-taper-completion) sessions and does not support
temperature correction, so it is not used here.

- **Profile has no `watts_at_low` anchor yet** (first ever calibration) → call
  `ingest_full_session(summary)`.
- **Profile has `watts_at_low`** AND the temperature-corrected trace `watts_at_low`
  is within the proximity tolerance → call `ingest_full_session(summary)`.
- **Profile has `watts_at_low`** AND the temperature-corrected trace `watts_at_low`
  is too far above the anchor (session started mid-charge) → call
  `ingest_partial_session(summary)`. The `active_full_wh` denominator and
  calibrated anchor are *not* updated.

**Temperature correction** (see `docs/research/temperature-battery-charging.md`):
cold sessions draw lower CC wattage (BMS reduces current), so a profile
calibrated in cold conditions will have a lower `watts_at_low` anchor than the
same battery in warm weather. Before the proximity comparison, the observed
starting wattage is corrected to the profile's reference temperature:

```
corrected = observed_watts_at_low + temp_coefficient_w_per_c × (ref_temp_c − session_temp_c)
```

If no temperature reading is available, the raw wattage is used. The
conservative failure mode (session demoted to partial) does not corrupt the
profile, but may miss valid full-session data.

This prevents a mid-charge taper completion from corrupting the `active_full_wh`
denominator or overwriting a good `watts_at_low` anchor with a mid-session reading.

### Non-ingestion cases

- Mode is `CHARGE_TO_TARGET` → no call to either ingest method.
- Mode is `CHARGE_TO_FULL` but session ended for a non-taper reason (guardrail
  fault, manual override, etc.) → no call.
- Session transitions to `FAULTED` → no call.

### Profile availability

After ingestion, `coordinator.profile` reflects the updated `CalibrationProfile`.
Subsequent ticks use the updated profile (e.g., `target_wattage` is now derived
from the freshly calibrated anchors).

## New surface

| Symbol | Location | Purpose |
|---|---|---|
| `coordinator.ingest_from_trace(trace)` | `coordinator.py` | Analyzes trace, decides full vs. partial (temperature-corrected proximity), ingests, returns updated profile |
| `HASensorWatcher.__init__(…, profile_store)` | `watcher.py` | New required kwarg; used after taper completion |
| `HASensorWatcher._do_tick()` | `watcher.py` | Extended with ingestion trigger |
| `CalibrationProfile.reference_temp_c` | `calibration.py` | Optional float; temperature at which `watts_at_low` was calibrated; used in proximity correction formula |

## Anchor artifact

`bdd/ha-adapter/ha-calibration-ingestion-trace.json` — a JSON file produced
by the test for Scenario D. It contains the profile before ingestion, the raw
trace passed to `ingest_from_trace`, and the profile after ingestion, so a
human can verify the full session landed in the profile's session history.

## BDD

Paired with `bdd/ha-adapter/ha-calibration-ingestion-bdd.md`.
