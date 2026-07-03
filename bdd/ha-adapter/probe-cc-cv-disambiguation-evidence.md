# Probe CC/CV Disambiguation — BDD Evidence

**Run date:** 2026-07-03
**Packet:** 5 / F7
**Test command:** `python3 -m pytest tests/test_probe_cc_cv_disambiguation.py tests/test_session_control.py -v`
**Full suite command:** `python3 -m pytest tests/ -q`
**Full suite result:** 302 passed

---

## Scenario A — Probe classifies CC phase: wattage flat, start time updated

**Given:** `HASensorWatcher` with calibrated profile (watts_at_low=60 W, watts_at_transition=80 W), target_finish_time set 8 h ahead, CHARGE_TO_TARGET mode, WAITING_FOR_SCHEDULE state.

**When:** Watcher enters PROBING (probe fires at probe_time). Receives 3 flat power readings: [65.0, 66.0, 65.0] W at 10 s intervals.

**Then (observed from anchor trace `bdd/ha-adapter/probe-cc-cv-disambiguation-trace.json` — cc_probe leg):**

```json
"probe_result_event": {
  "event": "probe_result",
  "reason": "probe complete: CC phase; SoC ~20%; start time updated",
  "classification": "cc",
  "soc_estimate_pct": 20.0,
  "uncertainty_pct": 10.0,
  "computed_start_time": "2026-01-02T03:18:00+00:00"
}
```

- `pessimistic_start_time`: `2026-01-02T00:54:00+00:00`
- `computed_start_time_after`: `2026-01-02T03:18:00+00:00` ← later than pessimistic ✓
- State after 3rd sample: `waiting_for_schedule` ✓

**Test output (pytest -v):**
```
tests/test_probe_cc_cv_disambiguation.py::TestCCProbeClassification::test_cc_probe_concludes_after_min_samples PASSED
tests/test_probe_cc_cv_disambiguation.py::TestCCProbeClassification::test_cc_probe_updates_computed_start_time_later PASSED
tests/test_probe_cc_cv_disambiguation.py::TestCCProbeClassification::test_cc_probe_fires_event_with_classification_field PASSED
tests/test_probe_cc_cv_disambiguation.py::TestCCProbeClassification::test_cc_probe_samples_cleared_after_conclusion PASSED
```

---

## Scenario B — Probe classifies CV taper: wattage falling, start time pushed late

**Given:** Same watcher configuration as Scenario A.

**When:** Watcher enters PROBING. Receives 3 falling power readings: [78.0, 65.0, 50.0] W at 10 s intervals. Ratio: last_mean (50.0) / first_mean (78.0) = 0.641 < 0.90 → CV taper.

**Then (observed from anchor trace — cv_taper_probe leg):**

```json
"probe_result_event": {
  "event": "probe_result",
  "reason": "probe complete: CV taper detected; battery near-full; start time pushed late",
  "classification": "cv_taper",
  "first_mean_w": 78.0,
  "last_mean_w": 50.0,
  "computed_start_time": "2026-01-02T06:30:00+00:00"
}
```

- `target_finish_time`: `2026-01-02T07:00:00+00:00`
- `margin_s`: 1800.0
- `computed_start_time_after`: `2026-01-02T06:30:00+00:00` = target − margin ✓
- State after 3rd sample: `waiting_for_schedule` ✓

**Test output (pytest -v):**
```
tests/test_probe_cc_cv_disambiguation.py::TestCVTaperProbeClassification::test_cv_taper_probe_concludes_after_min_samples PASSED
tests/test_probe_cc_cv_disambiguation.py::TestCVTaperProbeClassification::test_cv_taper_probe_pushes_start_time_to_target_minus_margin PASSED
tests/test_probe_cc_cv_disambiguation.py::TestCVTaperProbeClassification::test_cv_taper_probe_fires_event_with_classification_and_means PASSED
```

---

## Scenario C — Insufficient probe samples: falls back to timeout behavior

**Given:** Watcher with max_probe_seconds=30.0, meter unavailable (all `None` readings).

**When:** 4 `None` ticks sent across the probe window; controller times out at 30 s.

**Then (observed from anchor trace `bdd/ha-adapter/probe-cc-cv-disambiguation-trace.json` — probe_timeout leg):**

```json
"probe_result_event": {
  "event": "probe_result",
  "reason": "probe timeout: insufficient samples; using pessimistic start time",
  "computed_start_time": "2026-01-02T00:54:00+00:00"
}
```

- No `classification` field in probe_result event ✓
- `computed_start_time_after == pessimistic_start_time` (`"2026-01-02T00:54:00+00:00"`) ✓
- State returns to `waiting_for_schedule` ✓

**Test output (pytest -v):**
```
tests/test_probe_cc_cv_disambiguation.py::TestInsufficientSamplesTimeout::test_timeout_with_no_samples_uses_pessimistic PASSED
tests/test_probe_cc_cv_disambiguation.py::TestInsufficientSamplesTimeout::test_timeout_with_enough_samples_classifies PASSED
```

Note: `test_timeout_with_enough_samples_classifies` is a robustness edge-case test (not a named BDD scenario): it verifies that if `_probe_samples` has been populated by the time the controller timeout fires, classification still runs rather than silently discarding the accumulated data. This handles the race where the timer and the last sample arrive on the same tick.

**`_classify_probe_trend` unit tests (pytest -v):**
```
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_returns_none_when_insufficient_samples PASSED
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_returns_none_when_below_min_samples PASSED
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_flat_wattage_classified_as_cc PASSED
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_rising_wattage_classified_as_cc PASSED
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_falling_wattage_classified_as_cv_taper PASSED
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_small_drop_within_ratio_still_cc PASSED
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_drop_just_below_ratio_is_cv_taper PASSED
tests/test_probe_cc_cv_disambiguation.py::TestClassifyProbeTrend::test_zero_first_mean_returns_cc PASSED
```

---

## Scenario D — SoC latch during CHARGE_TO_FULL taper

**Given:** `SessionController` in CHARGE_TO_FULL mode, calibrated profile (watts_at_low=60, watts_at_transition=80, taper_floor_w=10 W). Session built peak SoC of 60.0% from 75 W reading (60 = (75−60)/(80−60)×80).

**When:** Wattage drops below taper_floor (8 W → taper starts), then continues falling (5 W, 3 W), then taper duration met (60 s elapsed).

**Then (observed from anchor trace — soc_latch leg):**

Tick at 12:01:00 (75 W, pre-taper):
```json
{"power_w": 75.0, "state": "charging", "soc_estimate": {"estimated_soc_pct": 60.0, "low_confidence": false, "note": ""}, "note": "peak SoC 60.0"}
```

Tick at 12:02:00 (8 W, taper start — latch arms):
```json
{"power_w": 8.0, "state": "charging", "soc_estimate": {"estimated_soc_pct": 60.0, "uncertainty_pct": 10.0, "low_confidence": true, "note": "taper phase: SoC held at session max"}, "note": "taper start; latch armed"}
```

Tick at 12:02:30 (5 W, falling — latch holds):
```json
{"power_w": 5.0, "state": "charging", "soc_estimate": {"estimated_soc_pct": 60.0, "low_confidence": true, "note": "taper phase: SoC held at session max"}, "note": "falling wattage; latch holds"}
```

Tick at 12:03:01 (3 W, cutoff):
```json
{"power_w": 3.0, "action": "turn_off", "state": "done_latched_off", "soc_estimate": {"estimated_soc_pct": 60.0, "low_confidence": true, "note": "taper phase: SoC held at session max"}, "note": "taper duration met; cutoff"}
```

- SoC held at 60.0% across all taper ticks (not computed from 8/5/3 W) ✓
- `low_confidence: true` ✓
- `note` contains `"taper phase: SoC held at session max"` ✓
- Session transitions to `done_latched_off` ✓
- After `set_mode()`, latch clears and next session computes SoC from wattage ✓

**Test output (pytest -v):**
```
tests/test_session_control.py::test_soc_latch_holds_at_session_max_when_taper_begins PASSED
tests/test_session_control.py::test_soc_latch_does_not_count_down_during_taper PASSED
tests/test_session_control.py::test_soc_latch_clears_after_set_mode PASSED
tests/test_session_control.py::test_soc_latch_skipped_when_no_calibrated_soc PASSED
tests/test_session_control.py::test_soc_latch_present_at_done_latched_off PASSED
```

---

## Anchor artifact

`bdd/ha-adapter/probe-cc-cv-disambiguation-trace.json` — written and verified by `test_generate_probe_cc_cv_disambiguation_trace`:

```
tests/test_probe_cc_cv_disambiguation.py::test_generate_probe_cc_cv_disambiguation_trace PASSED
```

Verified on disk:
- CC leg: `classification == "cc"`, `computed_start_time_after >= pessimistic_start_time` ✓
- CV leg: `classification == "cv_taper"`, `computed_start_time_after == target − margin` ✓
- Latch leg: `"taper phase"` in note at latch tick, same SoC held at done_latched_off ✓
