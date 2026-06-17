# Stale-meter guardrail — BDD evidence

Paired with [stale-meter-guardrail-bdd.md](stale-meter-guardrail-bdd.md) and
[docs/specs/stale-meter-guardrail.md](../../docs/specs/stale-meter-guardrail.md).

Run date: 2026-06-16. Raw outputs below (not summaries).

## Design grounding: why no cadence heuristic (decision D1)

The packet's original framing assumed staleness could be inferred from
time-since-last-update. Gap analysis of the one real session refutes that — the
meter reports on change, so it legitimately goes quiet for minutes during the CV
plateau:

```
REAL-DATA GAP ANALYSIS (fixtures/real-swoop-asm-charge.csv)
  samples=80 median_gap=365s p90=464s max_gap=788s
  gaps>=300s: 63/79   gaps>=600s: 4/79
```

Reproduce the figures from the raw CSV:

```bash
PYTHONPATH=src .venv/bin/python -c "import csv,statistics as st; from datetime import datetime; \
ts=[datetime.fromisoformat(r['timestamp'].replace('Z','+00:00')) for r in csv.DictReader(open('fixtures/real-swoop-asm-charge.csv'))]; \
g=[(ts[i]-ts[i-1]).total_seconds() for i in range(1,len(ts))]; \
print(f'samples={len(ts)} median={st.median(g):.0f}s p90={sorted(g)[int(len(g)*0.9)]:.0f}s max={max(g):.0f}s ge300={sum(x>=300 for x in g)}/{len(g)} ge600={sum(x>=600 for x in g)}/{len(g)}')"
# samples=80 median=365s p90=464s max=788s ge300=63/79 ge600=4/79
```

The median quiet window (365 s) already exceeds the originally-proposed 300 s
staleness threshold, and power is flat across the long gaps (e.g. 74.4 → 74.7 W
over 788 s), so a frozen value is indistinguishable from a healthy plateau. The
guardrail therefore faults only on genuine unavailability (`None`) while CHARGING,
threshold 1800 s — clearing the 788 s max healthy quiet window by ~2.3×.

## Scenario C — prolonged blindness while charging → STALE_METER fault (anchor)

Anchor artifact `stale-meter-guardrail-trace.json`, fault leg, read back from disk:

```json
"expected": {
  "fault_leg_fault": "stale_meter",
  "fault_leg_fault_timestamp": "2026-01-01T00:31:00+00:00",
  "fault_leg_final_state": "faulted",
  "fault_leg_event_log": [
    "guardrail/stale_meter: meter blind 1800 s while charging (1800 s without a reading)"
  ],
  "recovery_leg_fault": null,
  "recovery_leg_final_state": "charging"
}
```

The faulting tick (T0 + 1860 s = 00:31:00, blind run started at +60 s):

```json
{
  "timestamp": "2026-01-01T00:31:00+00:00",
  "power_w": null,
  "action": "turn_off",
  "state": "faulted",
  "soc_estimate": null,
  "reason": "meter blind 1800 s while charging (1800 s without a reading)",
  "fault": "stale_meter"
}
```

`action=turn_off`, `state=faulted`, `fault=stale_meter`, and the `event_log`
records `guardrail/stale_meter`. The charge fails safe; the OEM charger/BMS
remains the battery-safety layer.

## Scenario A / D — recovery before threshold clears the blind-run clock

Anchor `recovery_leg` ends `charging` with `recovery_leg_fault: null` (above). The
unit test `test_D_recovery_before_threshold_clears_clock` further proves a numeric
reading clears the clock and a *fresh* blind run must accrue the full 1800 s again
(no carry-over):

```
tests/test_stale_meter_guardrail.py::test_D_recovery_before_threshold_clears_clock PASSED
tests/test_stale_meter_guardrail.py::test_C_no_fault_just_below_threshold PASSED
```

## Scenario B — meter goes dark: hold safely + observability breadcrumbs

Live watcher driven through numeric → `None` → numeric transitions (events
captured off the HA bus mock):

```
  t+   0s power= 80.0  state=charging   events=['session_start']
  t+  60s power= None  state=charging   events=['session_start', 'meter_unavailable']
  t+ 120s power= None  state=charging   events=['session_start', 'meter_unavailable']
  t+ 300s power= 85.0  state=charging   events=['session_start', 'meter_unavailable', 'meter_recovered']
  t+ 360s power= None  state=charging   events=['session_start', 'meter_unavailable', 'meter_recovered', 'meter_unavailable']
  t+ 420s power= 90.0  state=charging   events=['session_start', 'meter_unavailable', 'meter_recovered', 'meter_unavailable', 'meter_recovered']
```

`meter_unavailable` fires once on the numeric → `None` transition (not repeated at
t+120 while still blind), `meter_recovered` once on resume; the core holds
`charging` throughout (no cutoff misfire, no Wh accrual). The latch is verified by
`test_watcher_fires_meter_unavailable_once_on_transition`.

## Edge — blindness outside CHARGING never faults

`test_blindness_outside_charging_does_not_fault`: `None` power in IDLE for up to
4000 s never starts the blind-run clock and never faults.

## Full test run

```
tests/test_stale_meter_guardrail.py::test_evaluator_no_fault_below_threshold PASSED
tests/test_stale_meter_guardrail.py::test_evaluator_faults_at_threshold PASSED
tests/test_stale_meter_guardrail.py::test_evaluator_measures_wall_clock_not_tick_count PASSED
tests/test_stale_meter_guardrail.py::test_evaluator_recovery_clears_blind_run PASSED
tests/test_stale_meter_guardrail.py::test_evaluator_reset_clears_blind_run PASSED
tests/test_stale_meter_guardrail.py::test_C_charging_blind_faults_after_threshold PASSED
tests/test_stale_meter_guardrail.py::test_C_event_log_records_stale_meter_fault PASSED
tests/test_stale_meter_guardrail.py::test_C_no_fault_just_below_threshold PASSED
tests/test_stale_meter_guardrail.py::test_D_recovery_before_threshold_clears_clock PASSED
tests/test_stale_meter_guardrail.py::test_blindness_outside_charging_does_not_fault PASSED
tests/test_stale_meter_guardrail.py::test_watcher_fires_meter_unavailable_once_on_transition PASSED
tests/test_stale_meter_guardrail.py::test_watcher_fires_meter_recovered_on_resume PASSED
tests/test_stale_meter_guardrail.py::test_generate_stale_meter_trace PASSED

============================== 13 passed in 0.04s ==============================
```

Whole suite: `279 passed`; `ruff check .` → `All checks passed!`.
