# Home Assistant entity adapter — BDD

## Status

Active. Paired with
[docs/specs/ha-entity-adapter.md](../../docs/specs/ha-entity-adapter.md).

## Why this BDD exists

Pins down the observable behavior of `CyclestewardCoordinator` and the
`charge_mode` select / `session_state` sensor entities before code is written.
All scenarios are provable in pure Python (no HA install required).

## Scenarios

### Scenario A — setting mode triggers charging on next tick

**Given** a coordinator with an uncalibrated profile, mode = `off`, state = `idle`
**When** `set_mode(CHARGE_TO_TARGET)` is called, then `tick(power_w=70)` is
called
**Then** the tick result has `action = turn_on`, `state = charging`, and
`coordinator.session_state == CHARGING`

### Scenario B — setting mode to off returns to idle

**Given** a coordinator currently in `CHARGING` state
**When** `set_mode(OFF)` is called
**Then** `coordinator.charge_mode == OFF` and `coordinator.session_state ==
IDLE`

### Scenario C — wattage cutoff fires DONE_LATCHED_OFF

**Given** a coordinator with a calibrated profile and target wattage 95 W, in
`CHARGING` state
**When** `tick(power_w=96)` is called at least 30 s after charging started
**Then** the result has `action = turn_off`, `state = done_latched_off`, and
`coordinator.session_state == DONE_LATCHED_OFF`

### Scenario D — session_state property reflects controller state

**Given** a coordinator with mode = `off`
**When** `session_state` is read
**Then** it returns `IDLE`; after `set_mode` + tick it returns `CHARGING`

### Scenario E — charge_mode property reflects controller mode

**Given** a coordinator just initialised
**When** `charge_mode` is read
**Then** it returns `OFF`; after `set_mode(CHARGE_TO_TARGET)` it returns
`CHARGE_TO_TARGET`

### Scenario F — morning reset clears mode to off

**Given** a coordinator with mode = `charge_to_target`, morning reset at 06:00
**When** `tick(now=06:01)` is called (past the reset time)
**Then** the result reason is `"morning reset: modes cleared"`,
`coordinator.charge_mode == OFF`, and `coordinator.session_state == IDLE`

### Scenario G — guardrail fault surfaces in TickResult

**Given** a coordinator with `max_runtime_seconds = 60`
**When** a charging session has been running for 65 s and `tick` is called
**Then** `result.fault == MAX_RUNTIME`, `result.state == FAULTED`, and
`coordinator.session_state == FAULTED`

### Scenario H — soc_estimate carried in TickResult during charging

**Given** a coordinator with a calibrated profile in `CHARGING` state
**When** `tick(power_w=75)` is called on the second charging tick
**Then** `result.soc_estimate` is not None, carries `uncertainty_pct` and
`low_confidence`, and `coordinator.soc_estimate` returns the same object

### Scenario I — listener is notified on tick and mode change

**Given** a coordinator with a registered listener callback
**When** `set_mode` and `tick` are each called once
**Then** the listener is called once per operation (2 total)

### Scenario J — unsubscribe stops notifications

**Given** a coordinator with a listener that has been unsubscribed
**When** a subsequent `tick` is called
**Then** the listener is not called again after unsubscribe

## Anchor artifact

The implementing test generates
`bdd/ha-adapter/ha-entity-adapter-trace.json`: a JSON sequence of coordinator
states across a full charge session from `set_mode` to `DONE_LATCHED_OFF`.

## Evidence

The implementing slice produces an evidence file at
`bdd/ha-adapter/ha-entity-adapter-evidence.md` containing raw test output
(not summaries) for each scenario.
