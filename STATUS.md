# STATUS.md

**Last updated:** 2026-06-09 (HA adapter slice 2 done: HASensorWatcher + ProfileStore + from_json, 34 new tests (174 total), BDD A–G evidence, arch + BDD reviews OK)
**Phase:** Phase 2 - HA adapter
**Next bounded packet:** HA adapter slice 3 — taper-completion calibration: detect CHARGE_TO_FULL sessions that complete via taper floor, run profile analysis on the live trace buffer, call ingest_full_session(), save updated CalibrationProfile to HA storage.
**Current readiness:** READY-FOR-NEXT-PACKET

## Recent sessions (rolling, last 5)

- **2026-06-09** - HA adapter slice 2 done. `CalibrationProfile.from_dict/from_json` added to all calibration dataclasses. `ProfileStore` (HA storage wrapper: load/save CalibrationProfile). `HASensorWatcher`: subscribes to HA power/temp state-change events, drives `coordinator.tick()` on each update + 60s keepalive, reads `plug_is_on` from HA state at tick time, dispatches relay TURN_ON/TURN_OFF, accumulates live power trace buffer (clears on CHARGING entry, retained through DONE_LATCHED_OFF for slice 3). `__init__.py` updated: loads profile from store on setup, starts/stops watcher. 34 new tests (174 total), ruff clean. Anchor: `bdd/ha-adapter/ha-adapter-wiring-trace.json`. BDD A–G evidence; arch review (0 violations); BDD review OK.
- **2026-06-09** - HA adapter slice 1 done. `custom_components/cyclesteward/` scaffolded: `CyclestewardCoordinator` (pure Python, no HA imports) wraps `SessionController`; exposes `charge_mode`, `session_state`, `soc_estimate`, `active_fault`, `session_reason`, `active_wh`, `relay_cycle_count`, `session_start`, `target_wattage`. All ADR-0011 entities implemented: `charge_mode` select, `session_state` + `soc_estimate` + `fault` sensors (primary), 4 diagnostic sensors, `manual_override` switch, `acknowledge_fault` button, `target_finish_time` + `morning_reset_time` time stubs. `__init__.py`, `config_flow.py` (stub), `const.py`, `manifest.json`, `services.yaml` (5 service declarations). Added `relay_cycle_count`, `session_start` to `GuardrailEvaluator`; `active_wh`, `relay_cycle_count`, `session_start`, `target_wattage` to `SessionController`. 12 new tests (140 total), ruff clean. Anchor: `bdd/ha-adapter/ha-entity-adapter-trace.json`. BDD A–J evidence; arch review (3 concerns addressed); BDD review OK.
- **2026-06-09** - ADR-0012 accepted. (A) Duration estimation: `elapsed_seconds` in `CalibrationProfile.ingest_full_session`; `estimated_duration_s()` returns mean±stddev; 4 h pessimistic default. (B) Probe cadence: fires at `target_finish_time − max_duration − margin − 10 min`; failure → pessimistic fallback + logbook event. (C) Margin: 30 min fixed default, user-configurable. (D) Dynamic start time: `tick()` gains optional `computed_start_time` param. Queue item (g) closed.
- **2026-06-09** - HA entity/service surface + probe transparency - ADR-0011 accepted: 5 primary entities (`charge_mode` select, `soc_estimate` sensor, `session_state` sensor, `fault` sensor, `manual_override` switch), 4 diagnostic sensors, 2 runtime `time` entities (`target_finish_time` + `morning_reset_time`), `acknowledge_fault` button, 5 services. Schedule is expressed as target finish time; start time is derived. ADR-0012 drafted: probe transparency requirement decided (`session_reason` attribute on `session_state` + logbook events for all automatic energizations, including ADR-0005 rescue probe); four algorithm open questions captured (duration estimation, probe cadence/fallback, margin policy, dynamic start-time + WAITING_FOR_SCHEDULE). Cross-reference added to ADR-0005. Queue item (f) closed.
- **2026-06-09** - Guardrails slice A–G. New `src/cyclesteward/guardrails.py`: `GuardrailsConfig`, `GuardrailFault`, `GuardrailResult`, `GuardrailEvaluator`. A: max-runtime fault. B: max-active-Wh fault (profile-derived 1.2× limit). C: relay chatter prevention (min_dwell + relay_cycle_limit). D: switch-command failure. E/F/G: temperature-gate + missing-reading paths verified. 32 new tests (127 total), ruff clean. BDD A–G evidence; arch + BDD reviews OK.
## Active work

### HA adapter slice 2 (DONE 2026-06-09)

- [x] `CalibrationProfile.from_dict` / `from_json` deserialization classmethods (and all nested dataclasses).
- [x] `ProfileStore`: wraps HA `Store`, loads `CalibrationProfile` on setup, saves on explicit call.
- [x] `HASensorWatcher`: subscribes to HA power/temp state-change events; drives `coordinator.tick()` on each power update + 60 s keepalive; reads `plug_is_on` from `hass.states.get()` at tick time; dispatches TURN_ON/TURN_OFF relay actions.
- [x] Live trace buffer: clears on CHARGING entry; retains through DONE_LATCHED_OFF for slice 3 calibration.
- [x] `__init__.py`: loads profile from store (or fresh if empty), creates coordinator, starts/stops watcher.
- [x] 34 new tests (174 total), ruff clean. Anchor: `bdd/ha-adapter/ha-adapter-wiring-trace.json`. BDD A–G evidence; arch review (0 violations); BDD review OK.

### HA adapter slice 1 (DONE 2026-06-09)

- [x] `CyclestewardCoordinator` (pure Python, no HA imports): wraps `SessionController`, exposes all entity-facing properties, listener subscription.
- [x] `charge_mode` select, `session_state` + `soc_estimate` + `fault` primary sensors, `manual_override` switch, `acknowledge_fault` button (all primary entities per ADR-0011).
- [x] `target_finish_time` + `morning_reset_time` time entity stubs (scheduling logic deferred to slice 2).
- [x] 4 diagnostic sensors: `active_wh`, `target_wattage`, `relay_cycles`, `session_start`.
- [x] `manifest.json`, `__init__.py`, `config_flow.py` (minimal stub), `const.py`, `services.yaml` (5 service declarations).
- [x] Added diagnostic properties to `GuardrailEvaluator` + `SessionController` (read-only).
- [x] 12 new tests (140 total), ruff clean. Anchor: `bdd/ha-adapter/ha-entity-adapter-trace.json`. BDD A–J evidence; arch review (3 concerns addressed); BDD review OK.

### Guardrails slice A–G (DONE 2026-06-09)

- [x] `GuardrailsConfig`, `GuardrailFault`, `GuardrailResult`, `GuardrailEvaluator` in `src/cyclesteward/guardrails.py`.
- [x] A: max-runtime fault → TURN_OFF + FAULTED + event_log entry.
- [x] B: max-active-Wh fault (profile-derived 1.2× fallback; idle_w subtracted; disabled when neither config nor profile provides limit).
- [x] C: relay chatter prevention — min_dwell suppresses rapid toggle; relay_cycle_limit caps total transitions; initial TURN_ON never suppressed; suppression recorded in reason + fault field.
- [x] D: switch-command failure — confirmation check runs before DONE_LATCHED_OFF short-circuit; morning reset wins over pending confirmation (intentional; documented by test).
- [x] E/F/G: freeze lockout, heat delay, missing-reading safety verified in guardrails test suite.
- [x] `tick()` extended with `plug_is_on: Optional[bool] = None`; `TickResult` extended with `fault: Optional[GuardrailFault]`.
- [x] 32 new tests (127 total), ruff clean. Anchor artifact: `bdd/guardrails/guardrails-trace.json`. BDD A–G evidence written; architecture review OK; BDD review OK.

### Session-control slice A–H (DONE 2026-06-09)

- [x] Pure state machine: `ChargeMode`, `SessionState`, `SessionAction`, `SocEstimate`, `TickResult`.
- [x] Wattage-threshold cutoff on first crossing; no double-gate; DONE_LATCHED_OFF latch.
- [x] Off-by-default modes; morning reset (once per day); mutually exclusive modes.
- [x] Scheduled start (WAITING_FOR_SCHEDULE → CHARGING at or after start time).
- [x] Manual override → CHARGING while cutoff still applies.
- [x] Charge-to-full taper-floor detection with configurable duration and timer reset.
- [x] SoC estimation from CC wattage: `uncertainty_pct`, `low_confidence`, transition note.
- [x] Temperature compensation (linear shift), freeze lockout (hard stop), heat delay (non-fault).
- [x] Missing/non-numeric readings hold safely with no cutoff misfire.
- [x] 31 tests, anchor artifact (`session-control-trace.json`), BDD A–H evidence, architecture + BDD review OK.

### Profile-calibration slice F-H (DONE 2026-06-09)

- [x] Opportunistic full-session detection: `classify_opportunistic_session()` accepts a near-anchor completed session (F) and stores `(temperature_c, active_wh)` in `temperature_observations`.
- [x] Inrush settling (F2): `watts_at_low` uses the first stable consecutive pair, not the onset sample.
- [x] Rejection: session starting too far from anchor → not promoted (G).
- [x] Rejection: incomplete/CALIBRATION_DISTRUST session → not promoted (G2).
- [x] Relay-cutoff disambiguation (G3): `taper_floor_w` set to None + TAPER_AMBIGUOUS warning when floor > 35% of peak.
- [x] HA-history import (H): demonstrated via real-swoop-asm-charge.csv; no homeassistant import.
- [x] Both carried real-data artifacts fixed: Swoop onset 65.7→69.7 W settled; Swoop relay cutoff detected.
- [x] BDD evidence F/F2/G/G2/G3/H written; architecture review OK; review-bdd-evidence verdict OK.

### Profile-calibration slice A-E (DONE 2026-06-09)

- [x] CalibrationProfile model with `ingest_full_session`, `ingest_partial_session`, `target_wattage`, `to_json`.
- [x] SocReport stores coarse intervals (dots, display_empty), never exact percentages.
- [x] Partial observations do not overwrite the full active-Wh denominator.
- [x] Bad-data sessions (CALIBRATION_DISTRUST) are stored but not promoted to trusted; state → CALIBRATING.
- [x] Rated capacity → overhead_ratio with `confidence: low` and uncertainty note.
- [x] BDD evidence A-E written and review-bdd-evidence verdict OK.

### Fixture analyzer anchor artifact (DONE 2026-06-08)

- [x] Define the CSV fixture input schema in code and tests.
- [x] Implement idle-subtracted active Wh integration for one low-to-full fixture (calibration aid).
- [x] Extract the wattage anchors: `watts_at_low` (CC-start), `watts_at_transition` (CC->CV peak), `taper_floor_w`.
- [x] Detect basic curve landmarks: start power band, peak/knee candidate, taper, completion threshold.
- [x] Emit a profile-summary JSON artifact (anchors + active Wh + landmarks) and read it back in evidence.
- [x] Produce BDD evidence for `bdd/anchor/fixture-analyzer-anchor-bdd.md`.

## Open queue (non-blocking)

- (a) Decide the Home Assistant domain slug (name resolved: CycleSteward; `docs/research/naming.md`).
- (b) Tune default values for the temperature thresholds/coefficient (ADR-0008) and the morning-reset/scheduled-start times (ADR-0009).
- (f) ~~Decide the remaining Home Assistant entity/service surface after the core model is proven.~~ DONE — ADR-0011 accepted 2026-06-09.
- (g) ~~ADR-0012: Resolve open questions A–D.~~ DONE — ADR-0012 accepted 2026-06-09. HA adapter slice unblocked.
- (c) Research how often users should be prompted for full calibration/balancing charges.
- (d) Decide default probe cadence and relay-cycle limits for low-battery detection.
- (e) Grow the charge-session fixture library further (seeded: clean/noisy/interrupted/malformed/unknown synthetics + one real Swoop ASM session; want more real sessions at varied temperatures and a full taper-to-completion session).

## Blockers

- None for the first anchor slice. Later Home Assistant integration slices need decisions on entity naming, setup-flow UX, and persistent storage schema.
