---
status: draft
date: 2026-06-09
depends-on-adrs: [0006, 0011, 0012]
---

# HA adapter: live sensor wiring + profile persistence

## Status

Draft. Defines slice 2 of the HA adapter: wiring the proven pure-Python coordinator to real HA sensor entities and persistent storage.

## Related docs

- [bdd/ha-adapter/ha-adapter-wiring-bdd.md](../../bdd/ha-adapter/ha-adapter-wiring-bdd.md) — observable behavior
- [docs/specs/ha-entity-adapter.md](ha-entity-adapter.md) — slice 1: coordinator + entity surface
- [docs/decisions/0006-pure-core-before-ha.md](../decisions/0006-pure-core-before-ha.md)
- [docs/decisions/0011-home-assistant-entity-and-service-surface.md](../decisions/0011-home-assistant-entity-and-service-surface.md)
- [docs/decisions/0012-finish-time-scheduling-and-probe-transparency.md](../decisions/0012-finish-time-scheduling-and-probe-transparency.md)
- [STATUS.md](../../STATUS.md)

## Context

Slice 1 scaffolded `CyclestewardCoordinator` (pure Python) and the ADR-0011 entity surface.
The coordinator exposes `tick()`, `set_mode()`, and listener subscription — but nothing calls
`tick()` yet: there is no connection to real HA sensor entities, and no profile is persisted
between restarts.

This slice wires the gap:

1. **`HASensorWatcher`** — subscribes to HA state-change events for the configured power (and
   optionally temperature) entity; calls `coordinator.tick()` on each power update and on a
   keepalive interval; acts on relay actions (TURN_ON / TURN_OFF) by calling HA services on
   the configured plug entity. Accumulates a live power trace `(timestamp, power_w)` during
   each session for the next slice to consume.
2. **`ProfileStore`** — wraps `homeassistant.helpers.storage.Store`; loads a saved
   `CalibrationProfile` on integration setup. Save is implemented but not yet wired to a
   trigger (profile update and save belong to slice 3: taper-completion calibration).

The coordinator remains pure Python with no HA imports; all HA-import code lives in the watcher
and store layers (ADR-0006).

## Behavior contract

### HASensorWatcher

```python
class HASensorWatcher:
    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: CyclestewardCoordinator,
        power_entity_id: str,
        plug_entity_id: str,
        temp_entity_id: Optional[str] = None,
        keepalive_interval_s: int = 60,
    ) -> None: ...

    async def async_start(self) -> None:
        """Register state-change listeners and keepalive timer."""

    async def async_stop(self) -> None:
        """Unregister all listeners and cancel keepalive timer."""
```

**State-change behavior:**
- Power entity state change → parse state to `float` (None if "unavailable", "unknown", or
  non-numeric) → call `coordinator.tick(power_w, cached_temp_c, now, plug_is_on=_plug_state())`.
- Temperature entity state change → update `cached_temp_c` (None if invalid); does not trigger
  a tick directly.
- Keepalive fires every `keepalive_interval_s` → call `coordinator.tick(cached_power_w, cached_temp_c, now, plug_is_on=_plug_state())`.

`plug_is_on` is read from HA state at tick time: `hass.states.get(plug_entity_id).state == "on"`;
returns `None` if the entity is unavailable or not yet seen.

**Trace accumulation:**
- On each tick where `power_w is not None`, append `(now, power_w)` to an internal trace buffer.
- Clear the buffer when the coordinator transitions into CHARGING state (new session start).
- Retain the buffer through DONE_LATCHED_OFF so slice 3 can read it for calibration analysis.

**Relay action dispatch:**
- `TickResult.action == TURN_ON` → `hass.services.async_call("homeassistant", "turn_on", {"entity_id": plug_entity_id})`.
- `TickResult.action == TURN_OFF` → `hass.services.async_call("homeassistant", "turn_off", {"entity_id": plug_entity_id})`.
- `TickResult.action == NONE` → no service call.

### ProfileStore

```python
class ProfileStore:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None: ...

    async def async_load(self) -> Optional[CalibrationProfile]:
        """Return the saved profile, or None if no data found."""

    async def async_save(self, profile: CalibrationProfile) -> None:
        """Persist the profile to HA storage."""
```

Storage key: `cyclesteward.<entry_id>`.

Profile JSON format: `CalibrationProfile.to_json()` output; reconstructed via a new
`CalibrationProfile.from_json(data: dict)` classmethod added to `calibration.py`.

On setup (`async_setup_entry`): load profile from store; if None, construct a fresh
`CalibrationProfile` from config-entry data.

Save trigger: not wired in this slice. Slice 3 will call `async_save` after a
taper-completion session updates the profile via `ingest_full_session()`.

### Config entry data keys used

| Key | Required | Description |
|---|---|---|
| `charger_label` | yes | Profile identity key |
| `battery_label` | yes | Profile identity key |
| `meter_id` | yes | Profile identity key |
| `power_entity_id` | yes | HA entity ID reporting watts |
| `plug_entity_id` | yes | HA switch entity controlling AC power |
| `temp_entity_id` | no | Optional temperature sensor entity ID |
| `rated_capacity_wh` | no | Profile capacity hint |

## Anchor artifact

`bdd/ha-adapter/ha-adapter-wiring-trace.json` — JSON trace of a complete wiring sequence:

1. Profile loaded from store (watts_at_transition = 125.5 W).
2. Power entity state change received (80 W); `plug_is_on` read from HA state = False.
3. `coordinator.tick()` called; action = TURN_ON; plug turn-on service call recorded.
4. Temperature entity state change received (22.5 °C).
5. Second power update (90 W) → tick called with temp_c=22.5; trace buffer = [(t1,80.0),(t2,90.0)].
6. Session reaches DONE_LATCHED_OFF; trace buffer retained (not cleared).

## Proof requirements

1. Unit tests for `HASensorWatcher` (mocked HA state events; relay dispatch; trace accumulation verified) — green.
2. Unit tests for `ProfileStore` load path + save/load round-trip in isolation — green.
3. `CalibrationProfile.from_json()` classmethod exists and round-trips `to_json()` output faithfully.
4. Anchor artifact `bdd/ha-adapter/ha-adapter-wiring-trace.json` on disk with expected fields.
5. `ruff check .` clean.
6. Architecture review passes against invariants.
7. BDD evidence review passes.

## Implementation order

1. Add `CalibrationProfile.from_json()` classmethod to `src/cyclesteward/calibration.py`.
2. Implement `ProfileStore` in `custom_components/cyclesteward/profile_store.py`.
3. Update `async_setup_entry` in `__init__.py` to load profile from store on startup.
4. Implement `HASensorWatcher` in `custom_components/cyclesteward/watcher.py` with:
   a. State-change listener for power entity; `plug_is_on` read from HA state at tick time.
   b. Optional state-change listener for temperature entity.
   c. Keepalive timer for scheduling/guardrails ticks when plug is off.
   d. Relay dispatch on TURN_ON / TURN_OFF.
   e. Trace buffer: append on each valid power tick; clear on CHARGING entry; retain on DONE_LATCHED_OFF.
5. Wire `HASensorWatcher` into `async_setup_entry` / `async_unload_entry`.
6. Write tests and produce anchor trace JSON.
7. Write BDD evidence.

## Non-goals

- Profile update on session completion (slice 3: taper-completion calibration).
- Profile save trigger (slice 3).
- Config flow UI (still a stub; full setup-flow spec is separate).
- Scheduling probe logic (ADR-0012; future slice).
- HA logbook events for session transitions (future slice).
- Calibration service handlers (declared in services.yaml; still stubbed).
- HA entity state attributes beyond what slice 1 already wires.

## References

- `custom_components/cyclesteward/coordinator.py` (pure Python; interface unchanged)
- `src/cyclesteward/calibration.py` (add `from_json`)
- `src/cyclesteward/session_control.py` (SessionState.CHARGING for trace-buffer reset)
- ADR-0006, ADR-0011, ADR-0012
