---
status: active
date: 2026-06-09
depends-on-adrs: [0006, 0011, 0012]
---

# Home Assistant entity adapter — coordinator + primary entities

## Status

Active. First HA adapter slice.

## Related docs

- [bdd/ha-adapter/ha-entity-adapter-bdd.md](../../bdd/ha-adapter/ha-entity-adapter-bdd.md)
- [docs/decisions/0011-home-assistant-entity-and-service-surface.md](../decisions/0011-home-assistant-entity-and-service-surface.md)
- [docs/decisions/0012-finish-time-scheduling-and-probe-transparency.md](../decisions/0012-finish-time-scheduling-and-probe-transparency.md)
- [STATUS.md](../../STATUS.md)

## Context

The pure CycleSteward core is proven. This slice scaffolds
`custom_components/cyclesteward/` and wires the ADR-0011 entity/service surface
to `SessionController` via a pure-Python coordinator.

## Scope

**This slice:**
- `CyclestewardCoordinator` — pure Python, no HA imports; wraps
  `SessionController`, exposes entity-facing properties and listener
  subscription
- `charge_mode` select entity (primary; ADR-0011)
- `session_state` sensor entity with `session_reason` attribute (primary;
  ADR-0011, ADR-0012 transparency)
- `soc_estimate` sensor with `uncertainty_pct` / `low_confidence` attributes
  (primary; ADR-0011)
- `fault` sensor entity (primary; ADR-0011)
- `manual_override` switch entity (primary; ADR-0011)
- `acknowledge_fault` button entity (recovery; ADR-0011)
- `target_finish_time` and `morning_reset_time` time entities (stubs; full
  scheduling logic is a future slice)
- Diagnostic sensors: `active_wh`, `target_wattage`, `relay_cycles`,
  `session_start` (thin wrappers; no test coverage this slice)
- HA component skeleton: `manifest.json`, `__init__.py`, `const.py`,
  `config_flow.py` (minimal stub), `services.yaml` (declarations only)

**Not this slice:**
- Live HA sensor subscription (wiring power_w from HA state to coordinator.tick)
- Profile persistence (stored in HA config entry, loaded on setup)
- Full config flow wizard (setup-flow spec)
- Scheduling probe logic (future slice)
- Service handler implementations (declared in services.yaml, handlers stubbed)

## Coordinator design

`CyclestewardCoordinator` is a pure Python class — no `homeassistant` imports —
that:

1. Holds a `SessionController` instance
2. Exposes `charge_mode`, `session_state`, `last_tick_result`, `soc_estimate`
   as read properties
3. Exposes `set_mode()`, `manual_override_on()`, `acknowledge_fault()`,
   `tick()` as write methods
4. Maintains a listener list: `subscribe(fn)` → unsubscribe callable; every
   tick or mode change notifies all listeners

HA entities read from coordinator properties and call coordinator methods.
They register a listener via `subscribe()` to receive `schedule_update_ha_state()`
notifications.

## session_reason attribute

Per ADR-0012, `session_state` sensor carries a `session_reason` attribute at all
times. Value is `TickResult.reason` from the last tick; empty string before the
first tick. This provides the probe-transparency requirement without a separate
entity.

## Anchor artifact

`bdd/ha-adapter/ha-entity-adapter-trace.json` — JSON trace of a coordinator
sequence: `set_mode(CHARGE_TO_TARGET)` → tick (TURN_ON) → tick (CHARGING with
SoC) → tick (TURN_OFF / DONE_LATCHED_OFF). Read back by the implementing test.

## Proof requirements

1. Pure Python tests for `CyclestewardCoordinator` scenarios A-H pass.
2. Syntax-validity check for all `custom_components/cyclesteward/*.py` passes.
3. Anchor artifact `bdd/ha-adapter/ha-entity-adapter-trace.json` on disk with
   expected state sequence.
4. Architecture review passes against invariants.
5. BDD evidence review passes.

## Non-goals

- HA config-flow UI (setup-flow spec).
- Calibration services (import_history, start_calibration_session).
- Scheduling probe (future slice per ADR-0012).
- OEM charger protocol integration.

## References

- `src/cyclesteward/session_control.py`
- `src/cyclesteward/guardrails.py`
- `src/cyclesteward/calibration.py`
- ADR-0006, ADR-0011, ADR-0012
