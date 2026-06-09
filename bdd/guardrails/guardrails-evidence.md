# Guardrails: Automation fault detection — BDD Evidence

Generated: 2026-06-09  
Test file: `tests/test_guardrails.py` (32 tests, all pass)  
Anchor artifact: `bdd/guardrails/guardrails-trace.json`

---

## Scenario A — maximum runtime faults a stuck session

**Given** a charging session remains active longer than the configured maximum runtime  
**When** the guardrail evaluator runs  
**Then** CycleSteward commands the plug off, records a max-runtime fault, and does not resume automatically

### Evidence

**`test_A_runtime_fault_fires_when_session_exceeds_limit`** — 60 s limit; tick at 61 s:

```
action=TURN_OFF  state=FAULTED  fault=max_runtime
reason="max runtime 60 s exceeded (61 s elapsed)"
```

**`test_A_faulted_session_does_not_resume_automatically`** — three subsequent ticks after fault:

```
tick +70 s: action=NONE  state=FAULTED  fault=None
tick +80 s: action=NONE  state=FAULTED  fault=None
tick +90 s: action=NONE  state=FAULTED  fault=None
```

**`test_A_event_log_records_runtime_fault`** — event_log contains `"guardrail/max_runtime: ..."`.

**Anchor artifact excerpt** (`guardrails-trace.json`, max_runtime_seconds=300):

```json
{
  "timestamp": "2026-01-10T04:05:01+00:00",
  "power_w": 84.0,
  "action": "turn_off",
  "state": "faulted",
  "fault": "max_runtime",
  "reason": "max runtime 300 s exceeded (301 s elapsed)"
},
{
  "timestamp": "2026-01-10T04:05:20+00:00",
  "power_w": 84.0,
  "action": "none",
  "state": "faulted",
  "reason": "faulted; awaiting user action"
}
```

---

## Scenario B — maximum active Wh faults an impossible session

**Given** integrated active Wh exceeds the configured maximum for the profile  
**When** the guardrail evaluator runs  
**Then** CycleSteward commands the plug off and records a max-active-Wh fault

### Evidence

**`test_B_wh_fault_fires_when_accumulated_wh_exceeds_limit`** — config max_active_wh=1.0 Wh; tick at +1 h (80 W × 1 h = 80 Wh):

```
action=TURN_OFF  state=FAULTED  fault=max_active_wh
reason="max active Wh 1.0 exceeded (80.00 Wh accumulated)"
```

**`test_B_profile_derived_wh_limit_used_when_config_is_none`** — config.max_active_wh=None; profile.active_full_wh=400.0 → limit=480.0 Wh; tick at +7 h (80 W × 7 h = 560 Wh):

```
action=TURN_OFF  state=FAULTED  fault=max_active_wh
```

**`test_B_idle_power_subtracted_from_active_wh`** — idle_power_w=5.0; active=80−5=75 W; 75 W × 5 min = 6.25 Wh > 5.0 Wh limit:

```
fault=max_active_wh
```

**`test_B_wh_guardrail_disabled_when_no_profile_no_config`** — no limit configured; 1000 W accumulated for 100 h; `check_active_wh(None)` returns `None`.

---

## Scenario C — relay chatter is prevented

**Given** recent on/off transitions already reached the configured relay-cycle limit or minimum dwell time has not elapsed  
**When** a policy would otherwise toggle the plug  
**Then** CycleSteward suppresses the toggle and records the relay guardrail reason

### Evidence

**`test_C_min_dwell_suppresses_rapid_cutoff`** — min_dwell=60 s; cutoff proposed at +30 s after TURN_ON:

```
action=NONE  state=CHARGING  fault=min_dwell
reason="relay suppressed: min dwell 60 s not elapsed (30.0 s since last transition)"
```

**`test_C_cutoff_allowed_after_dwell_period`** — min_dwell=30 s; cutoff proposed at +60 s:

```
action=TURN_OFF  fault=None
```

**`test_C_relay_cycle_limit_suppresses_toggle`** — relay_cycle_limit=1; after TURN_ON (transitions=[T0], len=1); cutoff proposed:

```
action=NONE  fault=relay_limit
reason="relay suppressed: relay cycle limit 1 reached (1 transitions so far)"
```

**`test_C_initial_turn_on_never_suppressed`** — min_dwell=999 s, relay_cycle_limit=0; initial TURN_ON with empty relay_transitions:

```
action=TURN_ON  fault=None
```

**`test_C_evaluator_check_relay_suppresses_below_dwell`** — unit test directly on GuardrailEvaluator; min_dwell=60 s; check at +30 s:

```
result.fault=MIN_DWELL  result.is_session_fault=False
```

**`test_C_evaluator_check_relay_empty_transitions_never_suppresses`** — unit test; relay_transitions not initialised; check_relay returns None regardless of min_dwell or cycle limit:

```
result=None
```

---

## Scenario D — switch command failure is visible

**Given** CycleSteward commands the smart plug off  
**When** the switch entity remains on after the confirmation timeout  
**Then** CycleSteward records a switch-command fault and emits a notification or event

### Evidence

**`test_D_command_failure_faults_when_plug_stays_on_past_deadline`** — command_confirm_seconds=10; plug still on at +11 s after TURN_OFF:

```
action=NONE  state=FAULTED  fault=switch_command_failure
reason="plug still on 10 s after TURN_OFF command"
```

**`test_D_no_fault_when_plug_confirms_off_before_deadline`** — plug reports off at +5 s (within 10 s deadline):

```
state=DONE_LATCHED_OFF  fault=None  (pending deadline cleared)
```

**`test_D_no_fault_before_deadline_even_if_plug_still_on`** — plug still on at +3 s (within 10 s deadline):

```
state=DONE_LATCHED_OFF  fault=None
```

**`test_D_command_fault_fires_from_done_latched_off_state`** — confirms command confirmation runs before the DONE_LATCHED_OFF short-circuit:

```
Initial state: DONE_LATCHED_OFF
After +11 s with plug_is_on=True: state=FAULTED  fault=switch_command_failure
```

**`test_D_no_pending_command_without_turn_off`** — Without a prior TURN_OFF, plug_is_on=True has no effect:

```
state=CHARGING  fault=None
```

**`test_D_morning_reset_wins_over_pending_command_confirmation`** — Morning reset fires on the same tick the command deadline is reached; reset deliberately wins, clears the pending deadline:

```
reason contains "morning reset"; fault=None  (no switch_command_failure raised)
```

---

## Scenario E — freeze lockout refuses to start charging when cold

**Given** an optional temperature sensor reports below the configured freeze threshold (after sensor-location offset)  
**When** a charge would otherwise start  
**Then** CycleSteward refuses to energize the plug and records a freeze-lockout reason

### Evidence (session-control state machine)

**`test_E_freeze_lockout_prevents_start`** — freeze_threshold=5 °C; sensor=2 °C:

```
action=NONE  state=IDLE
reason="freeze lockout: 2.0 °C < 5.0 °C"
```

**`test_E_freeze_lockout_with_sensor_offset`** — offset=+1 °C; sensor=3 °C; effective=4 °C < 5 °C:

```
state=IDLE; reason contains "4.0" and "5.0"
```

**`test_E_freeze_lockout_allows_start_above_threshold`** — sensor=10 °C > 5 °C:

```
action=TURN_ON  (no lockout)
```

---

## Scenario F — heat delays charging rather than blocking it

**Given** the temperature is above the configured heat-delay threshold  
**When** a scheduled charge would otherwise begin  
**Then** CycleSteward holds in a non-fault waiting state and retries as it cools, and only skips with a notification if it has not cooled by the configured deadline

### Evidence (session-control state machine)

**`test_F_heat_delay_enters_non_fault_waiting_state`** — heat_delay_threshold=30 °C; sensor=35 °C:

```
action=NONE  state=HEAT_DELAY  fault=None
reason="heat delay: 35.0 °C > 30.0 °C"
```

**`test_F_heat_delay_retries_after_cooling`** — after 1 h sensor cools to 25 °C:

```
action=TURN_ON  state=CHARGING
```

**`test_F_heat_delay_deadline_skips_session_with_notification`** — deadline=600 s; still 35 °C at +11 min:

```
reason contains "deadline exceeded"; ctrl.mode=OFF
```

---

## Scenario G — missing or non-numeric readings default safely

**Given** the power or temperature reading is `unknown`/`unavailable` or non-numeric for a sample  
**When** the guardrail evaluator runs  
**Then** it treats the reading as no-progress / hold using a safe default and does not crash or misfire a cutoff

### Evidence (session-control state machine)

**`test_G_none_power_holds_state_without_cutoff`** — power_w=None while CHARGING:

```
action=NONE  state=CHARGING  fault=None
reason="power reading unavailable; holding"
```

**`test_G_none_power_does_not_accumulate_wh`** — power_w=None with max_active_wh=0.01 over 5 hours:

```
All ticks: fault != MAX_ACTIVE_WH  (no Wh accumulated for None readings)
```

**`test_G_none_temperature_proceeds_ungated`** — temperature_c=None with freeze_threshold=25 °C (would block if sensor present):

```
action=TURN_ON  (gating disabled; no sensor)
```

---

## Architecture note

The new `GuardrailEvaluator` (A–D) and the existing temperature-gate / missing-reading paths (E–G) form the complete guardrail surface. `guardrails.py` has no Home Assistant imports. The command-confirmation check runs before the DONE_LATCHED_OFF terminal-state short-circuit (documented by `test_D_command_fault_fires_from_done_latched_off_state`). Morning reset deliberately wins over pending command confirmation (documented by `test_D_morning_reset_wins_over_pending_command_confirmation`).
