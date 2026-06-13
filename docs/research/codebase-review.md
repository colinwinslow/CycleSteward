---
title: Full-codebase review findings
status: open
date: 2026-06-12
---

# Research: Full-codebase review findings (2026-06-12)

## Question

What defects, gaps, and design risks exist in the work completed through the
finish-time-scheduling slice, and what should the next packets be?

## Context

A general review of all source, adapter, test, and doc layers performed at the
human's request before the next implementation session. Findings are ranked by
severity. Items marked **(verified)** were reproduced with a live Python
repro during the review, not inferred from reading.

The headline: the pure core is in genuinely good shape — clean layering,
honest uncertainty handling, ADR discipline that held up. The dominant risk is
not code quality but **integration inertness**: nothing has ever executed
inside a real Home Assistant instance, and the current wiring guarantees it
cannot (see F1). Several "proven" claims are proven only against mocks.

## Findings

### F1 — The integration is inert in a real HA install (blocker for any real use)

- `config_flow.py` collects only labels (`charger_label`, `battery_label`,
  `meter_id`, `rated_capacity_wh`). It never collects `power_entity_id`,
  `plug_entity_id`, or `temp_entity_id` — but `__init__.py:44-48` only starts
  `HASensorWatcher` when `power_entity_id` and `plug_entity_id` are non-empty.
  **A user installing today gets entities that display state but no watcher:
  no ticks, no relay control, no scheduling, no calibration.**
- `TargetFinishTimeEntity.async_set_value` (`time.py:58`) writes shadow state
  only. Nothing ever calls `watcher.set_target_finish_time()` in production
  code — the entire finish-time-scheduling slice is reachable only from tests.
  There is also no time-of-day → next-occurrence-datetime conversion anywhere
  (the entity holds a `time`, the watcher needs an aware `datetime`).
- `MorningResetTimeEntity` never writes through to
  `SessionConfig.morning_reset_time`.
- `services.yaml` declares 5 services; zero are registered in code.
- `margin_s` is constructor-injectable on the watcher but not configurable
  from any user surface.
- Timezone discipline is undecided: the watcher compares `_now()` (UTC-aware)
  against `target_finish_time`; a naive datetime here raises `TypeError`.

### F2 — Probe Wh accumulation is wiped on CHARGING entry (verified)

`session_control.py:319-321` accumulates Wh during PROBING "so energy consumed
counts toward the guardrail on the subsequent CHARGING session" — but
`GuardrailEvaluator.on_charging_started` (`guardrails.py:96-101`) resets
`_active_wh = 0.0` when the real session starts. Repro: 1.467 Wh accumulated
during probe → 0.0 after CHARGING entry. The comment, the STATUS log entry,
and the BDD-evidence claim of invariant-7 coverage are all false.
`test_probing_accumulates_wh_for_energy_guardrail` only asserts accumulation
*during* the probe, never retention — which is how this passed review.

### F3 — Probe relay operations bypass the guardrail evaluator

The watcher's probe path calls `homeassistant.turn_on`/`turn_off` directly
(`watcher.py:215-217, 235-237, 269-271`). `start_probe()` records no relay
transition; the probe-off path never calls `on_turn_off_committed`, so
guardrail D (command confirmation) is never armed for the probe TURN_OFF.
**If the plug ignores the probe TURN_OFF, the charger stays energized,
unmonitored, with no fault, until the computed start time arrives.** Probe
cycles also don't count toward the relay-cycle limit. ADR-0012 explicitly says
probes "require the same guardrail path" — they don't get it.

### F4 — Morning-reset fires on the first tick after a restart (verified)

`_should_morning_reset` treats `_last_morning_reset is None` as "reset is
due". On a fresh controller (HA restart) any first tick after the reset time
fires the reset and clears the mode. Repro: set mode at 22:00 on a fresh
controller → first tick clears it to OFF silently. Window in production is up
to one keepalive interval after every HA restart. Fix: initialize
`_last_morning_reset` to today's reset time at construction when `now` is
already past it (requires a construction-time `now`, or arm on first tick
without acting).

### F5 — No stale-meter detection (invariant 7 names it as required)

`_handle_keepalive` ticks with `_cached_power_w` forever. A power sensor that
silently stops updating (Zigbee drop without HA marking unavailable) is
indistinguishable from a live reading: cutoff is delayed past target, and
active-Wh integrates fictional energy until the max-Wh guardrail faults for
the wrong reason. The low-battery-rescue spec also assumes stale-meter
faulting exists. Fix shape: watcher tracks the last power-update timestamp and
passes `None` once age exceeds N× the expected report interval; the controller
already holds safely on `None`. Optionally fault after prolonged staleness
while CHARGING.

### F6 — `CalibrationProfile.elapsed_seconds` includes untrusted observations

The property's docstring says "from trusted ingestions" but the filter is only
`elapsed_seconds is not None` (`calibration.py:302-309`). Interrupted/distrusted
sessions (stored with `trusted=False`) pollute `estimated_duration_s()`, which
feeds probe timing and pessimistic start. One-line fix + test.

### F7 — CC/CV ambiguity in instantaneous-wattage SoC (design limitation, two user-visible symptoms)

The wattage→SoC map assumes CC phase, but a given wattage below the transition
anchor occurs twice per charge (rising CC, falling CV taper):

- During charge-to-full taper, `soc_estimate` visibly **declines** toward 0 as
  power tapers — exactly when the battery is at its fullest. The estimate
  should latch at its session max (or report the transition value) once taper
  is detected.
- The scheduling probe on a nearly-full battery reads taper wattage as *low*
  SoC → computes a much-too-early start → battery sits at full for hours,
  defeating the feature's purpose. The probe window (≤5 min) is long enough to
  check the wattage *trend* (rising/flat ⇒ CC; falling ⇒ CV/near-full) and
  disambiguate.

### F8 — Manual-override semantics are incoherent end-to-end

- The HA switch's `turn_on` calls `manual_override_on()`, which flips the
  controller to CHARGING — but no TURN_ON is ever dispatched to the plug
  (the controller only issues TURN_ON on its own IDLE/WAITING→CHARGING
  transition). The switch claims override is active while the plug stays off.
- The switch's `turn_off` writes shadow state only; the session keeps CHARGING.
- Nothing detects an *external* plug-on (user presses the Aqara button): the
  controller stays in WAITING/IDLE while real charging proceeds with **no
  cutoff and no guardrail accumulation** — contrary to ADR-0009's "cutoff
  still applies under manual override". Detection shape: plug reports on +
  sustained active power while not CHARGING → treat as manual override.

### F9 — Anchor learning has no aggregation

Every trusted full session wholesale overwrites `watts_at_low`,
`watts_at_transition`, `taper_floor_w`, `active_full_wh`, and
`reference_temp_c` (`calibration.py:378-395`). One noisy or cold-day session
redefines the profile. `full_observations` already stores history; anchors
should eventually be a robust aggregate (median/EMA) with drift detection
(ADR-0007 territory). Acceptable for now; should not survive to "calibrated
product" status.

### F10 — Minor

- `watcher.py:339`: taper-ingestion trigger matches `"taper floor" in
  session_reason` — string-coupling to a reason message; should be a
  structured field on `TickResult`.
- `session_control.py:336,345`: two step-comments both numbered "7".
- `SocReport.from_dots(5, 5)` yields interval 100–120% (unclamped).
- `coordinator.profile` reaches into `_controller._profile` (private access
  across the boundary it defines).
- Probe-success remaining-time model is linear in SoC; CV tail makes real
  remaining time longer near full → starts may run late by more than the
  margin absorbs. ADR-0012 acknowledges curve integration as deferred; fine,
  but worth keeping visible.

## Process observations

- The three-layer proof discipline mostly worked — but F2 shows the failure
  mode: a test that asserts an intermediate property lets an evidence claim
  overstate the end-to-end property. BDD-evidence review should demand the
  asserted property match the *claimed* property ("counts toward the guardrail
  on the subsequent session" ⇒ assert post-transition state).
- Biggest evidence gap overall: **zero execution in a real Home Assistant**
  (no hassfest, no dev-container smoke test). All HA behavior is proven
  against `sys.modules` mocks. A smoke-test packet would retire more risk than
  any further unit-test slice.

## Resolution

Open. Queue in STATUS.md reorganized 2026-06-12 to sequence: core correctness
fixes (F2/F3/F4/F6) → config-entry plumbing (F1) → stale-meter guardrail (F5)
→ real-HA smoke test → probe CC/CV disambiguation (F7) → manual-override
semantics (F8, needs a small ADR or spec note first).
