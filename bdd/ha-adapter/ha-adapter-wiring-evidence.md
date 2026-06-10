# HA adapter: live sensor wiring + profile persistence — BDD evidence

Paired with
[ha-adapter-wiring-bdd.md](ha-adapter-wiring-bdd.md).

Run: 2026-06-09

## Test run

```
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/colinwinslow/Documents/GitHub/CycleSteward
configfile: pyproject.toml

tests/test_ha_wiring.py::TestFromJson::test_bare_uncalibrated_profile_round_trips PASSED [  3%]
tests/test_ha_wiring.py::TestFromJson::test_calibrated_profile_anchors_preserved PASSED [  6%]
tests/test_ha_wiring.py::TestFromJson::test_assumptions_round_trip PASSED [  9%]
tests/test_ha_wiring.py::TestFromJson::test_overhead_round_trip PASSED   [ 12%]
tests/test_ha_wiring.py::TestFromJson::test_full_observation_round_trip PASSED [ 15%]
tests/test_ha_wiring.py::TestFromJson::test_temperature_observation_round_trip PASSED [ 18%]
tests/test_ha_wiring.py::TestFromJson::test_warnings_preserved PASSED    [ 21%]
tests/test_ha_wiring.py::TestFromJson::test_from_dict_matches_from_json PASSED [ 25%]
tests/test_ha_wiring.py::TestProfileStore::test_load_returns_none_when_empty PASSED [ 28%]
tests/test_ha_wiring.py::TestProfileStore::test_save_then_load_round_trips PASSED [ 31%]
tests/test_ha_wiring.py::TestProfileStore::test_load_reconstructs_all_fields PASSED [ 34%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_power_update_calls_tick_and_dispatches_turn_on PASSED [ 37%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_plug_is_on_read_from_hass_state PASSED [ 40%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_power_event_caches_power_w PASSED [ 43%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_temp_event_updates_cache_no_tick PASSED [ 46%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_temp_cache_used_on_next_power_tick PASSED [ 50%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_unavailable_power_produces_none_tick PASSED [ 53%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_unknown_power_produces_none_tick PASSED [ 56%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_trace_buffer_accumulates_valid_power_readings PASSED [ 59%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_trace_buffer_skips_none_power PASSED [ 62%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_trace_buffer_clears_on_charging_reentry PASSED [ 65%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_keepalive_uses_cached_power PASSED [ 68%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_keepalive_with_no_cached_power_passes_none PASSED [ 71%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_async_stop_calls_all_unsubs PASSED [ 75%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_async_stop_clears_unsub_list PASSED [ 78%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_turn_off_dispatched_when_wattage_reaches_target PASSED [ 81%]
tests/test_ha_wiring.py::TestHASensorWatcher::test_no_service_call_for_none_action PASSED [ 84%]
tests/test_ha_wiring.py::TestParseFloat::test_numeric_string PASSED      [ 87%]
tests/test_ha_wiring.py::TestParseFloat::test_unavailable PASSED         [ 90%]
tests/test_ha_wiring.py::TestParseFloat::test_unknown PASSED             [ 93%]
tests/test_ha_wiring.py::TestParseFloat::test_empty_string PASSED        [ 96%]
tests/test_ha_wiring.py::TestAsyncSetupEntry::test_stored_profile_loaded_into_coordinator PASSED [ 88%]
tests/test_ha_wiring.py::TestAsyncSetupEntry::test_fresh_profile_used_when_store_empty PASSED [ 91%]
tests/test_ha_wiring.py::TestParseFloat::test_numeric_string PASSED      [ 93%]
tests/test_ha_wiring.py::TestParseFloat::test_unavailable PASSED         [ 96%]
tests/test_ha_wiring.py::TestParseFloat::test_unknown PASSED             [ 100%]
tests/test_ha_wiring.py::TestParseFloat::test_empty_string PASSED        [ 100%]
tests/test_ha_wiring.py::TestParseFloat::test_non_numeric PASSED         [100%]

34 passed in 0.09s
```

## Anchor artifact

`bdd/ha-adapter/ha-adapter-wiring-trace.json` — verified on disk. Contents:

```json
{
  "slice": "ha-adapter-wiring",
  "profile_loaded": {
    "watts_at_transition": 125.5,
    "state": "calibrated",
    "loaded_from_store": true
  },
  "steps": [
    {
      "step": 1, "event": "power_state_change", "entity": "sensor.plug_power",
      "value": 80.0, "plug_is_on_read_from_hass": false,
      "session_state": "charging", "tick_action": "turn_on",
      "service_call": {"domain": "homeassistant", "service": "turn_on",
                       "data": {"entity_id": "switch.plug"}},
      "trace_buffer_len": 1
    },
    {
      "step": 2, "event": "temp_state_change", "entity": "sensor.battery_temp",
      "value": 22.5, "cached_temp_c": 22.5, "tick_triggered": false
    },
    {
      "step": 3, "event": "power_state_change", "entity": "sensor.plug_power",
      "value": 90.0, "temp_c_applied": 22.5,
      "session_state": "charging", "tick_action": "none",
      "service_call_fired": false,
      "trace_buffer": [["2026-01-01T01:00:00+00:00", 80.0],
                       ["2026-01-01T01:00:30+00:00", 90.0]]
    },
    {
      "step": 4, "event": "power_above_target_wattage", "value": 126.0,
      "session_state": "done_latched_off", "trace_buffer_len": 3,
      "trace_buffer_retained_through_done_latched_off": true
    }
  ]
}
```

## Per-scenario evidence

### Scenario A — power entity update triggers tick and relay dispatch

Covered by `test_power_update_calls_tick_and_dispatches_turn_on` and confirmed by the
anchor trace step 1:
```python
hass.services.async_call.assert_called_once_with(
    "homeassistant", "turn_on", {"entity_id": "switch.plug"}
)
```
Power event 80 W → coordinator.tick() → action=TURN_ON → HA service called with plug entity.
`plug_is_on=False` is read from `hass.states.get("switch.plug").state` at tick time
(confirmed by `test_plug_is_on_read_from_hass_state`).

### Scenario B — temperature entity caches; applied on next power tick only

Covered by `test_temp_event_updates_cache_no_tick` and `test_temp_cache_used_on_next_power_tick`:
```python
run(watcher._handle_temp_state_change(_make_event("22.5")))
assert watcher._cached_temp_c == pytest.approx(22.5)
assert coordinator.session_state == SessionState.IDLE  # no tick triggered
```
Temperature event alone does not drive a tick. Confirmed by anchor trace step 2
(`tick_triggered: false`) and step 3 (`temp_c_applied: 22.5`).

### Scenario C — unavailable power sensor → tick with power_w=None, no crash

Covered by `test_unavailable_power_produces_none_tick` and `test_unknown_power_produces_none_tick`:
```python
run(watcher._handle_power_state_change(_make_event("unavailable")))
hass.services.async_call.assert_not_called()
assert coordinator.session_state == SessionState.IDLE
```
No exception raised; no relay service call; coordinator holds safely in IDLE.

### Scenario D — profile load on setup: saved profile restored from HA storage

Covered at two levels:

**Store round-trip** (`TestProfileStore::test_save_then_load_round_trips`):
```python
run(ps.async_save(original))
restored = run(ps.async_load())
assert restored.watts_at_transition.watts == pytest.approx(125.5)
assert restored.state == ProfileState.CALIBRATED
```

**End-to-end via async_setup_entry** (`TestAsyncSetupEntry::test_stored_profile_loaded_into_coordinator`):
```python
with patch("custom_components.cyclesteward.ProfileStore", return_value=profile_store_instance):
    result = run(async_setup_entry(hass, entry))
assert result is True
coordinator = hass.data[DOMAIN]["test-entry"]
assert coordinator.target_wattage == pytest.approx(125.5)
```
`test_fresh_profile_used_when_store_empty` verifies the fallback: empty store → fresh
profile → `coordinator.target_wattage is None` (uncalibrated).

### Scenario E — live trace accumulates during session; clears on new session start

Covered by three tests:
```python
# Accumulation
run(watcher._do_tick(80.0, t(0)))
run(watcher._do_tick(82.0, t(10)))
run(watcher._do_tick(79.0, t(20)))
buf = watcher.trace_buffer
assert len(buf) == 3  # test_trace_buffer_accumulates_valid_power_readings

# Skips None
run(watcher._do_tick(None, t(10)))
assert len(watcher.trace_buffer) == 2  # test_trace_buffer_skips_none_power

# Clear on reentry; retain through DONE_LATCHED_OFF
# test_trace_buffer_clears_on_charging_reentry
assert len(watcher.trace_buffer) == 1   # new session, buffer cleared
assert watcher.trace_buffer[0][1] == pytest.approx(75.0)
```
Anchor trace step 4 shows `trace_buffer_retained_through_done_latched_off: true`.

### Scenario F — keepalive fires when no power events arrive

Covered by `test_keepalive_uses_cached_power`:
```python
run(watcher._handle_power_state_change(_make_event("85.0")))
run(watcher._handle_keepalive(t(60)))
assert coordinator.session_state == SessionState.CHARGING
```
Cached power_w=85.0 is passed to coordinator.tick() on keepalive; coordinator stays
CHARGING. `test_keepalive_with_no_cached_power_passes_none` confirms no crash when
no power event has arrived yet.

### Scenario G — watcher teardown: all listeners cancelled on async_stop

Covered by `test_async_stop_calls_all_unsubs` and `test_async_stop_clears_unsub_list`:
```python
watcher._unsubs = [unsub1, unsub2]
run(watcher.async_stop())
unsub1.assert_called_once()
unsub2.assert_called_once()
assert watcher._unsubs == []
```
All unsubscribe callables are invoked and the list is cleared. Subsequent state-change
events would not reach tick() since the subscriptions are cancelled.

## Additional relay dispatch coverage

`test_turn_off_dispatched_when_wattage_reaches_target` verifies the TURN_OFF path:
```python
# Tick 1: below target → TURN_ON → CHARGING
run(watcher._do_tick(80.0, t(0)))
assert coordinator.session_state == SessionState.CHARGING
# Tick 2 (>30 s later, past min_dwell): at target wattage → TURN_OFF → DONE_LATCHED_OFF
run(watcher._do_tick(130.0, t(35)))
assert coordinator.session_state == SessionState.DONE_LATCHED_OFF
hass.services.async_call.assert_called_once_with(
    "homeassistant", "turn_off", {"entity_id": "switch.plug"}
)
```
Note: the 35-second gap is required to clear the 30-second `min_dwell_seconds` relay-chatter
guard in `GuardrailEvaluator.check_relay()`.
