# STATUS.md

**Last updated:** 2026-07-04 (multi-battery slice 1 — battery registry + profile-library storage + v1→v2 migration — implemented; ADR-0014 accepted; 318 offline tests green; arch + BDD reviews OK)
**Phase:** Phase 2 - HA adapter
**Next bounded packet:** Multi-battery slice 2 — coordinator profile-swap + mid-session guard (ADR-0014). Expose the active battery on the coordinator and a swap method refused/queued while CHARGING/PROBING. Slice 3 (the `active_battery` select entity + "add new battery" UX + moving identity fields out of `config_flow.py`) follows. F8 (manual-override) remains queued behind the multi-battery work (user re-prioritized 2026-07-03).
**Current readiness:** READY-FOR-NEXT-PACKET (multi-battery slice 1 complete, verified, reviewed)

## Recent sessions (rolling, last 5)

- **2026-07-04** - Multi-battery support, slice 1 of ADR-0014 (accepted this session): battery registry + per-entry profile-library storage + v1→v2 migration. Direction came mid-session — Colin wants multiple bikes/chargers/batteries, and *"the same or different meters"*, which forced two separations instead of one: (a) a **config entry = one meter+plug** (single relay owner, invariant 7 intact); (b) **battery identities in a domain-level registry** (name/rated-capacity/dots — meter-independent facts); (c) **learned profiles keyed (battery, meter)** so anchors never cross meters (invariant 3). New `battery_registry.py` (`BatteryIdentity` + `BatteryRegistry` over `cyclesteward.registry` store; deterministic slug ids per D2; `async_register` collision-suffix + `async_ensure` reconciliation). `profile_store.py` → v2 keyed library + `active_battery_id`; pure `migrate_v1_payload()` wraps the old bare profile byte-identically inside HA's real `_async_migrate_func`. `__init__.async_setup_entry` loads the shared registry, reconciles identities from persisted labels (D3), fresh-install registers + stores active, dangling-active-id falls back deterministically (arch-review catch); runtime otherwise unchanged (one coordinator/one active profile). Stub `Store` upgraded to mirror HA's version-aware migration contract with shared backing. 16 new tests (318 total), ruff clean on touched trees. Anchor `bdd/ha-adapter/battery-registry-storage-trace.json` (migration / reconciliation / two-meter legs) written + verified on disk by `test_generate_battery_registry_storage_trace`; BDD A–E evidence. Arch review OK (0 violations; 3 recs applied: dangling-id guard, ADR D1-resolved annotation, evidence counts). BDD-evidence review OK (evidence read-back script de-elided). Deferred (ADR-0014 open): cross-meter anchor transfer, curve-fingerprint battery detection, slice-2 swap semantics, slice-3 select-entity UX + `ProfileStore` schema migration notes. One pre-existing F401 in `tests_ha/test_real_ha_smoke.py` left for a separate commit.
- **2026-07-03** - Probe CC/CV disambiguation implemented (packet 5 / F7; `docs/specs/probe-cc-cv-disambiguation.md` accepted). Two distinct changes: (1) **Probe side** (`watcher.py`): accumulate `_probe_samples` during PROBING; once `_MIN_PROBE_SAMPLES=3` reached, classify the trend (last-half mean / first-half mean < 0.90 → CV taper, else CC) via `_classify_probe_trend()`; CC path refines `computed_start_time` using SoC-proportional remaining duration; CV taper path pushes `computed_start_time` to `target_finish_time − margin` (battery near-full); timeout with < 3 samples falls back to pessimistic (no `classification` field in event); `probe_result` event now always carries `classification` when classification was possible. (2) **Session side** (`session_control.py`): `_session_max_soc_pct` tracks session-peak SoC from high-confidence estimates during CHARGING; `_taper_latched` arms the first time `_taper_start` is set in CHARGE_TO_FULL, and latched ticks return the peak SoC with `low_confidence=True` and note `"taper phase: SoC held at session max"` instead of the falling wattage estimate. Both fields clear on `set_mode()`, morning reset, and new CHARGING session start. **BDD-evidence review:** 3 concerns surfaced (BDD sample-count examples, missing timeout trace leg, undocumented edge-case test) — all fixed before commit: BDD updated to `_MIN_PROBE_SAMPLES` examples; `probe_timeout` leg added to anchor trace with raw JSON; edge-case test annotated. 23 new tests (302 total); 4-leg anchor trace verified on disk. Arch review: N/A (no new ADR or architectural decision; changes confined to probe accumulation and SoC display in existing layers). BDD-evidence review OK.
- **2026-06-16** - Stale-meter guardrail implemented (packet 3 / review F5; `docs/specs/stale-meter-guardrail.md` accepted). New `GuardrailFault.STALE_METER` (a session fault) + `GuardrailsConfig.stale_meter_fault_seconds=1800.0` + pure `GuardrailEvaluator.check_stale_meter(power_is_missing, now)` (wall-clock blind-run; cleared on recovery/reset). `session_control.tick()` step 6 consults it on the `None`-while-CHARGING path → TURN_OFF + FAULTED past threshold; step 9 clears the clock on a numeric reading. Watcher gains observability-only one-shot `meter_unavailable`/`meter_recovered` events on the numeric↔None transition (no threshold logic). **Design pivot:** the originally-accepted cadence heuristic (300 s → substitute None) was dropped after gap analysis of `fixtures/real-swoop-asm-charge.csv` showed the on-change Aqara meter has median 365 s / max 788 s healthy quiet windows with flat power — a frozen value is indistinguishable from a CV plateau, so cadence detection would false-fault. Staleness is now signalled only by HA `unavailable`/`unknown`→None (universal); fault on prolonged blind-while-CHARGING at 1800 s (tolerance for transient unavailability, not tied to cadence). User flagged the deeper risk of overfitting to their one plug → **ADR-0013 accepted** (adapt to the sensor, never hard-code a device-tuned threshold); adaptive cadence-based freeze detection deferred to open-queue (l). 13 new tests (279 total), ruff clean. Anchor: `bdd/ha-adapter/stale-meter-guardrail-trace.json` (fault + recovery legs). BDD A–D evidence; arch review OK (0 violations; FAULTED-short-circuit comment applied); BDD-evidence review OK (reproducible gap-analysis command added).
- **2026-06-16** - Config-entry plumbing implemented (packet 2 / review F1; `docs/specs/config-entry-plumbing.md` now `implemented`). Wired the three dead seams: (1) `config_flow.py` collects `power/plug/temp_entity_id` entity selectors + `target_soc_dots` + `margin_s`; (2) `time.py` `TargetFinishTimeEntity`/`MorningResetTimeEntity` now round-trip into `watcher.set_target_finish_time()` (via pure `schedule.next_occurrence`) and `coordinator.set_morning_reset_time()`, reached via `hass.data[DOMAIN]` (D1); (3) `services.py` registers `set_mode`/`manual_override`/`acknowledge_fault` (deferred HA imports), `services.yaml` trimmed to those 3 (D2). `__init__.async_setup_entry` threads `margin_s`, applies the configured target-finish + morning-reset at setup, registers/unregisters services. New pure `schedule.py` (`next_occurrence`, tz-aware via `dt_util`, D3). New `SessionController.set_morning_reset_time` + `morning_reset_time` getter; coordinator delegates. Test harness `tests/ha_stubs.py` stubs HA + voluptuous session-wide (conftest) so the real adapter modules run offline. 24 new tests (266 total), ruff clean. Anchor: `bdd/ha-adapter/config-entry-plumbing-trace.json`; BDD A–G evidence. Arch review OK (0 violations; applied: controller public getter so adapter stops touching `_config`). BDD-evidence review OK (pinned exact listener count + computed_start_time in the anchor `expected` block + test, added run date).

## Active work

### Multi-battery slice 1 — battery registry + profile-library storage (ADR-0014) (DONE 2026-07-04)

- [x] ADR-0014 accepted (registry + per-meter profiles + manual `active_battery` select; auto-detect rejected as selection mechanism, deferred as confirmation assist). Spec `docs/specs/battery-registry-storage.md` accepted (D1 registry home = domain `Store`; D2 deterministic slug ids; D3 pure store-migration + setup reconciliation).
- [x] `custom_components/cyclesteward/battery_registry.py`: `BatteryIdentity` (to_dict/from_dict) + `BatteryRegistry` over `cyclesteward.registry` (v1 store); `async_register` (dash-suffix collision, cannot collide with a natural slug) + `async_ensure` (idempotent; existing identity wins).
- [x] `profile_store.py` v2: keyed `{active_battery_id, profiles}`; pure `migrate_v1_payload()` (wraps bare v1 profile under `slugify(battery_label)`, byte-identical); `_ProfileLibraryStore(Store)` supplies `_async_migrate_func`; new API (`active_battery_id`, `battery_ids`, `get_profile`, `async_set_active`, `async_save_profile`).
- [x] `__init__.async_setup_entry`: shared registry in `hass.data[DOMAIN]["registry"]`; D3 reconciliation from persisted labels; fresh-install `async_ensure` + store active; dangling/absent active-id falls back to `battery_ids[0]` (arch-review). `watcher.py` calibration save → `async_save_profile(active_battery_id, ...)`.
- [x] Test harness: stub `Store` mirrors HA version-aware migration (shared in-memory backing, `reset_storage()` autouse in conftest); stub `slugify`.
- [x] 16 new tests (318 total), ruff clean on `custom_components/`+`tests/`+`src/`. Anchor `bdd/ha-adapter/battery-registry-storage-trace.json` (migration/reconciliation/two-meter legs) generated + read-back-verified by `test_generate_battery_registry_storage_trace`. Evidence `bdd/ha-adapter/battery-registry-storage-evidence.md` (A–E). Arch review OK; BDD-evidence review OK.

### Probe CC/CV disambiguation — packet 5 / F7 (DONE 2026-07-03)

- [x] `_classify_probe_trend()` in `watcher.py`: half-window mean ratio; `_MIN_PROBE_SAMPLES=3`, `_CV_FALLING_RATIO=0.90`; returns `"cc"`, `"cv_taper"`, or `None`.
- [x] `_probe_samples` accumulation during PROBING; early conclusion on classification; timeout path attempts classification before pessimistic fallback.
- [x] `_apply_cc_probe_result()`: uses average of last-half samples as representative wattage; refines `computed_start_time` via SoC-proportional duration; fires `probe_result` with `classification: "cc"`.
- [x] `_apply_cv_taper_probe_result()`: sets `computed_start_time = target_finish_time - margin`; fires `probe_result` with `classification: "cv_taper"`, `first_mean_w`, `last_mean_w`.
- [x] `_session_max_soc_pct` + `_taper_latched` in `session_control.py`; max tracked from high-confidence-only estimates; latch arms first tick below `taper_floor_w`; returns latched SoC with `low_confidence=True` and `"taper phase: SoC held at session max"` note; clears on `set_mode()`, morning reset, and new CHARGING session.
- [x] `test_finish_time_scheduling.py` updated: `test_successful_probe_updates_computed_start_time` now sends 3 flat readings (matching new min-samples behavior); asserts `classification: "cc"` in `probe_result`.
- [x] 23 new tests (302 total); `tests/test_probe_cc_cv_disambiguation.py` (18 tests) + 5 SoC-latch tests in `test_session_control.py`. Ruff clean.
- [x] 4-leg anchor trace at `bdd/ha-adapter/probe-cc-cv-disambiguation-trace.json` (CC, CV taper, timeout, SoC latch). Evidence `bdd/ha-adapter/probe-cc-cv-disambiguation-evidence.md`. BDD-evidence review OK (3 concerns surfaced and fixed before commit).

### Real-HA smoke test — packet 4 (DONE 2026-06-16)

- [x] `tests_ha/` tree with own `conftest.py` (no `ha_stubs`; `pytest_homeassistant_custom_component` plugin + autouse `enable_custom_integrations`); excluded from default run via `testpaths = ["tests"]`.
- [x] `tests_ha/test_real_ha_smoke.py`: A loader/manifest validation (`async_get_integration` + every platform imports), B config-flow `CREATE_ENTRY` with data round-trip, C entities register across all 5 platforms + 3 services, D clean unload (watcher key popped → `async_stop`, coordinator dropped, services removed).
- [x] `pyproject.toml` `[ha-test]` extra pins `homeassistant==2026.6.3` + `pytest-homeassistant-custom-component==0.13.339`; installed into separate `.venv-ha` (Python 3.14, gitignored). Project `.venv` is 3.9 — too old for HA.
- [x] `.github/workflows/ci.yml`: 3 jobs — `hassfest` (official `home-assistant/actions/hassfest@master`, the canonical check not shippable via pip), `test-offline` (3.12, ruff + pytest), `test-real-ha` (3.13, `pytest tests_ha/ --asyncio-mode=auto`).
- [x] `manifest.json` fixes surfaced by wiring hassfest: empty `documentation` → repo URL; key ordering → domain/name/alphabetical; `codeowners` populated. (Lighter runtime loader didn't reject these; hassfest would.)
- [x] 4 real-HA scenarios green (`.venv-ha`, HA 2026.6.3); offline suite still 279 green (unaffected). Evidence `bdd/ha-adapter/real-ha-smoke-test-evidence.md`. Arch review OK (production change confined to manifest metadata). BDD-evidence review OK (watcher-release assertion added to D).

### Stale-meter guardrail — review F5 (DONE 2026-06-16)

- [x] `guardrails.py`: `GuardrailFault.STALE_METER` (added to `is_session_fault`); `GuardrailsConfig.stale_meter_fault_seconds=1800.0`; `_blind_run_start` state (cleared in `reset()`); pure `check_stale_meter(power_is_missing, now)` (wall-clock blind-run; faults at threshold).
- [x] `session_control.tick()`: step 6 (`power_w is None`) consults `check_stale_meter(True, now)` while CHARGING → TURN_OFF + FAULTED + `guardrail/stale_meter` event-log entry; step 9 calls `check_stale_meter(False, now)` to clear the clock on a numeric reading. Blindness outside CHARGING never faults.
- [x] `watcher.py`: observability-only one-shot `meter_unavailable`/`meter_recovered` events on the numeric↔None transition while charging (`_meter_blind` latch, reset on session completion). No cadence/threshold logic — watcher already feeds `unavailable`/`unknown`→None.
- [x] Design pivot recorded: cadence heuristic dropped (real meter median 365 s / max 788 s healthy quiet windows; frozen value indistinguishable from CV plateau). Availability-based detection is the universal floor; 1800 s = tolerance for transient unavailability. ADR-0013 accepted (adapt to sensor, never device-tuned threshold); adaptive cadence detection → open-queue (l).
- [x] `docs/specs/stale-meter-guardrail.md` accepted (D1 revised, D2/D3); ADR-0013 accepted + indexed. 13 new tests (279 total), ruff clean. Anchor `bdd/ha-adapter/stale-meter-guardrail-trace.json` (fault + recovery legs); BDD A–D evidence. Arch review OK (FAULTED-short-circuit comment applied); BDD-evidence review OK (reproducible gap-analysis command added).

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
3. ~~**Stale-meter guardrail (F5; invariant 7).**~~ DONE 2026-06-16 (see Active
   work). Implemented as availability-based (not cadence): fault on prolonged
   blind-while-CHARGING when the entity is `unavailable`/`unknown`. Cadence-based
   freeze detection deferred to open-queue (l) per ADR-0013.
4. ~~**Real-HA smoke test.**~~ DONE 2026-06-16 (see Active work). Implemented as
   the pytest-hacc config-flow harness (real HA 2026.6.3, `tests_ha/` under
   `.venv-ha`) + canonical hassfest in CI. No live dev-HA instance — the
   in-process HA test core is the harness.
5. ~~**Probe CC/CV disambiguation (F7).**~~ DONE 2026-07-03 (see Active work).
   Implemented as half-window trend classification in the probe accumulator +
   SoC latch in session_control during CHARGE_TO_FULL taper.
6. ~~**Multi-battery slice 1 — battery registry + profile-library storage
   (ADR-0014).**~~ DONE 2026-07-04 (see Active work). Inserted ahead of F8 per
   Colin's 2026-07-03 direction (multiple bikes/chargers/batteries across the
   same or different meters).
7. **Multi-battery slice 2 — coordinator profile-swap + mid-session guard
   (ADR-0014).** Expose active battery on the coordinator; swap method
   refused/queued while CHARGING/PROBING (changing anchors mid-session
   invalidates an in-progress cutoff). Open ADR-0014 item: block outright vs.
   queue until `OFF_IDLE`/`DONE_LATCHED_OFF`.
8. **Multi-battery slice 3 — `active_battery` select entity + registration UX
   (ADR-0014).** New primary select (ADR-0011 pattern); "add new battery"
   affordance; move `charger_label`/`battery_label`/`rated_capacity_wh` out of
   `config_flow.py` into the registry; legible per-(battery,meter) calibration
   state so an uncalibrated pairing doesn't read as data loss.
9. **Manual-override semantics (F8).** Needs a small ADR/spec note first:
   what the switch means, whether it dispatches TURN_ON, and detection of
   external plug-on so cutoff + guardrails apply (ADR-0009 promise).
10. **Setup-flow / config-entry UX** (the larger wizard; builds on packet 2).

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
- (l) Adaptive cadence-based freeze detection (extends stale-meter-guardrail F5). The shipped guardrail catches a *dead* meter (entity `unavailable`/`unknown` → None) on any sensor, but not a meter that stays `available` while frozen on a constant value. Fixed-interval sensors (many Wi-Fi plugs; Zigbee with periodic reporting) expose a freeze as abnormally long silence; on-change sensors (Aqara) do not. A detector must *learn* the sensor's observed reporting interval and fault on silence ≫ that interval, auto-disabling for on-change sensors — never a hard-coded device-tuned threshold (the design must not overfit to one plug). See `docs/specs/stale-meter-guardrail.md` D1.
- (m) Cross-meter anchor transfer (ADR-0014 deferred). Slice 1 forks a fresh profile per (battery, meter); seeding meter B's anchors from meter A's with a learned offset is a research question (how much do consumer plug wattage readings actually diverge?) needing evidence before it relaxes invariant 3. A later ADR territory.
- (n) Curve-fingerprint battery-detection assist (ADR-0014 deferred). The probe accumulator (ADR-0012) could fingerprint which known profile a session's onset wattage resembles — but only as a *confirmation* layered on the manual `active_battery` select ("looks like Battery B, confirm?"), never as the selection mechanism (wrong-profile selection silently changes cutoff wattage).

## Blockers

- None for the first anchor slice. Later Home Assistant integration slices need decisions on entity naming, setup-flow UX, and persistent storage schema.
