# HA calibration ingestion — BDD

## Status

Draft. Paired with [docs/specs/ha-calibration-ingestion.md](../../docs/specs/ha-calibration-ingestion.md).

## Why this BDD exists

Pins the boundary between "session ended" and "profile updated in HA storage":
a taper-floor completion in `CHARGE_TO_FULL` mode must trigger exactly one
`ingest_full_session()` call and one `ProfileStore.save()` call, while all
other session endings must leave the profile untouched.

## Scenarios

### Scenario A — taper-floor completion in CHARGE_TO_FULL → ingest and save

**Given** `HASensorWatcher` constructed with a `CyclestewardCoordinator` in
`CHARGE_TO_FULL` mode, a calibrated `CalibrationProfile`
(with `taper_floor_w = 15.0`, `watts_at_low = 70.0`, `watts_at_transition = 130.0`),
and a `ProfileStore` mock that records calls to `save()`; the trace buffer holds a
plausible CC→CV→taper sequence: e.g. 10 readings from 95 W down to 12 W

**When** a power tick arrives that causes the coordinator to transition to
`DONE_LATCHED_OFF` with `session_reason` containing `"taper floor"`
(i.e., power has been below `taper_floor_w` for `taper_below_floor_seconds`)

**Then**
- `coordinator.ingest_from_trace(trace)` is called once with the buffered trace
- `ProfileStore.save()` is called once with the updated profile
- The coordinator's profile now has a non-empty `elapsed_seconds` list (the
  ingested session duration was recorded)

### Scenario B — CHARGE_TO_TARGET session end → NOT ingested

**Given** `HASensorWatcher` with coordinator in `CHARGE_TO_TARGET` mode
(profile has `watts_at_transition = 130.0` as the cutoff target);
`ProfileStore.save` is mocked to record calls

**When** a power tick causes the coordinator to transition to `DONE_LATCHED_OFF`
because wattage crossed the target threshold (session_reason: `"wattage crossed
target threshold"`)

**Then**
- `coordinator.ingest_from_trace` is NOT called
- `ProfileStore.save` is NOT called
- The profile is unchanged

### Scenario C — CHARGE_TO_FULL mode, guardrail-fault ending → NOT ingested

**Given** `HASensorWatcher` with coordinator in `CHARGE_TO_FULL` mode;
`GuardrailsConfig` set with a very short `max_runtime_seconds` so the session
will fault before a taper can occur; `ProfileStore.save` is mocked

**When** a series of ticks accumulates enough runtime to trigger the max-runtime
guardrail, transitioning the coordinator to `DONE_LATCHED_OFF` (or `FAULTED`)
with `session_reason` starting with `"guardrail/"`

**Then**
- `coordinator.ingest_from_trace` is NOT called
- `ProfileStore.save` is NOT called

### Scenario D — ingested profile is observable in the saved JSON (anchor artifact)

**Given** a fresh `CalibrationProfile` with 0 entries in `elapsed_seconds`
(no prior full sessions); a trace buffer of 20 readings representing a plausible
80-minute charge from 95 W (CC) to 12 W (taper); `ProfileStore.save` captures
the profile passed to it

**When** `coordinator.ingest_from_trace(trace)` is called and
`ProfileStore.save(updated_profile)` is called

**Then**
- `updated_profile.elapsed_seconds` has exactly 1 entry (the duration of the
  synthetic trace, approximately 80 minutes × 60 seconds)
- The updated profile round-trips cleanly through `to_json()` / `from_json()`
- The round-tripped `elapsed_seconds` list matches the original
- The above facts are recorded in `bdd/ha-adapter/ha-calibration-ingestion-trace.json`
  as a human-readable anchor artifact containing: profile_before (JSON),
  raw_trace (list of [iso-timestamp, watts] pairs), and profile_after (JSON)

### Scenario E — temperature correction promotes a warm-start session to full

Research note: at cold temperatures, a BMS reduces CC current, so a cold
near-empty session will draw *lower* wall power than a warm near-empty session.
A profile calibrated in cold conditions will therefore have a `watts_at_low`
anchor that is lower than the same battery's starting wattage in warm weather.
Without temperature correction, a genuine warm near-empty session would be
incorrectly demoted to partial. See `docs/research/temperature-battery-charging.md`.

**Given** `HASensorWatcher` with coordinator in `CHARGE_TO_FULL` mode; the
profile was calibrated in cold conditions: `watts_at_low = 65.0 W` with
`reference_temp_c = 8.0`; `temp_coefficient_w_per_c = 0.3`; the trace buffer
starts at 75.0 W (genuine near-empty but warm — higher raw wattage than the
cold-calibrated anchor); the watcher has `_cached_temp_c = 25.0`

**When** taper-floor completion occurs in `CHARGE_TO_FULL` mode

**Then**
- The temperature-corrected starting wattage is computed:
  `75.0 + 0.3 × (8.0 − 25.0) = 69.9 W`
- 69.9 W is within the proximity tolerance of the 65.0 W anchor (~7.5%); the
  session qualifies as a full near-empty charge
- `ingest_full_session()` IS called (not partial)
- `ProfileStore.save()` IS called with the updated profile

**Note on the no-temp fallback:** without a temperature reading, the raw starting
wattage (75.0 W) is used. Raw proximity: `|75−65|/65 = 15.4%`, which exceeds the
15% default threshold. Without temperature correction, this session would be
demoted to partial — a conservative failure mode that does not corrupt the profile
anchors. This confirms temperature correction is load-bearing for warm sessions
charted against a cold-calibrated anchor.

### Scenario F — genuine mid-charge session rejected as partial even after temperature correction

**Given** `HASensorWatcher` with coordinator in `CHARGE_TO_FULL` mode; the
profile is calibrated with `watts_at_low = 70.0 W` at `reference_temp_c = 20.0`;
`temp_coefficient_w_per_c = 0.3`; the trace buffer starts at 110.0 W (the user
plugged in mid-charge); `_cached_temp_c = 20.0` (same temperature as calibration
— no temperature correction to apply)

**When** taper-floor completion occurs in `CHARGE_TO_FULL` mode

**Then**
- Temperature-corrected starting wattage: `110.0 + 0.3 × (20.0 − 20.0) = 110.0 W`
- 110.0 W is ~57% above the 70.0 W anchor — far beyond any plausible temperature
  explanation; the session is not a near-empty charge
- `ingest_full_session()` is NOT called
- `ingest_partial_session()` IS called (partial calibration data is still useful)
- `ProfileStore.save()` IS called with the updated profile
- The profile's `watts_at_low` anchor is unchanged (70.0 W)
- The profile's `active_full_wh` is unchanged

## Evidence

The implementing slice produces:
- `bdd/ha-adapter/ha-calibration-ingestion-evidence.md` — raw test outputs
  (not summaries) for each scenario A–F
- `bdd/ha-adapter/ha-calibration-ingestion-trace.json` — anchor artifact (see
  Scenario D)
