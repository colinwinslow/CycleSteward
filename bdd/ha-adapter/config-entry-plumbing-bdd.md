# Config-entry plumbing: make a real install functional — BDD

## Status

Draft. Paired with [docs/specs/config-entry-plumbing.md](../../docs/specs/config-entry-plumbing.md).

## Why this BDD exists

A fresh install must be configurable end-to-end: the user picks the power/plug/
temperature entities, the watcher starts, the schedule entities actually move
behavior, and the declared services either work or are gone. This BDD pins down
the observable "the integration is no longer inert" behavior.

## Scenarios

### Scenario A — happy path: config flow collects entity IDs and entry data round-trips

**Given** a user runs the CycleSteward config flow
**When** they select a power sensor, a switch (plug), and submit (optionally a
temperature sensor, target SoC dots, and margin seconds)
**Then** the created config entry's `data` contains `power_entity_id`,
`plug_entity_id`, and the optional fields — inspectable as the entry-data JSON
captured in evidence.

### Scenario B — watcher starts from a real entry

**Given** a config entry whose `data` carries `power_entity_id` and
`plug_entity_id`
**When** `async_setup_entry` runs against a mock `hass`
**Then** an `HASensorWatcher` is created and `async_start()` is called, with
`margin_s` from the entry threaded into the constructor — captured as the
watcher's recorded init args + start call.

### Scenario C — target-finish time drives the schedule (next-occurrence, tz-aware)

**Given** a started watcher and a `TargetFinishTimeEntity`
**When** the user sets the target finish time to a time-of-day
**Then** the watcher's `set_target_finish_time` receives a timezone-aware
`datetime` at the **next occurrence** of that time-of-day (today if still ahead,
else tomorrow), and the watcher's `computed_start_time` becomes the recomputed
pessimistic start — both shown in evidence.

### Scenario D — morning-reset time round-trips into SessionConfig

**Given** a started coordinator and a `MorningResetTimeEntity`
**When** the user sets the morning-reset time-of-day
**Then** `SessionConfig.morning_reset_time` reflects the new value and the
controller arms/fires the reset against it on the next tick — shown as the
config value before/after plus a tick observation.

### Scenario E — declared services are registered and reach the coordinator

**Given** a set-up config entry
**When** each kept service (`set_mode`, `manual_override`, `acknowledge_fault`)
is called with the entry's `entry_id`
**Then** the corresponding coordinator method runs and the observable state
changes (e.g. `charge_mode` after `set_mode`) — captured as before/after
coordinator state.

### Scenario F — trimmed services are not declared-but-dead

**Given** the shipped `services.yaml`
**When** the file is read
**Then** it declares only services with a working backing path; any service
without a coordinator path this slice is absent (no declared-but-unregistered
service remains) — shown as the service list diff.

### Scenario G — timezone discipline: no naive datetimes in scheduling

**Given** the schedule conversion path
**When** a time-of-day is converted to a start/finish datetime
**Then** the result is timezone-aware (via `homeassistant.util.dt`), and the
day-boundary case (target time already past "now") rolls to the next day —
shown as the aware datetime and its `tzinfo` across the boundary case.

## Evidence

The implementing slice produces an evidence file at
`bdd/ha-adapter/config-entry-plumbing-evidence.md` containing raw outputs (not
summaries) for each scenario: captured entry-data JSON, recorded
watcher/coordinator calls, before/after state, and the `services.yaml` content.
