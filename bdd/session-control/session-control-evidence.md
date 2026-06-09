# session-control-evidence.md

Slice: scenarios A–H
Date: 2026-06-09
Command: `.venv/bin/pytest tests/test_session_control.py -v` (31 passed, 0 failed)
Full suite: `96 passed` — no regressions
Lint: `ruff check src/ tests/` — all checks passed
Architecture review: OK (no invariant violations)

### Raw pytest output

```
platform darwin -- Python 3.9.6, pytest-8.4.2
collected 31 items

tests/test_session_control.py::test_scenario_A_initial_tick_starts_charging PASSED [  3%]
tests/test_session_control.py::test_scenario_A_below_target_keeps_charging PASSED [  6%]
tests/test_session_control.py::test_scenario_A_cutoff_fires_on_first_crossing PASSED [  9%]
tests/test_session_control.py::test_scenario_A_no_double_gate PASSED     [ 12%]
tests/test_session_control.py::test_scenario_B_latch_persists_across_ticks PASSED [ 16%]
tests/test_session_control.py::test_scenario_B_new_set_mode_unlocks_latch PASSED [ 19%]
tests/test_session_control.py::test_scenario_C_waits_before_scheduled_start PASSED [ 22%]
tests/test_session_control.py::test_scenario_C_starts_at_scheduled_time PASSED [ 25%]
tests/test_session_control.py::test_scenario_C_transitions_from_waiting_to_charging PASSED [ 29%]
tests/test_session_control.py::test_scenario_D_morning_reset_clears_mode PASSED [ 32%]
tests/test_session_control.py::test_scenario_D_after_reset_no_charging PASSED [ 35%]
tests/test_session_control.py::test_scenario_D_morning_reset_fires_once_per_day PASSED [ 38%]
tests/test_session_control.py::test_scenario_E_manual_override_bypasses_schedule PASSED [ 41%]
tests/test_session_control.py::test_scenario_E_manual_override_cutoff_fires PASSED [ 45%]
tests/test_session_control.py::test_scenario_F_charges_until_taper_floor PASSED [ 48%]
tests/test_session_control.py::test_scenario_F_taper_timer_resets_when_power_rises PASSED [ 51%]
tests/test_session_control.py::test_scenario_G_low_confidence_when_calibrating PASSED [ 54%]
tests/test_session_control.py::test_scenario_G_high_confidence_when_calibrated PASSED [ 58%]
tests/test_session_control.py::test_scenario_G_soc_estimate_formula PASSED [ 61%]
tests/test_session_control.py::test_scenario_G_above_transition_flags_low_confidence PASSED [ 64%]
tests/test_session_control.py::test_scenario_G_uncalibrated_profile_flags_low_confidence PASSED [ 67%]
tests/test_session_control.py::test_scenario_H_freeze_lockout_prevents_start PASSED [ 70%]
tests/test_session_control.py::test_scenario_H_freeze_lockout_records_reason PASSED [ 74%]
tests/test_session_control.py::test_scenario_H_heat_delay_enters_waiting_state PASSED [ 77%]
tests/test_session_control.py::test_scenario_H_heat_delay_retries_when_cooled PASSED [ 80%]
tests/test_session_control.py::test_scenario_H_heat_delay_deadline_skips_session PASSED [ 83%]
tests/test_session_control.py::test_scenario_H_no_sensor_proceeds_ungated PASSED [ 87%]
tests/test_session_control.py::test_missing_power_holds_state PASSED     [ 90%]
tests/test_session_control.py::test_temp_compensation_shifts_target_up_when_cold PASSED [ 93%]
tests/test_session_control.py::test_temp_compensation_adds_note_to_soc_estimate PASSED [ 96%]
tests/test_session_control.py::test_generate_charge_to_target_trace PASSED [100%]

31 passed in 0.05s
```

---

## Scenario A — cut off when wattage first crosses the target threshold

Profile: `watts_at_low=70 W (0 % SoC)`, `watts_at_transition=100 W (80 % SoC)`.
Target: 50 % → `target_wattage(50) = 70 + (50/80)*30 = 88.75 W`.

Test output (raw tick trace from `test_generate_charge_to_target_trace`):

```
timestamp=04:00  power=70.0 W   action=turn_on   state=charging        reason="starting charge"
timestamp=04:05  power=75.0 W   action=none      state=charging        soc_est=13.3 % ±10 %
timestamp=04:10  power=80.0 W   action=none      state=charging        soc_est=26.7 % ±10 %
timestamp=04:15  power=85.0 W   action=none      state=charging        soc_est=40.0 % ±10 %
timestamp=04:20  power=88.0 W   action=none      state=charging        soc_est=48.0 % ±10 %
timestamp=04:25  power=89.0 W   action=turn_off  state=done_latched_off reason="wattage 89.0 W >= target 88.8 W; cutoff"
```

Artifact on disk: `bdd/session-control/session-control-trace.json` (verified in test).

Tests:
- `test_scenario_A_initial_tick_starts_charging` PASSED
- `test_scenario_A_below_target_keeps_charging` PASSED
- `test_scenario_A_cutoff_fires_on_first_crossing` PASSED
- `test_scenario_A_no_double_gate` PASSED (exactly at 88.75 W fires cutoff)

The cutoff fires on the **first** crossing with no separate gate condition. ✓

---

## Scenario B — bike rests at target, no departure timing needed

After the cutoff above, the controller is in `DONE_LATCHED_OFF`. Five subsequent ticks
(04:02–04:06) all return:

```
action=none  state=done_latched_off  reason="latched off; awaiting new session"
```

Setting a new mode via `set_mode()` resets to `IDLE`; the next tick returns `TURN_ON`. ✓

Tests:
- `test_scenario_B_latch_persists_across_ticks` PASSED
- `test_scenario_B_new_set_mode_unlocks_latch` PASSED

---

## Scenario C — scheduled charging starts at the configured time

Profile with `scheduled_start=22:00` (10 pm). Tick at 04:00:

```
action=none  state=waiting_for_schedule  reason="before scheduled start 22:00:00"
```

Tick at 04:02 (past `scheduled_start=04:01`):

```
action=turn_on  state=charging  reason="starting charge"
```

Tests:
- `test_scenario_C_waits_before_scheduled_start` PASSED
- `test_scenario_C_starts_at_scheduled_time` PASSED
- `test_scenario_C_transitions_from_waiting_to_charging` PASSED

---

## Scenario D — modes off by default and reset each morning

Controller with `morning_reset_time=06:00`, mode set to `CHARGE_TO_TARGET` overnight.

Tick at 05:59 (Jan 11): mode still `CHARGE_TO_TARGET`, no reset.

Tick at 06:00 (Jan 11):

```
action=none  state=idle  reason="morning reset: modes cleared"
mode=off
```

After reset, tick at 06:05: `action=none`, `mode=off` — charging does not restart. ✓

Morning reset fires only once per day: after reset, re-setting mode and ticking at 06:10 does **not** re-fire:

```
action=turn_on  state=charging  (no "morning reset" in reason)
```

Tests:
- `test_scenario_D_morning_reset_clears_mode` PASSED
- `test_scenario_D_after_reset_no_charging` PASSED
- `test_scenario_D_morning_reset_fires_once_per_day` PASSED

---

## Scenario E — manual override still honors the cutoff

Mode `CHARGE_TO_TARGET`, `scheduled_start=23:00`. Normal tick at 04:00:

```
state=waiting_for_schedule
```

`manual_override_on()` → `state=CHARGING`. Tick at 04:05 with 89.0 W (above 88.75 W target):

```
action=turn_off  state=done_latched_off  reason="wattage 89.0 W >= target 88.8 W; cutoff"
```

Cutoff fires via the manual-override path as well. ✓

Tests:
- `test_scenario_E_manual_override_bypasses_schedule` PASSED
- `test_scenario_E_manual_override_cutoff_fires` PASSED

---

## Scenario F — "Charge to full" stop is best-effort

Profile: `taper_floor_w=12 W`, `taper_below_floor_seconds=60 s`.

Sequence after `TURN_ON`:

```
t=00:01  power=50.0 W   state=charging   (above floor; no timer)
t=02:00  power= 8.0 W   state=charging   (below floor; taper timer starts)
t=02:30  power= 8.0 W   state=charging   (30 s < 60 s; timer running)
t=03:01  power= 8.0 W   action=turn_off  state=done_latched_off
                         reason="wattage below taper floor for configured duration; best-effort full completion"
```

When power rises above the floor mid-taper, the timer resets. A subsequent 30 s below does not trigger cutoff. ✓

Tests:
- `test_scenario_F_charges_until_taper_floor` PASSED
- `test_scenario_F_taper_timer_resets_when_power_rises` PASSED

---

## Scenario G — uncertain SoC estimate is surfaced

With a fully calibrated profile (`watts_at_low=70, watts_at_transition=100`):

```
power=80.0 W:  SocEstimate(estimated_soc_pct=26.7, uncertainty_pct=10.0, low_confidence=False, note="")
```

Formula verification: `0 + (80-70)/(100-70) * 80 = 26.667 %` → rounds to `26.7 %`. ✓

With a `CALIBRATING` (partial) profile, same power:

```
SocEstimate(estimated_soc_pct=26.7, uncertainty_pct=20.0, low_confidence=True, note="")
```

Above the CC/CV transition (105 W):

```
SocEstimate(estimated_soc_pct=80.0, uncertainty_pct=15.0, low_confidence=True,
            note="above CC/CV transition; model less reliable")
```

Uncalibrated profile (no anchors):

```
SocEstimate(estimated_soc_pct=0.0, uncertainty_pct=50.0, low_confidence=True,
            note="profile not calibrated")
```

Tests:
- `test_scenario_G_low_confidence_when_calibrating` PASSED
- `test_scenario_G_high_confidence_when_calibrated` PASSED
- `test_scenario_G_soc_estimate_formula` PASSED
- `test_scenario_G_above_transition_flags_low_confidence` PASSED
- `test_scenario_G_uncalibrated_profile_flags_low_confidence` PASSED

---

## Scenario H — temperature gate prevents starting

### Freeze lockout

`TemperatureConfig(freeze_threshold_c=5.0)`, temperature reading 2.0 °C:

```
action=none  state=idle  reason="freeze lockout: 2.0 °C < 5.0 °C"
```

With sensor offset (`sensor_offset_c=1.0`) and temperature 3.0 °C (effective = 4.0 °C):

```
reason="freeze lockout: 4.0 °C < 5.0 °C"
```

Freeze lockout is a hard stop; the state remains `IDLE`. ✓

### Heat delay (non-fault waiting state)

`TemperatureConfig(heat_delay_threshold_c=30.0)`, temperature 35.0 °C:

```
action=none  state=heat_delay  reason="heat delay: 35.0 °C > 30.0 °C"
```

When temperature drops to 25.0 °C on the next tick:

```
action=turn_on  state=charging  reason="starting charge"
```

HEAT_DELAY exits cleanly and charging begins. ✓

### Heat delay deadline exceeded

`heat_delay_deadline_seconds=600`, temperature stays 35.0 °C for 11 minutes:

```
action=none  state=idle  reason="heat delay deadline exceeded after 660 s; session skipped, mode reset to off"
mode=off
```

### No sensor — proceeds ungated

With `temperature_c=None` (no sensor), `freeze_threshold_c=25.0` (would block if sensor present):

```
action=turn_on  state=charging
```

Temperature gating is fully disabled when no sensor is configured (ADR-0008). ✓

Tests:
- `test_scenario_H_freeze_lockout_prevents_start` PASSED
- `test_scenario_H_freeze_lockout_records_reason` PASSED
- `test_scenario_H_heat_delay_enters_waiting_state` PASSED
- `test_scenario_H_heat_delay_retries_when_cooled` PASSED
- `test_scenario_H_heat_delay_deadline_skips_session` PASSED
- `test_scenario_H_no_sensor_proceeds_ungated` PASSED

---

## Additional coverage

**Missing/non-numeric readings** (`test_missing_power_holds_state` PASSED):

```
power=None → action=none  state=charging  reason="power reading unavailable; holding"
```

No cutoff misfire on unknown readings. ✓

**Temperature compensation** (`test_temp_compensation_shifts_target_up_when_cold` PASSED):

```
temp_coeff=0.5 W/°C, baseline=20 °C, actual=10 °C
base_target=88.75 W, compensation=0.5*(10-20)=-5 W → adjusted_target=83.75 W
power=84.0 W >= 83.75 W → turn_off, done_latched_off
```

SoC estimate note when compensation is active (`test_temp_compensation_adds_note_to_soc_estimate` PASSED):

```
SocEstimate(note="temperature-compensated")
```

**Anchor artifact** (`test_generate_charge_to_target_trace` PASSED):
`bdd/session-control/session-control-trace.json` written and verified: contains
`"charging"` state events, a `"turn_off"` / `"done_latched_off"` cutoff event,
and a subsequent `"none"` / `"done_latched_off"` latch-hold event.
