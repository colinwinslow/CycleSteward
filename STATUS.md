# STATUS.md

**Last updated:** 2026-06-16 (config-entry-plumbing implemented — packet 2/F1 done; config flow, time entities, services wired; 24 new tests; reviews OK)
**Phase:** Phase 2 - HA adapter
**Next bounded packet:** Stale-meter guardrail (F5; invariant 7) — queued packet 3 below. Watcher tracks last power-update age, passes `None` when stale; optional fault on prolonged staleness while CHARGING. No spec yet.
**Current readiness:** READY-FOR-NEXT-PACKET (packet 2 complete, verified, reviewed)

## Recent sessions (rolling, last 5)

- **2026-06-16** - Config-entry plumbing implemented (packet 2 / review F1; `docs/specs/config-entry-plumbing.md` now `implemented`). Wired the three dead seams: (1) `config_flow.py` collects `power/plug/temp_entity_id` entity selectors + `target_soc_dots` + `margin_s`; (2) `time.py` `TargetFinishTimeEntity`/`MorningResetTimeEntity` now round-trip into `watcher.set_target_finish_time()` (via pure `schedule.next_occurrence`) and `coordinator.set_morning_reset_time()`, reached via `hass.data[DOMAIN]` (D1); (3) `services.py` registers `set_mode`/`manual_override`/`acknowledge_fault` (deferred HA imports), `services.yaml` trimmed to those 3 (D2). `__init__.async_setup_entry` threads `margin_s`, applies the configured target-finish + morning-reset at setup, registers/unregisters services. New pure `schedule.py` (`next_occurrence`, tz-aware via `dt_util`, D3). New `SessionController.set_morning_reset_time` + `morning_reset_time` getter; coordinator delegates. Test harness `tests/ha_stubs.py` stubs HA + voluptuous session-wide (conftest) so the real adapter modules run offline. 24 new tests (266 total), ruff clean. Anchor: `bdd/ha-adapter/config-entry-plumbing-trace.json`; BDD A–G evidence. Arch review OK (0 violations; applied: controller public getter so adapter stops touching `_config`). BDD-evidence review OK (pinned exact listener count + computed_start_time in the anchor `expected` block + test, added run date).
- **2026-06-16** - Scaffolded `docs/specs/config-entry-plumbing.md` + `bdd/ha-adapter/config-entry-plumbing-bdd.md` (scenarios A–G) for queued packet 2 (F1). Grounded the spec in the actual dead seams: config-flow stub never collects `power/plug/temp_entity_id` (so the watcher never starts → integration inert), time entities are local stubs that never reach watcher/SessionConfig, and `services.yaml` declares 5 services with zero registered. Resolved 3 embedded decisions and wrote them into the spec: D2 keep 3 backed services + trim `start_calibration_session`/`import_history`; D3 `homeassistant.util.dt` + next-occurrence; D1 `hass.data[DOMAIN]` lookup. No code changed; spec is draft, implementation not started.
- **2026-06-12** - Full-codebase review (findings F1–F10, `docs/research/codebase-review.md`) + core correctness fixes packet (F2/F3/F4/F6). F2: `on_charging_started` no longer zeroes `active_wh`/relay history — probe Wh and cycles persist into CHARGING (verified bug; 1.467 Wh was being wiped). F3: `start_probe` records relay transition + refuses on chatter suppression; `end_probe(now)` and probe-timeout arm command confirmation; watcher honors refusal (arch-review catch: never energize on refusal) and passes `now` to `end_probe`. F4: morning reset arms on a fresh controller's first tick instead of firing (restart race; verified bug). F6: `elapsed_seconds` filters to trusted observations. BDD evidence correction note added to finish-time-scheduling evidence. 8 new/strengthened tests (241 total), ruff clean. Arch review: 1 invariant-7 gap found and fixed, 3 recommendations applied. Follow-up: `ingest_from_trace` observation timestamp now trace-derived (was wall-clock `now`; made the ha-calibration-ingestion anchor artifact non-deterministic and was wrong metadata for a historical trace; 242 total). Closeout BDD-evidence review: corrections verified honest; stale 39-test raw-output block in finish-time-scheduling evidence refreshed to the 44-test run.
- **2026-06-12** - Finish-time scheduling done (ADR-0012 decisions B–D). `SessionState.PROBING` + `start_probe`/`end_probe` in `SessionController` and coordinator. `session_reason` on all non-idle states. `computed_start_time` kwarg threaded through `tick()`. `HASensorWatcher` rewritten: `set_target_finish_time()`, `_pessimistic_start_time()`, `_probe_time()`, `_fire_event()` logbook helper; probe fires once per cycle, updates `computed_start_time` on success or falls back to pessimistic on timeout; overrun event fires once per session without faulting; PROBING accumulates Wh for energy guardrail. 39 new tests (233 total), ruff clean. Anchor: `bdd/ha-adapter/finish-time-scheduling-trace.json`. BDD A–F evidence; arch review (0 violations, 3 concerns addressed); BDD review (FAULTED coverage gap closed).
- **2026-06-09** - HA adapter slice 3 done. `CalibrationProfile`: `elapsed_seconds` field on `FullObservation`, `reference_temp_c` field, `elapsed_seconds` property, `estimated_duration_s()` method (ADR-0012 decision A). `CyclestewardCoordinator.ingest_from_trace()`: converts live trace to Samples, calls `analyze()`, applies temperature-corrected proximity check (full vs. partial decision), calls appropriate ingest method, returns updated profile. `HASensorWatcher._do_tick()`: ingestion trigger on CHARGING→DONE_LATCHED_OFF with "taper floor" reason in CHARGE_TO_FULL mode; awaits `ProfileStore.async_save()`. Research note on non-linear temperature effects added. 20 new tests (194 total), ruff clean. Anchor: `bdd/ha-adapter/ha-calibration-ingestion-trace.json`. BDD A–F evidence; arch review (0 invariant violations, 2 concerns addressed); BDD review (3 concerns addressed: temp-correction proof, silent guard removed, reference_temp assertion hardened).
## Active work

### Config-entry plumbing — review F1 (DONE 2026-06-16)

- [x] `config_flow.py`: `power_entity_id`/`plug_entity_id` (required) + `temp_entity_id`/`target_soc_dots`/`margin_s` (optional) entity/number selectors; entry `data` round-trips.
- [x] `schedule.py`: pure `next_occurrence(tod, now)` (tz-aware, next-occurrence/day-boundary rule; HA injects `dt_util.now()`) — D3.
- [x] `time.py`: `TargetFinishTimeEntity` → `watcher.set_target_finish_time(next_occurrence(...))`; `MorningResetTimeEntity` → `coordinator.set_morning_reset_time()`; watcher/coordinator reached via `hass.data[DOMAIN]` (D1); no-watcher set is a no-op beyond storing the value.
- [x] `services.py`: registers `set_mode`/`manual_override`/`acknowledge_fault` (deferred HA imports, idempotent, domain-level); `services.yaml` trimmed to those 3 (D2); `start_calibration_session`/`import_history` removed.
- [x] `__init__.async_setup_entry`: threads `margin_s` into the watcher, applies configured target-finish + morning-reset at setup, registers services; unregisters on last unload.
- [x] `SessionController.set_morning_reset_time` + `morning_reset_time` getter; `coordinator` delegates (no `_config` reach-in — arch-review recommendation).
- [x] Test harness `tests/ha_stubs.py` stubs HA + voluptuous session-wide (conftest) so real adapter modules run offline; 24 new tests (266 total), ruff clean. Anchor `bdd/ha-adapter/config-entry-plumbing-trace.json`; BDD A–G evidence. Arch review OK; BDD-evidence review OK (exact figures pinned in anchor `expected` + test).

### Core correctness fixes — review F2/F3/F4/F6 (DONE 2026-06-12)

- [x] F2: `GuardrailEvaluator.on_charging_started` no longer zeroes `active_wh` or replaces the relay-transition list; probe energy and cycles persist into CHARGING (per-session zeroing stays in `reset()`).
- [x] F3: `start_probe(now)` records a relay transition via new `on_turn_on_committed()` and refuses when `check_relay` would suppress; `end_probe(now=None)` and the probe-timeout path arm command confirmation; coordinator/watcher pass `now` through.
- [x] F3 (arch-review catch): watcher gates `turn_on` + `probe_start` event on `start_probe()` success; refusal fires a `probe_result` fallback event and never energizes the plug.
- [x] F4: morning reset arms `_last_morning_reset` on a fresh controller's first tick (today's boundary if past, else yesterday's) instead of firing immediately; 3 tests that encoded the old behavior updated with arming ticks.
- [x] F6: `CalibrationProfile.elapsed_seconds` filters to `trusted` observations.
- [x] BDD evidence correction note in `bdd/ha-adapter/finish-time-scheduling-evidence.md` (overstated invariant-7 claim).
- [x] 8 new/strengthened tests (241 total), ruff clean; arch review applied (invariant-7 gap fixed, stale docstring updated, probe-off bypass documented).

### Finish-time scheduling (DONE 2026-06-12)

- [x] `SessionState.PROBING` in enum; `max_probe_seconds` in `SessionConfig`.
- [x] `start_probe(now)` / `end_probe()` on `SessionController` and `CyclestewardCoordinator`.
- [x] `session_reason` non-empty on all non-idle states (WAITING, PROBING, CHARGING, DONE_LATCHED_OFF, FAULTED).
- [x] `computed_start_time: Optional[datetime]` kwarg on `tick()` — overrides time-of-day schedule.
- [x] PROBING section moved before `power_w is None` guard so timeout fires without power readings.
- [x] PROBING tick accumulates Wh via `_guardrails.accumulate()` (invariant 7).
- [x] `HASensorWatcher`: `set_target_finish_time()`, `_pessimistic_start_time()`, `_probe_time()`, `_max_duration_s()`.
- [x] `_fire_event()` logbook helper: fires `cyclesteward_event` on HA bus with standard schema.
- [x] Probe fires once per cycle at `probe_time`; success updates `computed_start_time`; timeout falls back to pessimistic.
- [x] `session_start` event on WAITING→CHARGING; `overrun` event fires once per session without faulting.
- [x] Pre-existing morning-reset failures in `test_ha_wiring.py` fixed (use fixed T0 timestamps).
- [x] 39 new tests (233 total), ruff clean. Anchor: `bdd/ha-adapter/finish-time-scheduling-trace.json`. BDD A–F evidence; arch review (0 violations, 3 concerns addressed); BDD review OK (FAULTED gap closed).

### HA adapter slice 3 (DONE 2026-06-09)

- [x] `elapsed_seconds: Optional[float]` on `FullObservation`; `reference_temp_c`, `elapsed_seconds` property, `estimated_duration_s()` on `CalibrationProfile`.
- [x] `ingest_full_session()` extended with `elapsed_seconds` and `session_temp_c` kwargs.
- [x] `coordinator.ingest_from_trace()`: trace→Samples→analyze→temperature-corrected proximity→full or partial ingest.
- [x] `HASensorWatcher`: accepts `profile_store`; `_do_tick()` triggers ingestion on taper-floor DONE_LATCHED_OFF.
- [x] `__init__.py` passes `store` to watcher.
- [x] 20 new tests (194 total), ruff clean. Anchor: `bdd/ha-adapter/ha-calibration-ingestion-trace.json`. BDD A–F evidence; arch review OK; BDD review OK.

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

## Queued packets (ordered; from 2026-06-12 review, `docs/research/codebase-review.md`)

1. ~~**Core correctness fixes (F2/F3/F4/F6).**~~ DONE 2026-06-12 (see Active work).
2. ~~**Config-entry plumbing (F1).**~~ DONE 2026-06-16 (see Active work).
3. **Stale-meter guardrail (F5; invariant 7).** Watcher tracks last
   power-update age, passes `None` when stale; optional fault on prolonged
   staleness while CHARGING.
4. **Real-HA smoke test.** Run the integration in a dev HA instance (or at
   minimum hassfest + config-flow exercise); the single biggest untested
   surface is HA itself — all current evidence is against mocks.
5. **Probe CC/CV disambiguation (F7).** Use the wattage trend across the probe
   window to distinguish CC (rising/flat) from CV taper (falling ⇒ near-full);
   also latch `soc_estimate` at session max once taper is detected so the
   display doesn't count down during charge-to-full.
6. **Manual-override semantics (F8).** Needs a small ADR/spec note first:
   what the switch means, whether it dispatches TURN_ON, and detection of
   external plug-on so cutoff + guardrails apply (ADR-0009 promise).
7. **Setup-flow / config-entry UX** (the larger wizard; builds on packet 2).

## Open queue (non-blocking)

- (a) Decide the Home Assistant domain slug (name resolved: CycleSteward; `docs/research/naming.md`).
- (b) Tune default values for the temperature thresholds/coefficient (ADR-0008) and the morning-reset/scheduled-start times (ADR-0009).
- (f) ~~Decide the remaining Home Assistant entity/service surface after the core model is proven.~~ DONE — ADR-0011 accepted 2026-06-09.
- (g) ~~ADR-0012: Resolve open questions A–D.~~ DONE — ADR-0012 accepted 2026-06-09. HA adapter slice unblocked.
- (c) Research how often users should be prompted for full calibration/balancing charges.
- (d) Decide default probe cadence and relay-cycle limits for low-battery detection.
- (e) Grow the charge-session fixture library further (seeded: clean/noisy/interrupted/malformed/unknown synthetics + one real Swoop ASM session; want more real sessions at varied temperatures and a full taper-to-completion session).
- (h) Anchor aggregation + drift detection (F9): trusted full sessions currently overwrite anchors wholesale; aggregate across `full_observations` instead (ADR-0007 territory).
- (i) Replace the `"taper floor" in session_reason` string match with a structured `TickResult` field (F10).
- (j) Probe remaining-time model is linear in SoC; revisit with curve integration once real taper fixtures exist (ADR-0012 deferred item).
- (k) `target_soc_dots` is collected by the config flow and stored coarsely in `entry.data` but has no runtime consumer yet (arch-review flag, 2026-06-16). A later SoC-target slice must wire it into `SessionConfig.target_soc_pct` via a coarse dots→band mapping (invariant 6 — no silent precise conversion).

## Blockers

- None for the first anchor slice. Later Home Assistant integration slices need decisions on entity naming, setup-flow UX, and persistent storage schema.
