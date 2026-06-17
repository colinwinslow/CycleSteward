---
status: draft
date: 2026-06-16
depends-on-adrs: [0006, 0009, 0011, 0012]
---

# Config-entry plumbing: make a real install functional

## Status

Draft. Defines the contract surface for config-entry plumbing per ADR-0011
(entity/service surface) and ADR-0012 (derived start time). Closes review
finding F1 (`docs/research/codebase-review.md`).

## Related docs

- [bdd/ha-adapter/config-entry-plumbing-bdd.md](../../bdd/ha-adapter/config-entry-plumbing-bdd.md) — observable behavior
- [STATUS.md](../../STATUS.md) — current phase and active work

## Context

Today the integration loads but does nothing useful in a real Home Assistant
install:

- `config_flow.py` collects profile-identity fields
  (`charger_label`, `battery_label`, `meter_id`, `rated_capacity_wh`) but **not**
  the entity IDs the watcher needs. `__init__.py` only starts `HASensorWatcher`
  when `power_entity_id` **and** `plug_entity_id` are present in `entry.data`.
  Since the config flow never collects them, the watcher never starts — the
  integration is inert.
- `time.py`'s `TargetFinishTimeEntity` and `MorningResetTimeEntity` hold a local
  `_value` and write HA state, but never call `watcher.set_target_finish_time()`
  or round-trip the morning-reset time into `SessionConfig`. Setting either time
  in the UI has no effect on behavior.
- `services.yaml` declares five services (`set_mode`, `manual_override`,
  `start_calibration_session`, `import_history`, `acknowledge_fault`) but none
  are registered with `hass.services.async_register`. Calling any of them fails.

This packet wires the three seams so that a fresh install can be configured,
the watcher starts, the schedule entities drive behavior, and the declared
service surface either works or is trimmed to what exists.

## Behavior contract

### 1. Config flow collects the operational inputs

`async_step_user` schema gains (in addition to the existing identity fields):

| Field | Type | Required | Notes |
|---|---|---|---|
| `power_entity_id` | entity selector (`sensor`, device_class `power`) | yes | watcher power source |
| `plug_entity_id` | entity selector (`switch`) | yes | controlled relay |
| `temp_entity_id` | entity selector (`sensor`, device_class `temperature`) | no | optional temp compensation |
| `target_soc_dots` | int 0–5 (or coarse selector) | no | coarse target per invariant 6 / ADR-0004 |
| `margin_s` | int seconds | no, default matches `watcher._DEFAULT_MARGIN_S` | scheduling safety margin |

Entity selectors are used so the user picks existing entities rather than
typing IDs. The created entry's `data` carries every field; `__init__.py`'s
existing `power_entity_id and plug_entity_id` gate then starts the watcher.

`margin_s` is threaded into the `HASensorWatcher(...)` constructor at setup.

### 2. Time entities round-trip into behavior

- `TargetFinishTimeEntity.async_set_value(value: time)`: convert the
  time-of-day to the **next occurrence** as a timezone-aware `datetime`, then
  call `watcher.set_target_finish_time(dt)`. The watcher already recomputes the
  pessimistic start time and resets per-cycle probe/overrun state on that call.
  At setup the stored/default time is applied once so the schedule is live
  without a manual edit.
- `MorningResetTimeEntity.async_set_value(value: time)`: round-trip the
  time-of-day into `SessionConfig.morning_reset_time`. This requires a setter on
  `CyclestewardCoordinator` (e.g. `set_morning_reset_time(t: time)`) that
  mutates the controller's config; the controller's existing arming logic picks
  it up on the next tick.

Time entities reach the watcher via `hass.data[DOMAIN][f"{entry_id}.watcher"]`
and the coordinator via `hass.data[DOMAIN][entry_id]` (D1). When no watcher is
present (entity IDs not configured), the time-set is a no-op beyond storing the
value.

### 3. Service registration

Register the five declared services in `async_setup` (domain-level, once) or
`async_setup_entry`, each resolving `entry_id` → coordinator and calling the
matching coordinator method:

| Service | Coordinator call |
|---|---|
| `set_mode` | `set_mode(ChargeMode(mode))` |
| `manual_override` | `manual_override_on()` / off path |
| `acknowledge_fault` | `acknowledge_fault()` |
| `start_calibration_session` | (calibration entry path) |
| `import_history` | (CSV import path) |

Per D2, this slice keeps only `set_mode`, `manual_override`, and
`acknowledge_fault`. `start_calibration_session` and `import_history` are
**trimmed from `services.yaml`** — they return with their feature slices. The
slice ships only services that actually execute.

### 4. Timezone discipline

All scheduling datetimes are timezone-aware in HA's configured zone. Time-of-day
→ datetime conversion uses `homeassistant.util.dt` (`dt_util.now()`,
`dt_util.start_of_local_day()`), never naive `datetime.now()`. The "next
occurrence" rule (D3): if the target time-of-day today is already past
`dt_util.now()`, use tomorrow's date; otherwise today's. This applies uniformly
to target-finish and morning-reset.

## Anchor artifact

A simulated entry-setup trace: a JSON fixture describing config-entry `data`
(entity IDs + schedule times), fed through a test that drives
`async_setup_entry` against a mock `hass`, and asserts (a) the watcher started,
(b) `set_target_finish_time` received the correct next-occurrence datetime, and
(c) a registered service call reaches the coordinator. Output is the test's
captured calls, read back in evidence.

## Implementation order

1. **Config-flow schema** — add entity selectors + scheduling fields; entry
   `data` round-trips. (Unit test on the flow.)
2. **Watcher starts from a real entry** — simulated `async_setup_entry` test
   confirms the watcher starts when entity IDs are present and `margin_s`
   threads through.
3. **Time entities → behavior** — coordinator `set_morning_reset_time`; time→
   next-occurrence-datetime helper; entities call into watcher/coordinator;
   setup applies stored values once.
4. **Service registration** — register the kept services; trim the rest from
   `services.yaml`.
5. **Timezone audit** — confirm all conversions use `dt_util`; add a regression
   test for the next-occurrence rule across the day boundary.

## Proof requirements

1. Unit tests: config-flow schema accepts entity IDs and produces entry `data`;
   green in `tests/`.
2. Simulated `async_setup_entry` test: watcher starts; `margin_s` threaded.
3. Time-entity round-trip tests: `set_target_finish_time` receives the correct
   aware next-occurrence datetime; `morning_reset_time` reaches `SessionConfig`.
4. Service-registration test: each kept service is registered and its call
   reaches the coordinator; `services.yaml` contains only kept services.
5. BDD scenarios in `bdd/ha-adapter/config-entry-plumbing-bdd.md` pass with raw
   evidence on disk.
6. `python -m ruff check .` clean; full suite green.

## Non-goals

- The larger setup-flow wizard / options flow (SoC reporting mode, temperature
  parameters, guardrail defaults) — that is queued packet #7 (`setup-flow.md`).
- Implementing calibration/import coordinator paths from scratch if they don't
  exist — those services are trimmed here, not built.
- The stale-meter guardrail (F5, queued packet #3) and probe CC/CV
  disambiguation (F7).
- Real-HA smoke test (queued packet #4) — this slice stays against mocks.

## Decisions (resolved 2026-06-16)

- **D1 — entity→watcher path. RESOLVED:** time entities reach the watcher and
  coordinator via `hass.data[DOMAIN]` lookup keyed by `entry_id` (coordinator)
  and `f"{entry_id}.watcher"` (watcher) — consistent with the existing
  `__init__.py` storage pattern. No new reference threading through platform
  setup.
- **D2 — service surface. RESOLVED:** trim to the three services with a working
  coordinator path — `set_mode`, `manual_override`, `acknowledge_fault`. Remove
  `start_calibration_session` and `import_history` from `services.yaml`; they
  return with their feature slices. No non-functional services ship.
- **D3 — timezone source. RESOLVED:** `homeassistant.util.dt` is the single tz
  authority; all scheduling datetimes are aware in HA's configured zone.
  Next-occurrence rule: if the target time-of-day is already past
  `dt_util.now()`, use tomorrow's date, else today's — applied to both
  target-finish and morning-reset.

## References

- ADR-0011 — HA entity/service surface
- ADR-0012 — derived start time / target finish time
- ADR-0009 — morning reset / scheduled start defaults
- ADR-0006 — core-before-HA-plumbing (this layer owns only HA wiring)
- `docs/research/codebase-review.md` — finding F1
