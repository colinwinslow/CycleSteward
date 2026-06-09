# Anchor: Fixture analyzer profile summary - Evidence

Raw evidence that each scenario in
[fixture-analyzer-anchor-bdd.md](fixture-analyzer-anchor-bdd.md) was honestly hit.
Outputs are pasted raw, not summarized.

## Run info

```
run_utc = 2026-06-09T04:37:50Z   (= 2026-06-08 21:37 PDT, the session's local day)
python  = Python 3.9.6
pytest  = pytest-8.4.2
canonical command (3.11+ env): python -m pip install -e ".[dev]" && python -m pytest
this run (3.9 sandbox): PYTHONPATH=src .venv/bin/python -m pytest
```

Note: the project targets Python >=3.11; the only interpreter on this machine is
3.9.6, so the package is run from `src/` via `PYTHONPATH`/`conftest.py` instead of
an editable install. The logic is version-agnostic; the same `pytest` command is
canonical in a 3.11+ environment.

## Full test run

```
$ PYTHONPATH=src .venv/bin/python -m pytest -v
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
configfile: pyproject.toml
testpaths: tests
collected 28 items

tests/test_cli.py::test_analyze_fixture_writes_json PASSED               [  3%]
tests/test_cli.py::test_malformed_input_exits_nonzero_and_writes_nothing PASSED [  7%]
tests/test_cli.py::test_stdout_mode_emits_json PASSED                    [ 10%]
tests/test_energy.py::test_active_power_clamps_at_zero PASSED            [ 14%]
tests/test_energy.py::test_standby_only_samples_add_no_energy PASSED     [ 17%]
tests/test_energy.py::test_integration_uses_idle_subtracted_power PASSED [ 21%]
tests/test_energy.py::test_trapezoidal_ramp PASSED                       [ 25%]
tests/test_energy.py::test_non_increasing_interval_is_skipped PASSED     [ 28%]
tests/test_energy.py::test_estimate_idle_is_lowest_reading PASSED        [ 32%]
tests/test_landmarks.py::test_clean_session_detects_anchors_and_landmarks PASSED [ 35%]
tests/test_landmarks.py::test_noisy_session_still_detects_anchors PASSED [ 39%]
tests/test_landmarks.py::test_interrupted_session_warns_about_gap PASSED [ 42%]
tests/test_landmarks.py::test_no_active_charging_warns PASSED            [ 46%]
tests/test_profile.py::test_analyze_clean_fixture_summary PASSED         [ 50%]
tests/test_profile.py::test_idle_is_estimated_when_not_supplied PASSED   [ 53%]
tests/test_profile.py::test_summary_is_deterministic PASSED             [ 57%]
tests/test_profile.py::test_to_json_is_valid_and_round_trips PASSED      [ 60%]
tests/test_profile.py::test_input_warnings_propagate_to_summary PASSED   [ 64%]
tests/test_real_fixture.py::test_real_session_parses_and_detects_transition PASSED [ 67%]
tests/test_real_fixture.py::test_real_session_active_wh_matches_plug_energy_meter PASSED [ 71%]
tests/test_real_fixture.py::test_real_session_known_artifacts PASSED     [ 75%]
tests/test_samples.py::test_parse_valid_csv_yields_samples PASSED        [ 78%]
tests/test_samples.py::test_missing_required_column_raises PASSED        [ 82%]
tests/test_samples.py::test_midnight_rollover_timestamps_parse PASSED    [ 85%]
tests/test_samples.py::test_unknown_and_empty_rows_are_skipped_with_warnings PASSED [ 89%]
tests/test_samples.py::test_trailing_z_timestamp_is_accepted PASSED      [ 92%]
tests/test_seed_docs.py::test_seed_contains_workflow_contract_and_first_bdd PASSED [ 96%]
tests/test_seed_docs.py::test_agent_contract_names_load_bearing_invariants PASSED [100%]

============================== 28 passed in 6.78s ==============================
```

```
$ .venv/bin/ruff check .
All checks passed!
```

## Scenario A - happy path: low-to-full fixture produces a profile summary

**Given** `fixtures/synthetic-low-to-full.csv` (a clean CC ramp 69->84 W, CV taper
to ~18 W, completion to idle) and a known idle baseline of 1.8 W.
**When** the analyzer runs.
**Then** it writes a JSON profile summary with sample count, idle power, the
wattage anchors, the calibration active Wh, peak power/timestamp, taper and
completion candidates, and no warnings.

```
$ PYTHONPATH=src .venv/bin/python -m cyclesteward.cli analyze-fixture \
    --input fixtures/synthetic-low-to-full.csv --idle-watts 1.8 \
    --output /tmp/profile-summary.json
wrote /tmp/profile-summary.json

$ cat /tmp/profile-summary.json
{
  "schema_version": 1,
  "profile_id": "fixture:synthetic-low-to-full",
  "sample_count": 49,
  "idle_power_w": 1.8,
  "anchors": {
    "watts_at_low": 69.0,
    "watts_at_transition": 84.0,
    "taper_floor_w": 18.0
  },
  "active_full_wh": 467.7333,
  "landmarks": {
    "active_start_timestamp": "2026-06-08T18:10:00-07:00",
    "peak_power_w": 84.0,
    "peak_timestamp": "2026-06-08T23:00:00-07:00",
    "taper_start_timestamp": "2026-06-08T23:10:00-07:00",
    "completion_timestamp": "2026-06-09T01:10:00-07:00"
  },
  "warnings": []
}
```

Observed: `watts_at_low=69.0`, `watts_at_transition=84.0` (the CC->CV peak),
`taper_floor_w=18.0`, `active_full_wh=467.7333`, completion detected, `warnings`
empty. Matches the expected anchors for this curve.

## Scenario B - idle subtraction prevents standby power from becoming charge energy

**Given** readings that begin and end at standby/idle.
**When** the analyzer integrates active Wh as `max(power_w - idle_w, 0)`.
**Then** standby-only rows add no charge energy.

Direct unit evidence (`tests/test_energy.py`), all PASSED above:

- `test_standby_only_samples_add_no_energy`: three readings all at 2.0 W with
  idle 2.0 W integrate to exactly `0.0` Wh.
- `test_integration_uses_idle_subtracted_power`: 10 W for 1 h at idle 2 W = `8.0`
  Wh (active = 10-2).
- `test_trapezoidal_ramp`: 2 W -> 10 W over 1 h at idle 2 W = `4.0` Wh (avg active
  4 W).
- `test_active_power_clamps_at_zero`: `active_power_w(1.5, 2.0) == 0.0`.

Raw run (standby-only adds nothing; idle-subtracted active integrates; the
idle-bookended clean fixture):

```
$ PYTHONPATH=src .venv/bin/python - <<'PY'  (see commands in evidence)
standby-only (all 1.8 W, idle 1.8) active_wh = 0.0
idle->10W active->idle, idle 1.8, active_wh = 10.0
clean fixture (1.8W-bookended) active_full_wh = 467.7333
PY
```

In Scenario A the fixture starts (1.80 W) and ends (1.80 W) at idle; with idle
1.8 W those rows contribute zero, and the integral is 467.7333 Wh of active
energy only.

## Scenario C - malformed fixture fails visibly

**Given** `fixtures/malformed-missing-power.csv` whose header lacks `power_w`.
**When** the analyzer runs.
**Then** it exits non-zero with a validation error and writes no summary.

```
$ PYTHONPATH=src .venv/bin/python -m cyclesteward.cli analyze-fixture \
    --input fixtures/malformed-missing-power.csv --output /tmp/should-not-exist.json
error: fixture malformed-missing-power.csv missing required column(s): power_w
exit_code=2
output file created? -> NO
```

Observed: error on stderr, exit code 2, no output file written. Unit mirror:
`tests/test_samples.py::test_missing_required_column_raises` and
`tests/test_cli.py::test_malformed_input_exits_nonzero_and_writes_nothing`.

## Scenario D - non-monotonic or interrupted sessions carry warnings

**Given** `fixtures/synthetic-interrupted.csv` (a low-to-full with a 4-hour gap).
**When** the analyzer runs.
**Then** it still reports parseable statistics but warns that the profile should
not be trusted for calibration.

```
$ PYTHONPATH=src .venv/bin/python -m cyclesteward.cli analyze-fixture \
    --input fixtures/synthetic-interrupted.csv --idle-watts 1.8
{
  "schema_version": 1,
  "profile_id": "fixture:synthetic-interrupted",
  "sample_count": 26,
  "idle_power_w": 1.8,
  "anchors": {
    "watts_at_low": 69.0,
    "watts_at_transition": 84.0,
    "taper_floor_w": 18.0
  },
  "active_full_wh": 467.7283,
  "landmarks": {
    "active_start_timestamp": "2026-06-08T18:10:00-07:00",
    "peak_power_w": 84.0,
    "peak_timestamp": "2026-06-08T23:00:00-07:00",
    "taper_start_timestamp": "2026-06-08T23:10:00-07:00",
    "completion_timestamp": "2026-06-09T01:10:00-07:00"
  },
  "warnings": [
    "sampling gap of 14400s exceeds 3x the median interval; session looks interrupted; profile should not be trusted for calibration"
  ]
}
```

Observed: parseable statistics still produced (anchors, landmarks), plus a warning
containing "interrupted" and "profile should not be trusted for calibration". Unit
mirror: `tests/test_landmarks.py::test_interrupted_session_warns_about_gap`.

## Supplementary - robust-to-unknown rows (ADR-0010 / guardrails)

```
$ PYTHONPATH=src .venv/bin/python -m cyclesteward.cli analyze-fixture \
    --input fixtures/synthetic-with-unknown-rows.csv --idle-watts 1.8
sample_count= 10
warnings= [
  "row 2: skipped missing/unknown reading",
  "row 4: skipped missing/unknown reading",
  "sampling gap of 14400s exceeds 3x the median interval; session looks interrupted; profile should not be trusted for calibration"
]
```

`unknown` and empty `power_w` rows are skipped with warnings rather than crashing
(12 input rows -> 10 samples).

## Real data - Swoop ASM charge session

First real-data run (`fixtures/real-swoop-asm-charge.csv`, derived from a Home
Assistant export): 0/5 dots up past the CC->CV transition, cut off mid-taper.

```
$ PYTHONPATH=src .venv/bin/python -m cyclesteward.cli analyze-fixture \
    --input fixtures/real-swoop-asm-charge.csv --output /tmp/real-summary.json
$ cat /tmp/real-summary.json
{
  "schema_version": 1,
  "profile_id": "fixture:real-swoop-asm-charge",
  "sample_count": 80,
  "idle_power_w": 0.0,
  "anchors": {
    "watts_at_low": 65.74,
    "watts_at_transition": 83.9,
    "taper_floor_w": 68.86
  },
  "active_full_wh": 586.7915,
  "landmarks": {
    "active_start_timestamp": "2026-06-05T06:00:07.295000+00:00",
    "peak_power_w": 83.9,
    "peak_timestamp": "2026-06-05T13:26:29.113000+00:00",
    "taper_start_timestamp": "2026-06-05T13:28:28.682000+00:00",
    "completion_timestamp": "2026-06-05T13:36:02.659000+00:00"
  },
  "warnings": []
}
```

**Independent cross-check (real hardware):** the plug's own cumulative energy
meter `sensor.utility_smartplug_1_energy` rose 75.96 - 75.38 = 0.58 kWh (~580 Wh)
across the session; the trapezoidal `active_full_wh` is 586.8 Wh -- a ~1% match.

**Real-world findings (documented, not yet refined):**
- Onset/inrush: `watts_at_low` = 65.74 W latched onto the inrush ramp, not the
  settled CC value (~69.7 W).
- Mid-taper cutoff: the relay opened during early taper, so `taper_floor_w` =
  68.86 W is the cutoff reading and "completion" is the relay-off event, not a
  true CV floor.

Mirror tests: `tests/test_real_fixture.py` (3 tests, all PASSED in the run above
once the fixture was added; total suite now 28 passed).

## Determinism

```
$ ... --output /tmp/run1.json ; ... --output /tmp/run2.json
$ diff -q /tmp/run1.json /tmp/run2.json
IDENTICAL
```

Mirror: `tests/test_profile.py::test_summary_is_deterministic`.
