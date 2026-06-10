# HA calibration ingestion — BDD evidence

Generated: 2026-06-09. All scenarios from `ha-calibration-ingestion-bdd.md` verified green.

## Test run

```
tests/test_ha_calibration_ingestion.py::TestScenarioA::test_ingest_full_session_called_on_taper_completion PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioA::test_elapsed_seconds_recorded PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioB::test_no_ingest_on_charge_to_target_completion PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioC::test_no_ingest_on_guardrail_fault PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioD::test_elapsed_seconds_and_round_trip PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioD::test_estimated_duration_s_pessimistic_when_no_observations PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioD::test_estimated_duration_s_from_single_observation PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioD::test_estimated_duration_s_stddev_with_three_observations PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioE::test_temp_correction_promotes_warm_session_to_full PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioE::test_no_temp_reading_uses_raw_comparison PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioE::test_reference_temp_updated_on_trusted_full_ingestion PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioF::test_mid_charge_session_demoted_to_partial PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioF::test_watts_at_low_anchor_unchanged_after_mid_charge PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioF::test_active_full_wh_unchanged_after_mid_charge PASSED
tests/test_ha_calibration_ingestion.py::TestScenarioF::test_save_still_called_for_mid_charge_partial PASSED
tests/test_ha_calibration_ingestion.py::TestIngestFromTrace::test_empty_trace_returns_profile_unchanged PASSED
tests/test_ha_calibration_ingestion.py::TestIngestFromTrace::test_first_calibration_no_anchor_always_full PASSED
tests/test_ha_calibration_ingestion.py::TestIngestFromTrace::test_near_anchor_start_ingest_full PASSED
tests/test_ha_calibration_ingestion.py::TestIngestFromTrace::test_far_from_anchor_start_ingest_partial PASSED
tests/test_ha_calibration_ingestion.py::TestIngestFromTrace::test_profile_property_returns_current_profile PASSED

20 passed in 0.06s
```

Full suite: **194 passed**, ruff clean.

## Scenario A — taper-floor completion in CHARGE_TO_FULL → ingest and save

`test_ingest_full_session_called_on_taper_completion`: Coordinator in CHARGE_TO_FULL with
`watts_at_low=90.0`, `taper_floor_w=30.0`. Five CC ticks (95→75 W), then two taper ticks
(20 W, 18 W) 2 s apart — exceeds `taper_below_floor_seconds=1`. On the tick that fires
the taper cutoff, `HASensorWatcher._do_tick()` detects the CHARGING→DONE_LATCHED_OFF
transition with reason containing "taper floor", calls `coordinator.ingest_from_trace()`,
and awaits `profile_store.async_save()`. `store_mock.async_save` called once;
`len(saved_profile.full_observations) == 1` ✓

`test_elapsed_seconds_recorded`: Uncalibrated profile with `taper_floor_w=30.0`.
Seven CC ticks (90→78 W at 300 s intervals), then two taper ticks at t=2500 and t=2502.
After taper fires: `len(saved.elapsed_seconds) >= 1` and `saved.elapsed_seconds[0] > 0` ✓

## Scenario B — CHARGE_TO_TARGET session end → NOT ingested

`test_no_ingest_on_charge_to_target_completion`: Coordinator in CHARGE_TO_TARGET mode.
Tick at 80 W → CHARGING, tick at 130 W (target) at t=35 s → DONE_LATCHED_OFF with
reason "wattage crossed target threshold" (no "taper floor"). Ingestion trigger skipped.
`store_mock.async_save` not called; `len(profile.full_observations) == 0` ✓

## Scenario C — CHARGE_TO_FULL + guardrail fault → NOT ingested

`test_no_ingest_on_guardrail_fault`: CHARGE_TO_FULL with `max_runtime_seconds=5`.
Tick at t=0 → CHARGING, tick at t=6 → max-runtime guardrail fires → DONE_LATCHED_OFF
with reason containing "max runtime" (not "taper floor"). Trigger skipped.
`store_mock.async_save` not called ✓

## Scenario D — anchor artifact + round-trip

`test_elapsed_seconds_and_round_trip`: Uncalibrated profile. Synthetic 18-sample
CC→CV→taper trace (360 s intervals, ~102-minute span) passed directly to
`coordinator.ingest_from_trace()`. `len(updated.elapsed_seconds) == 1`;
`elapsed_seconds[0] == 6120.0 s` (17 intervals × 360 s) ✓.
`CalibrationProfile.from_json(updated.to_json())` restores `elapsed_seconds[0]` exactly ✓.
Artifact written to `bdd/ha-adapter/ha-calibration-ingestion-trace.json`.

`test_estimated_duration_s_pessimistic_when_no_observations`: No observations →
`(4*3600, 0.2*4*3600)` returned ✓

`test_estimated_duration_s_from_single_observation`: 1 observation → uncertainty = 20% of mean ✓

`test_estimated_duration_s_stddev_with_three_observations`: 3 observations (10/15/20
intervals × 360 s = 3240/5040/6840 s) → uncertainty is stddev across all three,
not fixed 20% ✓

## Scenario E — temperature correction promotes warm-start to full

`test_temp_correction_promotes_warm_session_to_full`: Profile calibrated at 8°C with
`watts_at_low=65.0 W`. Session at 25°C starts at 75.0 W. Test runs BOTH paths to prove
correction is load-bearing:
- **Raw path** (`session_temp_c=None`): 75 W vs 65 W = 15.4% > 15% → `ingest_partial_session`;
  `len(full_observations)==0`, `len(partial_observations)==1` ✓
- **Corrected path** (`session_temp_c=25.0`): `75.0 + 0.3*(8-25) = 69.9 W`, 7.5% from
  anchor < 15% → `ingest_full_session`; `len(full_observations)==1`,
  `len(partial_observations)==0` ✓

`test_no_temp_reading_uses_raw_comparison`: Same profile and config, but no temp reading.
Trace starting at 85 W: raw proximity 30.8% > 15% → demoted to partial.
`len(partial_observations) == 1`, `len(full_observations) == 0` ✓

`test_reference_temp_updated_on_trusted_full_ingestion`: Uncalibrated profile, 33-sample
trace, session_temp_c=22.0. After trusted ingestion, `profile.reference_temp_c == 22.0` ✓

## Scenario F — genuine mid-charge rejected as partial, anchors protected

`test_mid_charge_session_demoted_to_partial`: Profile `watts_at_low=70.0`, session at
same 20°C reference. Trace starts at 110 W → 57% above anchor → `ingest_partial_session`
called. `len(full_observations) == 0`, `len(partial_observations) == 1` ✓

`test_watts_at_low_anchor_unchanged_after_mid_charge`: After mid-charge ingestion,
`profile.watts_at_low.watts == 70.0` (unchanged) ✓

`test_active_full_wh_unchanged_after_mid_charge`: After mid-charge ingestion,
`profile.active_full_wh == 400.0` (unchanged) ✓

`test_save_still_called_for_mid_charge_partial`: Watcher test. High-starting trace
(110 W) + taper completion. `store_mock.async_save` called once; saved profile has
`len(full_observations) == 0`, `len(partial_observations) == 1` ✓

## Anchor artifact

`bdd/ha-adapter/ha-calibration-ingestion-trace.json` contains:
- `profile_before`: uncalibrated profile (no anchors)
- `raw_trace`: 18 readings, 95→72 W CC, 40 W CV, 10 W taper, at 360-second intervals
- `profile_after`: calibrated profile with `watts_at_low=95.0`, `elapsed_seconds=6120.0`
  in `full_observations[0]`
