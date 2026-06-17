# Specs

One spec per shippable feature: `docs/specs/<slug>.md`, paired with a BDD file
at `bdd/<feature>/<slug>-bdd.md`.

## Current specs

- `fixture-analyzer-anchor` - pure-core CSV-to-profile anchor artifact (draft)
- `setup-flow` - Home Assistant setup and profile creation UX (draft)
- `profile-calibration` - calibration and learned profile behavior (draft)
- `session-control` - charge-to-target, modes, and scheduling (draft)
- `low-battery-rescue` - probe and rescue behavior for depleted displays (draft)
- `guardrails` - automation guardrails and fault behavior (draft)
- `ha-entity-adapter` - HA coordinator + primary entity surface, first adapter slice (active)
- `ha-adapter-wiring` - live sensor wiring, relay dispatch, trace buffer, profile persistence (active)
- `ha-calibration-ingestion` - taper-completion calibration ingestion with temperature correction (active)
- `finish-time-scheduling` - probe cadence, dynamic start time, PROBING state, logbook events, overrun detection (active)
- `config-entry-plumbing` - config-flow entity selection, time-entity round-trip, service registration; closes review F1 (implemented)
- `stale-meter-guardrail` - STALE_METER fault on prolonged blind-while-charging; closes review F5 (accepted)
- `real-ha-smoke-test` - loads the integration in genuine Home Assistant (config flow, entity register, unload) + hassfest CI; closes packet 4 (accepted)
