# profile-calibration-evidence.md

Slice: scenarios A, A2, B, C, D, E  
Date: 2026-06-09  
Command: `.venv/bin/pytest tests/test_calibration.py -v` (21 passed, 0 failed)  
Full suite: `49 passed` — no regressions  
Lint: `ruff check .` — all checks passed

---

## Scenario A — display-empty to full calibration stores the wattage anchors

Input: `fixtures/synthetic-low-to-full.csv`, `idle_power_w=1.8`, `rated_capacity_wh=500`.

Profile JSON after `ingest_full_session(soc_at_start=display_empty)`:

```json
{
  "schema_version": 1,
  "charger_label": "test-charger",
  "battery_label": "test-battery",
  "meter_id": "sensor.test_power",
  "rated_capacity_wh": 500.0,
  "state": "calibrated",
  "idle_power_w": 1.8,
  "watts_at_low": {
    "watts": 69.0,
    "assumed_soc_label": "display_empty",
    "confidence": "high"
  },
  "watts_at_transition": {
    "watts": 84.0,
    "assumed_soc_label": "cc_cv_transition",
    "confidence": "high"
  },
  "taper_floor_w": 18.0,
  "active_full_wh": 467.7333,
  "full_observations": [
    {
      "timestamp": "2026-06-09T12:00:00+00:00",
      "active_wh": 467.7333,
      "watts_at_low": 69.0,
      "watts_at_transition": 84.0,
      "trusted": true,
      "soc_at_start": {
        "label": "display_empty",
        "interval_low_pct": 0.0,
        "interval_high_pct": 15.0,
        "coarse": true
      },
      "quality_flags": []
    }
  ],
  "warnings": []
}
```

State is `calibrated`, observation is `trusted: true`, `quality_flags` is empty. ✓

---

## Scenario A2 — active Wh locates the target wattage

Same profile, `SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)`:

```
target_wattage(80.0) = 84.000 W   ← equals watts_at_transition (80% = transition assumption)
target_wattage(40.0) = 76.500 W   ← midpoint interpolation: 69 + 0.5 * 15 = 76.5  (tested: 40% is midpoint of 0–80)
target_wattage( 0.0) = 69.000 W   ← equals watts_at_low
```

A wattage threshold is recorded for 80% cutoff so the runtime uses a wattage
comparison, not an integrated-Wh target. ✓

---

## Scenario B — zero dots is not true zero percent

```python
SocReport.from_dots(0, 5)
  → label="0 of 5 dots", interval_low_pct=0.0, interval_high_pct=20.0, coarse=True

SocReport.from_dots(3, 5)
  → label="3 of 5 dots", interval_low_pct=60.0, interval_high_pct=80.0, coarse=True

SocReport.display_empty()
  → label="display_empty", interval_low_pct=0.0, interval_high_pct=15.0, coarse=True
```

All reports carry `coarse=True` and an interval `[low, high)` with positive
width. Neither zero dots nor display_empty is stored as exact 0%. ✓

---

## Scenario C — partial observation refines but does not overwrite

Same profile (state=calibrated, `active_full_wh=467.7333`) after ingesting a
partial session from `3 of 5 dots`:

```json
{
  "state": "calibrated",
  "active_full_wh": 467.7333,
  "partial_observations": [
    {
      "timestamp": "2026-06-10T09:00:00+00:00",
      "active_wh": 465.7917,
      "soc_at_start": {
        "label": "3 of 5 dots",
        "interval_low_pct": 60.0,
        "interval_high_pct": 80.0,
        "coarse": true
      }
    }
  ]
}
```

`active_full_wh` is unchanged at `467.7333`; state remains `calibrated`;
partial is recorded separately with its coarse `SocReport`. ✓

---

## Scenario D — bad sample data is rejected for calibration

Input: `fixtures/synthetic-interrupted.csv` — produces a sampling-gap warning
containing `CALIBRATION_DISTRUST`.

```
state: calibrating
warnings: ['session not trusted for calibration: sampling gap of 14400s exceeds
  3x the median interval; session looks interrupted; profile should not be
  trusted for calibration']
full_observations[0].trusted: False
full_observations[0].quality_flags: ['sampling gap of 14400s exceeds 3x the
  median interval; session looks interrupted; profile should not be trusted
  for calibration']
```

State is `calibrating`, not `calibrated`. Anchors remain `None`. The
observation is stored but marked `trusted: false` with the quality flag
preserved verbatim. ✓

---

## Scenario E — rated capacity yields an overhead estimate

From the full-calibration JSON above:

```json
"overhead": {
  "ratio": 0.9355,
  "rated_capacity_wh": 500.0,
  "measured_full_wh": 467.7333,
  "confidence": "low",
  "note": "nominal rated capacity; derived overhead carries uncertainty"
}
```

`ratio = 467.7333 / 500.0 = 0.9355`.  
`confidence` is `"low"` (rated capacity is nominal, not guaranteed).  
The uncertainty note is present in the JSON. ✓

---

## Test run output (raw)

```
tests/test_calibration.py::test_soc_report_from_dots_is_coarse PASSED
tests/test_calibration.py::test_soc_report_from_dots_spans_a_range PASSED
tests/test_calibration.py::test_soc_report_from_dots_mid_range PASSED
tests/test_calibration.py::test_soc_report_display_empty_is_coarse PASSED
tests/test_calibration.py::test_full_calibration_stores_wattage_anchors PASSED
tests/test_calibration.py::test_full_calibration_json_has_expected_shape PASSED
tests/test_calibration.py::test_initial_state_is_uncalibrated PASSED
tests/test_calibration.py::test_target_wattage_80pct_equals_transition_when_assumptions_match PASSED
tests/test_calibration.py::test_target_wattage_interpolates_midpoint PASSED
tests/test_calibration.py::test_target_wattage_at_low_anchor PASSED
tests/test_calibration.py::test_target_wattage_returns_none_when_uncalibrated PASSED
tests/test_calibration.py::test_partial_does_not_overwrite_active_full_wh PASSED
tests/test_calibration.py::test_partial_soc_report_stored_as_coarse PASSED
tests/test_calibration.py::test_partial_appears_in_json PASSED
tests/test_calibration.py::test_interrupted_session_not_trusted PASSED
tests/test_calibration.py::test_untrusted_session_leaves_anchors_unset PASSED
tests/test_calibration.py::test_bad_session_transitions_to_calibrating PASSED
tests/test_calibration.py::test_quality_flags_recorded_in_observation PASSED
tests/test_calibration.py::test_rated_capacity_yields_overhead_estimate PASSED
tests/test_calibration.py::test_no_overhead_when_rated_capacity_not_set PASSED
tests/test_calibration.py::test_overhead_in_json_carries_uncertainty_note PASSED

21 passed in 1.39s
```
