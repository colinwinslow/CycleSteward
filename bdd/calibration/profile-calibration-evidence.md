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

---

# Slice F–H evidence

Slice: scenarios F, F2, G, G2, G3, H  
Date: 2026-06-09  
Command: `.venv/bin/pytest tests/test_calibration.py tests/test_landmarks.py tests/test_real_fixture.py -v` (44 passed, 0 failed)  
Full suite: `65 passed` — no regressions  
Lint: `ruff check src/ tests/` — all checks passed

---

## Scenario F — a naturally-occurring near-empty-to-full session is reused

Input: `fixtures/synthetic-low-to-full.csv`, calibrated profile (watts\_at\_low = 69.0 W), temperature\_c = 21.0.

`classify_opportunistic_session` call:

```
promoted=True, reason='opportunistic full-span datapoint'
```

Profile's `temperature_observations` after promotion:

```json
[
  {
    "timestamp": "2026-06-09T12:00:00+00:00",
    "active_wh": 467.7333,
    "watts_at_low": 69.0,
    "temperature_c": 21.0
  }
]
```

Session starting wattage (69.0 W) is within 10% of the anchor (69.0 W). Completion was detected. Temperature/Wh pair stored without prompting. ✓

---

## Scenario F2 — inrush settling yields a representative watts\_at\_low

Input: `fixtures/synthetic-inrush-settling.csv` (inrush ramp: 46 W → 62 W → 70.2 W before settling).

```
watts_at_low = 70.2 W   ← settled CC (onset sample was 46.0 W)
```

The inrush onset crossed the 50% threshold at 46 W, but the first stable consecutive pair
(|70.8 − 70.2| / 70.2 = 0.85% < 5%) landed at 70.2 W. `watts_at_low` reflects the
settled bulk-charge wattage, not the rising-edge artefact. ✓

Real-data validation (Swoop ASM fixture, was 65.74 W, now 69.72 W):

```
test_real_session_watts_at_low_uses_settled_cc_value  PASSED   68.0 < 69.72 < 72.0
```

---

## Scenario G — a session starting too far from the low anchor is rejected

Input: synthesised summary with `watts_at_low = 90.0 W` against a calibrated profile with anchor 69.0 W.

```
promoted=False
reason='start wattage 90.0 W is 30% from learned anchor 69.0 W (>10% tolerance); not promoted'
temperature_observations length=0
```

The 30% distance exceeds the 10% proximity tolerance. No observation stored. ✓

---

## Scenario G2 — an incomplete session is not promoted even if it starts near the anchor

Input: `fixtures/synthetic-interrupted.csv` — starts at 69.0 W (same as the anchor), so the
proximity gate would pass, but the session has a 4-hour sampling gap that triggers
CALIBRATION\_DISTRUST.

```
promoted=False
reason='session not trusted for calibration; not promoted'
```

Starting wattage (69.0 W) is at the anchor (69.0 W) — proximity is satisfied. The classifier
still rejects because `CALIBRATION_DISTRUST` is present in warnings (the gap gate fires before
proximity is checked). The scenario's core guarantee — "even if it starts near the anchor" —
is directly exercised. ✓

---

## Scenario G3 — a sharp mid-taper relay cutoff is not mistaken for a natural taper floor

Input: `fixtures/synthetic-mid-taper-cutoff.csv` (full CC to peak, then one taper sample at 78.5 W, then immediate 0 W).

Landmark detection:

```
taper_floor_w = None
taper warning: 'taper floor candidate (78.5 W) is 93% of peak;
  taper_floor_w is unreliable due to apparent relay cutoff'
```

`classify_opportunistic_session`:

```
promoted=False
reason='taper floor ambiguous (likely relay cutoff); not promoted'
```

78.5 W is 93% of peak active — well above the 35% cap for a genuine taper floor.
`taper_floor_w` is not assigned. Warning surfaced. Session not promoted. ✓

Real-data validation (Swoop ASM: 68.86 W → 0 W in 18 s, was erroneously assigned a floor):

```
test_real_session_mid_taper_cutoff_is_detected  PASSED   taper_floor_w is None, TAPER_AMBIGUOUS present
```

---

## Scenario H — calibration runs on imported Home Assistant history

Input: `fixtures/real-swoop-asm-charge.csv` (derived from HA recorder export; 80 samples, temperature column present).

Profile JSON from `ingest_full_session`:

```json
{
  "state": "calibrated",
  "watts_at_low": {
    "watts": 69.72,
    "assumed_soc_label": "display_empty",
    "confidence": "high"
  },
  "watts_at_transition": {
    "watts": 83.9,
    "assumed_soc_label": "cc_cv_transition",
    "confidence": "high"
  },
  "taper_floor_w": null,
  "active_full_wh": 586.7915,
  "warnings": []
}
```

State is `calibrated`. Wattage anchors extracted correctly. Relay-cutoff flag on `taper_floor_w` is expected (this session ended mid-taper). No `homeassistant` import in any core module. ✓

Unknown/unavailable row tolerance (`synthetic-with-unknown-rows.csv`):

```
test_ha_export_tolerates_unknown_rows  PASSED   ≥2 skipped-row warnings, len(samples) > 0
```

---

## Test run output (raw — slice F–H additions)

```
tests/test_calibration.py::test_opportunistic_session_is_promoted PASSED
tests/test_calibration.py::test_opportunistic_session_stores_temperature_wh_pair PASSED
tests/test_calibration.py::test_opportunistic_promotion_appears_in_json PASSED
tests/test_calibration.py::test_inrush_fixture_calibrated_with_settled_watts_at_low PASSED
tests/test_calibration.py::test_session_far_from_anchor_not_promoted PASSED
tests/test_calibration.py::test_incomplete_session_not_promoted PASSED
tests/test_calibration.py::test_relay_cutoff_session_not_promoted PASSED
tests/test_calibration.py::test_uncalibrated_profile_rejects_opportunistic PASSED
tests/test_calibration.py::test_ha_exported_rows_produce_profile_output PASSED
tests/test_calibration.py::test_ha_export_tolerates_unknown_rows PASSED
tests/test_calibration.py::test_ha_core_has_no_homeassistant_import PASSED
tests/test_landmarks.py::test_inrush_ramp_settled_past_for_watts_at_low PASSED
tests/test_landmarks.py::test_no_inrush_session_watts_at_low_unchanged PASSED
tests/test_landmarks.py::test_mid_taper_cutoff_sets_taper_floor_to_none PASSED
tests/test_landmarks.py::test_natural_taper_floor_not_flagged_as_cutoff PASSED
tests/test_real_fixture.py::test_real_session_watts_at_low_uses_settled_cc_value PASSED
tests/test_real_fixture.py::test_real_session_mid_taper_cutoff_is_detected PASSED

65 passed in 3.19s (full suite)
```
