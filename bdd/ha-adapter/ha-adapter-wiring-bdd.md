# HA adapter: live sensor wiring + profile persistence — BDD

## Status

Draft. Paired with [docs/specs/ha-adapter-wiring.md](../../docs/specs/ha-adapter-wiring.md).

## Why this BDD exists

Pins the observable boundary between real HA sensor entities and the pure-Python coordinator:
a real power-entity state change must flow through to a relay action, and a calibration profile
must survive a simulated HA restart.

## Scenarios

### Scenario A — power entity update triggers tick and relay dispatch

**Given** `HASensorWatcher` initialized with power entity "sensor.plug_power", plug entity
"switch.plug", and `CyclestewardCoordinator` in CHARGE_TO_TARGET mode with a calibrated profile
(watts_at_transition = 130 W); HA state for "switch.plug" is "off"
**When** HA fires a `state_changed` event for "sensor.plug_power" with new state "80.0"
**Then** `coordinator.tick()` is called with power_w=80.0 and plug_is_on=False (read from HA
state at tick time); TickResult.action == TURN_ON; the HA `homeassistant.turn_on` service is
called with entity_id "switch.plug"

### Scenario B — temperature entity caches; applied on next power tick only

**Given** `HASensorWatcher` initialized with power entity, plug entity, and temp entity
"sensor.battery_temp"
**When** HA fires `state_changed` for "sensor.battery_temp" with new state "22.5", then
HA fires `state_changed` for "sensor.plug_power" with new state "90.0"
**Then** `coordinator.tick()` is called exactly once (on the power event) with temp_c=22.5;
the temperature event alone does not trigger a tick

### Scenario C — unavailable power sensor → tick with power_w=None, no crash

**Given** `HASensorWatcher` initialized and running
**When** HA fires `state_changed` for "sensor.plug_power" with new state "unavailable"
**Then** `coordinator.tick()` is called with power_w=None; no exception raised; no relay
service call is made (action == NONE)

### Scenario D — profile load on setup: saved profile restored from HA storage

**Given** HA storage contains a `CalibrationProfile` JSON previously saved via `ProfileStore`
(with watts_at_transition = 125.5)
**When** `async_setup_entry` runs for that config entry
**Then** the coordinator is initialized with the stored profile (profile.watts_at_transition == 125.5),
not a fresh default profile

### Scenario E — live trace accumulates during session; clears on new session start

**Given** `HASensorWatcher` running with coordinator in CHARGING state
**When** power ticks arrive with values 80.0 W, 82.0 W, 79.0 W at times t1, t2, t3; then
coordinator transitions to DONE_LATCHED_OFF; then a new session begins (CHARGING re-entered)
**Then** after the three ticks the trace buffer holds [(t1, 80.0), (t2, 82.0), (t3, 79.0)];
the buffer is retained through DONE_LATCHED_OFF; it is cleared when CHARGING is entered again

### Scenario F — keepalive tick fires when no power events arrive

**Given** `HASensorWatcher` running, last cached power reading was 85.0 W,
keepalive_interval_s = 60
**When** 60 seconds elapse without a power entity state change
**Then** `coordinator.tick()` is called with power_w=85.0 (the cached value); coordinator
state is updated normally

### Scenario G — watcher teardown: all listeners cancelled on async_stop

**Given** `HASensorWatcher` started and actively subscribed to state-change events
**When** `async_stop()` is called (simulating integration unload)
**Then** all state-change listeners are unregistered and the keepalive timer is cancelled;
subsequent state-change events do not trigger `coordinator.tick()`

## Evidence

The implementing slice produces:
- `bdd/ha-adapter/ha-adapter-wiring-evidence.md` — raw test outputs (not summaries) for each
  scenario A–G
- `bdd/ha-adapter/ha-adapter-wiring-trace.json` — anchor artifact JSON trace: profile load →
  power update → relay dispatch → temp update → second tick with temp → trace buffer contents
  shown at DONE_LATCHED_OFF
