# Finish-Time Scheduling — BDD Evidence

**Run date:** 2026-06-12 23:41 UTC  
**Test file:** `tests/test_finish_time_scheduling.py`  
**Anchor artifact:** `bdd/ha-adapter/finish-time-scheduling-trace.json`  
**BDD file:** `bdd/ha-adapter/finish-time-scheduling-bdd.md`

---

## Raw pytest output (39 tests, 0 failures)

```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/colinwinslow/Documents/GitHub/CycleSteward

tests/test_finish_time_scheduling.py::TestProbingState::test_probing_in_session_state_enum PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_start_probe_transitions_waiting_to_probing PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_start_probe_returns_false_if_not_waiting PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_end_probe_transitions_probing_to_waiting PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_end_probe_returns_false_if_not_probing PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_probing_tick_returns_soc_estimate PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_probing_tick_timeout_returns_to_waiting PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_probing_accumulates_wh_for_energy_guardrail PASSED
tests/test_finish_time_scheduling.py::TestProbingState::test_probing_tick_with_no_power_stays_probing PASSED
tests/test_finish_time_scheduling.py::TestComputedStartTime::test_waiting_when_before_computed_start PASSED
tests/test_finish_time_scheduling.py::TestComputedStartTime::test_charging_when_at_computed_start PASSED
tests/test_finish_time_scheduling.py::TestComputedStartTime::test_computed_start_takes_precedence_over_scheduled_start PASSED
tests/test_finish_time_scheduling.py::TestComputedStartTime::test_none_computed_start_falls_back_to_scheduled_start PASSED
tests/test_finish_time_scheduling.py::TestSessionReason::test_waiting_reason_is_human_readable PASSED
tests/test_finish_time_scheduling.py::TestSessionReason::test_probing_reason_is_human_readable PASSED
tests/test_finish_time_scheduling.py::TestSessionReason::test_idle_reason_is_empty_or_mode_off PASSED
tests/test_finish_time_scheduling.py::TestSessionReason::test_charging_reason_non_empty PASSED
tests/test_finish_time_scheduling.py::TestLogbookEventHelper::test_fire_event_calls_hass_bus PASSED
tests/test_finish_time_scheduling.py::TestLogbookEventHelper::test_fire_event_includes_extra_fields PASSED
tests/test_finish_time_scheduling.py::TestProbeScheduling::test_pessimistic_start_time_with_no_observations PASSED
tests/test_finish_time_scheduling.py::TestProbeScheduling::test_probe_time_is_pessimistic_start_minus_headroom PASSED
tests/test_finish_time_scheduling.py::TestProbeScheduling::test_probe_fires_when_clock_reaches_probe_time PASSED
tests/test_finish_time_scheduling.py::TestProbeScheduling::test_probe_fires_only_once_per_cycle PASSED
tests/test_finish_time_scheduling.py::TestProbeScheduling::test_probe_timeout_fires_probe_result_with_failure PASSED
tests/test_finish_time_scheduling.py::TestProbeScheduling::test_no_target_finish_time_no_probe PASSED
tests/test_finish_time_scheduling.py::TestComputedStartTimeUpdate::test_successful_probe_updates_computed_start_time PASSED
tests/test_finish_time_scheduling.py::TestOverrunDetection::test_overrun_event_fired_when_charging_past_finish_time PASSED
tests/test_finish_time_scheduling.py::TestOverrunDetection::test_no_overrun_event_when_no_target_finish_time PASSED
tests/test_finish_time_scheduling.py::TestOverrunDetection::test_overrun_fires_only_once_per_session PASSED
tests/test_finish_time_scheduling.py::TestOverrunDetection::test_overrun_does_not_fault PASSED
tests/test_finish_time_scheduling.py::TestScenarioDSessionReason::test_waiting_reason_non_empty PASSED
tests/test_finish_time_scheduling.py::TestScenarioDSessionReason::test_probing_reason_non_empty PASSED
tests/test_finish_time_scheduling.py::TestScenarioDSessionReason::test_charging_reason_non_empty PASSED
tests/test_finish_time_scheduling.py::TestScenarioDSessionReason::test_done_latched_off_reason_non_empty PASSED
tests/test_finish_time_scheduling.py::TestScenarioDSessionReason::test_faulted_reason_non_empty PASSED
tests/test_finish_time_scheduling.py::TestScenarioDSessionReason::test_idle_reason_empty_before_first_tick PASSED
tests/test_finish_time_scheduling.py::TestScenarioFWaitingTransition::test_stays_waiting_before_computed_start PASSED
tests/test_finish_time_scheduling.py::TestScenarioFWaitingTransition::test_transitions_to_charging_at_computed_start PASSED
tests/test_finish_time_scheduling.py::TestScenarioFWaitingTransition::test_session_start_event_fired_on_charging_transition PASSED

============================== 39 passed in 0.09s ==============================
```

---

## Scenario coverage

### Scenario A — happy path: probe fires, SoC read, refined start → CHARGING → DONE_LATCHED_OFF

**Tests:**
- `TestProbeScheduling::test_probe_fires_when_clock_reaches_probe_time` — probe transitions to PROBING at probe_time; `probe_start` event fired
- `TestComputedStartTimeUpdate::test_successful_probe_updates_computed_start_time` — stable 90W reading ends probe; `computed_start_time` moves later than pessimistic; `probe_result` event contains `soc_estimate_pct` and `uncertainty_pct`
- `TestScenarioFWaitingTransition::test_transitions_to_charging_at_computed_start` — at `computed_start_time`, transitions WAITING_FOR_SCHEDULE → CHARGING with TURN_ON
- `TestScenarioDSessionReason::test_done_latched_off_reason_non_empty` — DONE_LATCHED_OFF state reached; `session_reason` non-empty

**Anchor trace excerpt** (`bdd/ha-adapter/finish-time-scheduling-trace.json`):
```json
"logbook_events": [
  {"event": "probe_start", "reason": "Probing: estimating SoC (<=5 min)"},
  {"event": "probe_result", "soc_estimate_pct": 30.8, "uncertainty_pct": 10.0, "computed_start_time": "..."},
  {"event": "session_start", "reason": "starting charge", "target_finish_time": "..."}
],
...
{"label": "probe_start",  "state": "probing", ...},
{"label": "probe_result", "state": "waiting_for_schedule", ...},
{"label": "charging_start", "state": "charging", "action": "turn_on"},
{"label": "cutoff",       "state": "done_latched_off", "action": "turn_off"}
```

### Scenario B — probe failure: fallback to pessimistic start time

**Tests:**
- `TestProbeScheduling::test_probe_timeout_fires_probe_result_with_failure` — probe starts; times out; `session_state == WAITING_FOR_SCHEDULE`; `watcher.computed_start_time == watcher._pessimistic_start_time()`; `probe_result` event with `"timeout"` in reason
- `TestProbeScheduling::test_probe_fires_only_once_per_cycle` — `_probe_fired` flag prevents re-trigger; call count doesn't increase after first probe

### Scenario C — no profile: pessimistic 4 h default drives probe_time

**Tests:**
- `TestProbeScheduling::test_pessimistic_start_time_with_no_observations` — `estimated_duration_s()` with no observations returns `(14400s, 2880s)` (4h ± 20%); `max_duration = 14400 + 2*2880 = 20160s`; `pessimistic_start = target − 20160 − 1800`; assert exact match
- `TestProbeScheduling::test_probe_time_is_pessimistic_start_minus_headroom` — `probe_time = pessimistic_start − 600s`; assert exact match

### Scenario D — session_reason non-empty on all non-idle states

**Tests:** `TestScenarioDSessionReason` (6 subtests):
- `WAITING_FOR_SCHEDULE` → `"Scheduled: waiting..."` non-empty ✓
- `PROBING` → `"Probing: estimating SoC..."` non-empty ✓
- `CHARGING` → `"starting charge"` non-empty ✓
- `DONE_LATCHED_OFF` → non-empty ✓
- `FAULTED` → triggered via `max_runtime_seconds=60`; `result.state == FAULTED`; `session_reason != ""` ✓
- `OFF_IDLE` (no tick) → `""` empty ✓

### Scenario E — overrun fires logbook event, doesn't fault

**Tests:**
- `TestOverrunDetection::test_overrun_event_fired_when_charging_past_finish_time` — `"overrun"` in fired events after ticking past target_finish_time
- `TestOverrunDetection::test_overrun_fires_only_once_per_session` — overrun count == 1 across 5 ticks past target
- `TestOverrunDetection::test_overrun_does_not_fault` — `session_state == CHARGING` and `active_fault is None` after overrun
- `TestOverrunDetection::test_no_overrun_event_when_no_target_finish_time` — no overrun without a target

### Scenario F — computed_start_time drives WAITING_FOR_SCHEDULE

**Tests:** `TestScenarioFWaitingTransition` (3 subtests):
- `now < computed_start_time` → stays `WAITING_FOR_SCHEDULE` ✓
- `now >= computed_start_time` → transitions to `CHARGING` with `TURN_ON` ✓
- `session_start` logbook event fired on WAITING → CHARGING transition ✓

---

## Architecture review result

0 invariant violations. 3 concerns addressed:
1. Energy accumulation during PROBING — `_guardrails.accumulate()` called in PROBING tick (verified by `test_probing_accumulates_wh_for_energy_guardrail`)
2. Uncertainty propagated in `probe_result` event — `uncertainty_pct` added to logbook event payload
3. Overrun fires only once — `_overrun_fired` flag added (verified by `test_overrun_fires_only_once_per_session`)
