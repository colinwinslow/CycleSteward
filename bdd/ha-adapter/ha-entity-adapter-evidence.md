# Home Assistant entity adapter — BDD evidence

Paired with
[ha-entity-adapter-bdd.md](ha-entity-adapter-bdd.md).

## Test run

```
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/colinwinslow/Documents/GitHub/CycleSteward
configfile: pyproject.toml

tests/test_ha_coordinator.py::test_A_mode_set_triggers_charging PASSED   [  8%]
tests/test_ha_coordinator.py::test_B_mode_off_returns_idle PASSED        [ 16%]
tests/test_ha_coordinator.py::test_C_wattage_cutoff_done_latched_off PASSED [ 25%]
tests/test_ha_coordinator.py::test_D_session_state_reflects_controller PASSED [ 33%]
tests/test_ha_coordinator.py::test_E_charge_mode_reflects_controller PASSED [ 41%]
tests/test_ha_coordinator.py::test_F_morning_reset_clears_mode PASSED    [ 50%]
tests/test_ha_coordinator.py::test_G_guardrail_fault_propagates PASSED   [ 58%]
tests/test_ha_coordinator.py::test_H_soc_estimate_in_charging_tick PASSED [ 66%]
tests/test_ha_coordinator.py::test_I_listener_notified_on_tick_and_mode_change PASSED [ 75%]
tests/test_ha_coordinator.py::test_J_unsubscribe_stops_notifications PASSED [ 83%]
tests/test_ha_coordinator.py::test_anchor_artifact_written PASSED        [ 91%]
tests/test_ha_coordinator.py::test_ha_entity_files_syntactically_valid PASSED [100%]

12 passed in 0.06s
```

Note: `test_anchor_artifact_written` and `test_ha_entity_files_syntactically_valid` are
infrastructure tests (artifact generation + syntax check) not mapped to a named BDD
scenario; they are included in this test file for completeness.  The 10 named scenario
tests cover BDD scenarios A–J directly.

## Per-scenario evidence

### Scenario A — setting mode triggers charging on next tick

Asserted in `test_A_mode_set_triggers_charging`:
```python
assert result.action.value == "turn_on"
assert result.state == SessionState.CHARGING
assert basic_coordinator.session_state == SessionState.CHARGING
```
All three Then-conditions from the BDD exercised.

### Scenario B — setting mode to off returns to idle

Asserted in `test_B_mode_off_returns_idle`:
```python
assert basic_coordinator.charge_mode == ChargeMode.OFF
assert basic_coordinator.session_state == SessionState.IDLE
```
Coordinator was driven to CHARGING first (tick at 70 W), then set_mode(OFF) applied.

### Scenario C — wattage cutoff fires DONE_LATCHED_OFF

Asserted in `test_C_wattage_cutoff_done_latched_off`:
```python
assert r2.action.value == "turn_off"
assert r2.state == SessionState.DONE_LATCHED_OFF
assert calibrated_coordinator.session_state == SessionState.DONE_LATCHED_OFF
```
First tick confirmed CHARGING; second tick at 96 W (> 95 W threshold), 60 s later (> 30 s
min_dwell), fired the cutoff.  Anchor artifact corroborates at step "tick 3 — cutoff (96 W)".

### Scenario D — session_state property reflects controller state

Asserted in `test_D_session_state_reflects_controller`:
```python
assert basic_coordinator.session_state == SessionState.IDLE   # before mode set
assert basic_coordinator.session_state == SessionState.CHARGING  # after set_mode + tick
```

### Scenario E — charge_mode property reflects controller mode

Asserted in `test_E_charge_mode_reflects_controller`:
```python
assert basic_coordinator.charge_mode == ChargeMode.OFF         # at init
assert basic_coordinator.charge_mode == ChargeMode.CHARGE_TO_TARGET  # after set_mode
```

### Scenario F — morning reset clears mode to off

Asserted in `test_F_morning_reset_clears_mode`:
```python
assert result.reason == "morning reset: modes cleared"
assert coordinator.charge_mode == ChargeMode.OFF
assert coordinator.session_state == SessionState.IDLE
```
Coordinator configured with `morning_reset_time=06:00`; mode set to CHARGE_TO_TARGET;
tick at 06:01 fired the reset.

### Scenario G — guardrail fault surfaces in TickResult

Asserted in `test_G_guardrail_fault_propagates`:
```python
assert result.fault == GuardrailFault.MAX_RUNTIME
assert result.state == SessionState.FAULTED
assert coordinator.session_state == SessionState.FAULTED
```
`max_runtime_seconds=60`; session ran to T0+65 s.

### Scenario H — soc_estimate carried in TickResult during charging

Asserted in `test_H_soc_estimate_in_charging_tick`:
```python
assert result.soc_estimate is not None
assert isinstance(result.soc_estimate.uncertainty_pct, float)
assert isinstance(result.soc_estimate.low_confidence, bool)
assert calibrated_coordinator.soc_estimate is result.soc_estimate
```
Second charging tick at 75 W with calibrated profile (65–95 W ramp).  Anchor artifact
shows `"estimated_soc_pct": 34.7, "uncertainty_pct": 10.0, "low_confidence": false`.

### Scenario I — listener notified on tick and mode change

Asserted in `test_I_listener_notified_on_tick_and_mode_change`:
```python
assert calls == ["ping"]      # after set_mode only
assert calls == ["ping", "ping"]  # after set_mode + tick
```
Intermediate check after `set_mode` confirms exactly one call per operation.

### Scenario J — unsubscribe stops notifications

Asserted in `test_J_unsubscribe_stops_notifications`:
```python
assert calls == ["ping"]   # only the set_mode before unsub; tick after unsub silent
```

## Anchor artifact

`ha-entity-adapter-trace.json` written and verified by `test_anchor_artifact_written`:

```json
[
  {"step": "initial", "charge_mode": "off", "session_state": "idle"},
  {"step": "after set_mode(CHARGE_TO_TARGET)", "charge_mode": "charge_to_target", "session_state": "idle"},
  {"step": "tick 1 — turn on", ..., "action": "turn_on", "session_state": "charging"},
  {"step": "tick 2 — charging (78 W)", ..., "action": "none", "soc_estimate": {"estimated_soc_pct": 34.7, ...}},
  {"step": "tick 3 — cutoff (96 W)", ..., "action": "turn_off", "session_state": "done_latched_off"}
]
```

State sequence confirmed: `idle → idle → charging → charging → done_latched_off`.

## Architecture review

Verdict: CONCERNS (not blockers). Three items addressed before this evidence was written:

1. `SocEstimateSensor.extra_state_attributes` — replaced `None` sentinels with
   `uncertainty_pct: 100.0, low_confidence: True` so automations always receive
   machine-readable numerics (ADR-0004, ADR-0011 consequences).
2. `ManualOverrideSwitch._is_on` — marked with TODO comment as temporary shadow state
   pending `SessionController.manual_override_active` (scheduling slice).
3. `time.py _value` fields — marked with TODO comments for `SessionConfig` round-trip
   in scheduling slice.
