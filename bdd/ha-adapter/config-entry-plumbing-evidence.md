# Config-entry plumbing — BDD evidence

Paired with [config-entry-plumbing-bdd.md](config-entry-plumbing-bdd.md) and
[docs/specs/config-entry-plumbing.md](../../docs/specs/config-entry-plumbing.md).
Closes review finding F1.

Tests: `tests/test_config_entry_plumbing.py` (24 tests). HA + voluptuous are
stubbed session-wide by `tests/conftest.py` → `tests/ha_stubs.py`, so the **real**
`config_flow`, `time`, `services`, and `__init__` modules run as pure Python.
Anchor artifact: `bdd/ha-adapter/config-entry-plumbing-trace.json`.

Full suite: **266 passed**, `ruff check .` clean. Run date: 2026-06-16
(`.venv/bin/python -m pytest`).

```
$ .venv/bin/python -m pytest tests/test_config_entry_plumbing.py -v
tests/test_config_entry_plumbing.py::TestScenarioA::test_schema_collects_entity_ids PASSED
tests/test_config_entry_plumbing.py::TestScenarioA::test_entry_data_round_trips PASSED
tests/test_config_entry_plumbing.py::TestScenarioA::test_no_input_shows_form_with_schema PASSED
tests/test_config_entry_plumbing.py::TestScenarioB::test_watcher_started_with_margin_and_next_occurrence PASSED
tests/test_config_entry_plumbing.py::TestScenarioB::test_morning_reset_round_tripped_into_config PASSED
tests/test_config_entry_plumbing.py::TestScenarioB::test_no_watcher_when_entity_ids_absent PASSED
tests/test_config_entry_plumbing.py::TestScenarioC::test_set_value_pushes_next_occurrence_to_watcher PASSED
tests/test_config_entry_plumbing.py::TestScenarioC::test_past_time_of_day_rolls_to_tomorrow PASSED
tests/test_config_entry_plumbing.py::TestScenarioC::test_no_watcher_is_noop_beyond_storing_value PASSED
tests/test_config_entry_plumbing.py::TestScenarioD::test_set_value_round_trips_into_config PASSED
tests/test_config_entry_plumbing.py::TestScenarioD::test_controller_arms_against_new_reset_on_next_tick PASSED
tests/test_config_entry_plumbing.py::TestScenarioE::test_set_mode_service_reaches_coordinator PASSED
tests/test_config_entry_plumbing.py::TestScenarioE::test_manual_override_service_transitions_to_charging PASSED
tests/test_config_entry_plumbing.py::TestScenarioE::test_acknowledge_fault_service_clears_fault PASSED
tests/test_config_entry_plumbing.py::TestScenarioE::test_unknown_entry_id_raises PASSED
tests/test_config_entry_plumbing.py::TestScenarioE::test_registration_is_idempotent PASSED
tests/test_config_entry_plumbing.py::TestScenarioF::test_only_kept_services_declared PASSED
tests/test_config_entry_plumbing.py::TestScenarioF::test_trimmed_services_absent PASSED
tests/test_config_entry_plumbing.py::TestScenarioF::test_declared_services_all_register PASSED
tests/test_config_entry_plumbing.py::TestScenarioG::test_next_occurrence_is_timezone_aware PASSED
tests/test_config_entry_plumbing.py::TestScenarioG::test_future_time_today PASSED
tests/test_config_entry_plumbing.py::TestScenarioG::test_past_time_rolls_to_tomorrow PASSED
tests/test_config_entry_plumbing.py::TestScenarioG::test_equal_to_now_rolls_to_tomorrow PASSED
tests/test_config_entry_plumbing.py::TestScenarioG::test_sub_second_now_does_not_block_same_day PASSED
```

---

## Scenario A — config flow collects entity IDs; entry data round-trips

`STEP_USER_DATA_SCHEMA` introspection — required vs optional keys:

```
required = {power_entity_id, plug_entity_id, charger_label, battery_label, meter_id}
optional = {temp_entity_id, target_soc_dots, margin_s, rated_capacity_wh}
```

`async_step_user(user_input)` returns the created entry with the operational
fields carried through verbatim:

```
result["type"]                  == "create_entry"
result["data"]["power_entity_id"] == "sensor.bike_plug_power"
result["data"]["plug_entity_id"]  == "switch.bike_plug"
result["data"]                  == user_input   # full round-trip
```

`async_step_user(None)` returns `{"type": "form", "data_schema": STEP_USER_DATA_SCHEMA}`.

## Scenario B — watcher starts from a real entry (anchor artifact)

`async_setup_entry` driven against a mock `hass` with the anchor
(`config-entry-plumbing-trace.json`). Raw captured values:

```
setup_result                       = True
now                                = 2026-06-16T08:00:00+00:00
watcher listeners registered       = 3        (power + temp + keepalive)
watcher._margin_s                  = 1200.0   (threaded from entry.data)
target_finish (next occurrence)    = 2026-06-17T07:30:00+00:00   (07:30 past 08:00 → tomorrow)
target_finish tzinfo               = UTC
computed_start_time                = 2026-06-17T01:34:00+00:00   (pessimistic = finish − max_dur − margin)
coordinator.morning_reset_time     = 05:30:00
registered services                = ['acknowledge_fault', 'manual_override', 'set_mode']
```

The exact `listeners_registered` (3), `target_finish_next_occurrence`, and
`computed_start_time` are pinned in the anchor's `expected` block and asserted
by `test_watcher_started_with_margin_and_next_occurrence` (the test reads the
expected values from the fixture and asserts equality), so these figures are the
artifact's, not hand-transcribed prose. `computed_start_time` is the watcher's
pessimistic start = finish − max_duration − margin: an uncalibrated profile gives
`estimated_duration_s()` = 4 h ± 0.8 h → max = 4 h + 2×0.8 h = 5.6 h; 07:30 −
5.6 h − 1200 s = 01:34.

When `power_entity_id`/`plug_entity_id` are absent, no watcher is created
(`"<entry>.watcher"` not in `hass.data[DOMAIN]`) — the existing inert path is
preserved for an unconfigured entry.

## Scenario C — target-finish time drives the schedule (next-occurrence, tz-aware)

`TargetFinishTimeEntity.async_set_value(time)` with `dt_util.now()` =
`2026-06-16T08:00:00+00:00`:

```
set 09:30 (ahead of now)  → watcher._target_finish_time = 2026-06-16T09:30:00+00:00 (today)
set 06:00 (past now)      → watcher._target_finish_time = 2026-06-17T06:00:00+00:00 (tomorrow)
watcher.computed_start_time is recomputed (not None) on each set
```

No watcher registered → set is a no-op beyond storing `native_value` (no raise).

## Scenario D — morning-reset time round-trips into SessionConfig

`MorningResetTimeEntity.async_set_value(time(5, 30))`:

```
coordinator.morning_reset_time before = 06:00:00   (SessionConfig default)
coordinator.morning_reset_time after  = 05:30:00
```

A tick after the new boundary (05:45) does not crash and the controller reads
the updated reset time (`05:30:00`) on that tick's arming check.

## Scenario E — services registered and reach the coordinator

Service handlers invoked through the (fake) registry:

```
set_mode {mode: charge_to_target}     → coordinator.charge_mode: OFF → CHARGE_TO_TARGET
manual_override {enabled: true}       → coordinator.session_state → CHARGING (mode set)
acknowledge_fault (after MAX_RUNTIME) → coordinator.session_state: FAULTED → not FAULTED
unknown entry_id                      → ValueError raised
async_register_services called twice  → idempotent (no duplicate handlers)
```

The MAX_RUNTIME fault for the acknowledge test is produced by a real
`GuardrailsConfig(max_runtime_seconds=10.0)` and two real coordinator ticks
5 minutes apart — not a stubbed fault.

## Scenario F — services.yaml declares only services with a backing path

Top-level keys parsed from the shipped `custom_components/cyclesteward/services.yaml`:

```
declared = {set_mode, manual_override, acknowledge_fault}
start_calibration_session  ∉ declared   (trimmed; spec D2)
import_history             ∉ declared   (trimmed; spec D2)
declared == registered services in services.py   (no declared-but-dead service)
```

## Scenario G — timezone discipline: no naive datetimes in scheduling

`next_occurrence(tod, now)` (pure helper; HA passes `dt_util.now()`):

```
now = 2026-06-16T08:00:00+00:00
next_occurrence(09:30) = 2026-06-16T09:30:00+00:00   tzinfo = UTC (aware)
next_occurrence(07:00) = 2026-06-17T07:00:00+00:00   (past → tomorrow)
next_occurrence(08:00) = 2026-06-17T08:00:00+00:00   (== now → tomorrow, no zero-length window)
next_occurrence(08:00) with now=08:00:00.5 = 2026-06-17T08:00:00+00:00
```

Result `tzinfo` always equals `now.tzinfo`; passing an aware `now` yields an
aware datetime, so no naive datetime enters the scheduling path.
