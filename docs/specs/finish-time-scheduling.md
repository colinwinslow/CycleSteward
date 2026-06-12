---
status: draft
date: 2026-06-10
depends-on-adrs: [0009, 0011, 0012]
---

# Finish-Time Scheduling: Probe, derived start time, and transparency

## Status

Draft. Defines the scheduling logic for deriving a charge start time from
`target_finish_time` per ADR-0012.

## Related docs

- [bdd/ha-adapter/finish-time-scheduling-bdd.md](../../bdd/ha-adapter/finish-time-scheduling-bdd.md) — observable behavior
- [STATUS.md](../../STATUS.md) — current phase and active work
- [ADR-0012](../decisions/0012-finish-time-scheduling-and-probe-transparency.md)
- [ADR-0011](../decisions/0011-ha-entity-service-surface.md)
- [ADR-0009](../decisions/0009-charge-modes-scheduling-safe-defaults.md)

## Context

The user sets a `target_finish_time` ("ready by 07:00") in HA. The integration
derives when to start charging. To do this accurately it needs to know the
battery's current SoC, which requires a brief pre-charge probe — energizing the
charger for ≤5 min to read a stable CC-phase wattage. After the probe, the
adapter refines the computed start time; if the probe fails, it falls back to
the pessimistic (worst-case) start time.

Every automatic energization — probe or charge session — must surface a
human-readable explanation in the HA UI and record a logbook event. Silently
turning the charger on is a bug.

## Behavior contract

### New session state

```python
class SessionState(str, Enum):
    ...
    PROBING = "probing"          # charger on for a bounded SoC-read probe
```

### `SessionController.tick()` new parameter

```python
def tick(
    self,
    now: datetime,
    power_w: Optional[float],
    temperature_c: Optional[float],
    plug_is_on: Optional[bool] = None,
    computed_start_time: Optional[datetime] = None,   # NEW
) -> TickResult:
```

When `session_state == WAITING_FOR_SCHEDULE`, the controller transitions to
`CHARGING` when `now >= computed_start_time`. Before the first probe,
`computed_start_time` defaults to:

```
target_finish_time − max_profile_duration − margin
```

The controller is stateless about how `computed_start_time` was derived.

### `session_reason` attribute

`session_state` sensor always carries a non-empty `session_reason` string
attribute whenever `session_state != OFF_IDLE`. Example values:

| State | Example reason |
|---|---|
| `WAITING_FOR_SCHEDULE` | `"Scheduled: waiting for start time (target 07:00)"` |
| `PROBING` | `"Probing: estimating SoC (≤5 min)"` |
| `CHARGING` | `"Charging to 80% (target finish 07:00)"` |
| `DONE_LATCHED_OFF` | `"Charge complete"` |
| `FAULTED` | `"Fault: max runtime exceeded"` |

### Logbook events

The adapter fires `hass.bus.async_fire("cyclesteward_event", {...})` for:

- Probe start (reason, expected duration)
- Probe result: SoC estimate + updated `computed_start_time`, or failure reason
- Session start with reason string
- Overrun: charge ran past `target_finish_time`
- Fault (existing; must now also set `session_reason`)
- Fault acknowledgment
- Morning reset trigger

Event data schema:

```python
{
    "event": str,          # e.g. "probe_start", "probe_result", "session_start"
    "reason": str,         # human-readable
    "timestamp": str,      # ISO-8601
    # additional fields per event type (see implementation order)
}
```

### Probe scheduling (in `HASensorWatcher` / coordinator)

```
probe_time = target_finish_time − estimated_max_duration − margin − probe_headroom
```

- `estimated_max_duration` = `mean + 2×stddev` from profile; fallback 4 h
- `margin` = 30 min default (user-configurable config entry)
- `probe_headroom` = 10 min fixed

Probe is bounded: `SessionController` exits `PROBING` state after a configurable
max probe duration (default 5 min) or on first stable CC-phase wattage reading.

On probe failure: fall back to `target_finish_time − max_duration − margin`; fire
logbook event with failure reason. No silent retry.

After successful probe: adapter updates `computed_start_time` passed on subsequent
ticks based on refined SoC estimate.

## Anchor artifact

`bdd/ha-adapter/finish-time-scheduling-trace.json` — a JSON trace of a full
scheduling cycle: WAITING_FOR_SCHEDULE → probe fires → probe completes with SoC
estimate → WAITING_FOR_SCHEDULE with refined start → CHARGING at computed start →
DONE_LATCHED_OFF. Produced by exercising the pure-Python coordinator + controller
with a synthetic timeline; no real HA instance needed.

## Implementation order

1. **`PROBING` state** — add to `SessionState` enum; add transition rules in
   `SessionController`: IDLE/WAITING enters PROBING on `start_probe` action;
   exits on timeout or stable reading.
2. **`computed_start_time` param** on `tick()` — plumb through controller; use
   in `WAITING_FOR_SCHEDULE` transition check.
3. **`session_reason`** — add to `TickResult`; set in every non-idle state
   transition in `SessionController`.
4. **Logbook event helper** in `HASensorWatcher` — thin wrapper around
   `hass.bus.async_fire` with the standard schema.
5. **Probe scheduling logic** in coordinator/watcher — compute `probe_time`,
   fire probe at the right wall-clock moment, handle fallback.
6. **`computed_start_time` update** in adapter after successful probe.
7. **Overrun detection** — compare `now` to `target_finish_time` when
   `DONE_LATCHED_OFF` is reached; fire logbook event if overrun.
8. **Tests** — unit tests for each step; anchor trace generated and verified.

## Proof requirements

1. Unit tests for `PROBING` state transitions green (`pytest tests/`).
2. Unit tests for `computed_start_time` WAITING_FOR_SCHEDULE transition green.
3. Unit tests for `session_reason` set on every non-idle state in `TickResult`.
4. Unit tests for probe scheduling: correct `probe_time` computed from profile +
   defaults; fallback path on failure.
5. Unit tests for logbook events fired for each transition type.
6. BDD scenarios A–F in `bdd/ha-adapter/finish-time-scheduling-bdd.md` pass with
   raw evidence.
7. Anchor trace `bdd/ha-adapter/finish-time-scheduling-trace.json` verified
   on disk: contains PROBING state, session_reason strings, logbook events, and
   DONE_LATCHED_OFF.

## Non-goals

- Profile-derived margin (stddev-based) — deferred to future enhancement.
- Multiple probes per cycle.
- Rescue probe HA adapter work (transparency requirement applies but
  low-battery-rescue is its own spec).
- Config-entry UX for `margin` and `target_finish_time` (setup-flow spec).
- Localization of `session_reason` strings.

## References

- [ADR-0012](../decisions/0012-finish-time-scheduling-and-probe-transparency.md)
- [ADR-0011](../decisions/0011-ha-entity-service-surface.md)
- [ADR-0009](../decisions/0009-charge-modes-scheduling-safe-defaults.md)
- [ADR-0005](../decisions/0005-guardrails-and-low-battery-rescue.md)
- `src/cyclesteward/session_control.py`
- `custom_components/cyclesteward/sensor.py`
- `custom_components/cyclesteward/ha_sensor_watcher.py`
