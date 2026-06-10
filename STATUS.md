# STATUS.md

**Last updated:** 2026-06-09 (HA adapter slice done: coordinator + full ADR-0011 entity surface scaffolded, 12 tests, BDD A–J evidence, architecture + BDD reviews OK)
**Phase:** Phase 2 - HA adapter
**Next bounded packet:** HA adapter slice 2 — live sensor wiring (subscribe to HA power/temp entities, drive coordinator.tick() on polling interval) + profile persistence (load/save CalibrationProfile via HA storage).
**Current readiness:** READY-FOR-NEXT-PACKET

## Recent sessions (rolling, last 5)

- **2026-06-09** - HA adapter slice 1 done. `custom_components/cyclesteward/` scaffolded: `CyclestewardCoordinator` (pure Python, no HA imports) wraps `SessionController`; exposes `charge_mode`, `session_state`, `soc_estimate`, `active_fault`, `session_reason`, `active_wh`, `relay_cycle_count`, `session_start`, `target_wattage`. All ADR-0011 entities implemented: `charge_mode` select, `session_state` + `soc_estimate` + `fault` sensors (primary), 4 diagnostic sensors, `manual_override` switch, `acknowledge_fault` button, `target_finish_time` + `morning_reset_time` time stubs. `__init__.py`, `config_flow.py` (stub), `const.py`, `manifest.json`, `services.yaml` (5 service declarations). Added `relay_cycle_count`, `session_start` to `GuardrailEvaluator`; `active_wh`, `relay_cycle_count`, `session_start`, `target_wattage` to `SessionController`. 12 new tests (140 total), ruff clean. Anchor: `bdd/ha-adapter/ha-entity-adapter-trace.json`. BDD A–J evidence; arch review (3 concerns addressed); BDD review OK.
- **2026-06-09** - ADR-0012 accepted: finish-time scheduling algorithm fully decided. (A) Duration estimation: store `elapsed_seconds` in `CalibrationProfile.ingest_full_session`; `estimated_duration_s()` returns mean±stddev; 4 h pessimistic default before profile has data. (B) Probe cadence: fires at `target_finish_time − max_duration − margin − 10 min headroom`; failure → pessimistic fallback + logbook event; scheduling probe shares infrastructure with rescue probe (ADR-0005); `PROBING` state added to `SessionController`. (C) Margin: 30 min fixed default, user-configurable in config entry; overrun is logbook event not fault. (D) Dynamic start time: `tick()` gains optional `computed_start_time` param; before probe runs, defaults to `target_finish_time − max_duration − margin`. Queue item (g) closed.
- **2026-06-09** - HA entity/service surface + probe transparency - ADR-0011 accepted: 5 primary entities (`charge_mode` select, `soc_estimate` sensor, `session_state` sensor, `fault` sensor, `manual_override` switch), 4 diagnostic sensors, 2 runtime `time` entities (`target_finish_time` + `morning_reset_time`), `acknowledge_fault` button, 5 services. Schedule is expressed as target finish time; start time is derived. ADR-0012 drafted: probe transparency requirement decided (`session_reason` attribute on `session_state` + logbook events for all automatic energizations, including ADR-0005 rescue probe); four algorithm open questions captured (duration estimation, probe cadence/fallback, margin policy, dynamic start-time + WAITING_FOR_SCHEDULE). Cross-reference added to ADR-0005. Queue item (f) closed.
- **2026-06-09** - Guardrails slice A–G - New `src/cyclesteward/guardrails.py`: `GuardrailsConfig`, `GuardrailFault`, `GuardrailResult`, `GuardrailEvaluator`. Integrates into `SessionController` via `guardrails_config` param + `plug_is_on` param on `tick()` + `fault` field on `TickResult`. A: max-runtime fault (TURN_OFF + FAULTED + event_log). B: max-active-Wh fault (profile-derived 1.2× limit; idle_power_w subtracted; disabled when neither config nor profile provides limit). C: relay chatter prevention (min_dwell suppresses rapid toggle; relay_cycle_limit caps total transitions; initial TURN_ON never suppressed). D: switch-command failure (confirmation check runs before DONE_LATCHED_OFF short-circuit; morning reset wins over pending confirmation — intentional). E/F/G: existing temperature-gate + missing-reading paths verified. 32 new tests (127 total), ruff clean. Anchor artifact: `bdd/guardrails/guardrails-trace.json`. BDD A–G evidence written; architecture review OK; BDD review OK.
- **2026-06-09** - Session-control slice A–H - Pure state machine (`src/cyclesteward/session_control.py`): `ChargeMode`, `SessionState`, `SessionAction`, `SocEstimate`, `TickResult`, `TemperatureConfig`, `SessionConfig`, `SessionController`. Implements wattage-threshold cutoff (first crossing, no double-gate), DONE_LATCHED_OFF, off-by-default modes, morning reset, scheduled start, manual override (still honors cutoff), charge-to-full taper-floor detection, SoC estimation from CC wattage (calibrated: ±10 %, uncalibrated: ±20 % + low_confidence), temperature compensation (linear coeff), freeze lockout (hard stop) and heat delay (non-fault, with deadline). 31 new tests (96 total), ruff clean. Anchor artifact: `bdd/session-control/session-control-trace.json`. BDD A–H evidence written; architecture review OK; BDD review OK.
## Active work

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
