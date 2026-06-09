---
id: 0011
title: Home Assistant entity and service surface
status: accepted
date: 2026-06-09
supersedes: []
superseded-by: null
tags: [home-assistant, entities, services, ux]
---

# ADR-0011: Home Assistant entity and service surface

## Context

The pure CycleSteward core — calibration, session control, guardrails — is proven
and tested. The next phase is a Home Assistant custom component that wraps the core.
Before implementing the HA adapter, the entity and service surface must be fixed:
what HA objects does CycleSteward create, what state do they carry, and what
actions can a user or automation call?

The surface must reflect `SessionController`, `GuardrailEvaluator`, and
`CalibrationProfile` faithfully while following HA conventions. The adapter must
not carry derived state of its own (ADR-0006), must not claim certainty it does
not have (ADR-0002, ADR-0004), and must not expose configuration fields as runtime
entities unless the field is genuinely changeable at runtime without re-entering
the config flow. The `docs/specs/setup-flow.md` already covers the config-flow
inputs; this ADR decides runtime entities and callable services only.

## Decision

**CycleSteward will expose five primary entities (one `select`, three `sensor`,
one `switch`), four diagnostic `sensor` entities, two runtime-configurable `time`
entities, one `button` entity for fault recovery, and five service calls. The
schedule is expressed as a target finish time (not a start time); the start time
is derived by the integration. The derivation mechanism requires a new ADR and is
not specified here.**

### Entities — primary

| Entity | Kind | States / range |
|---|---|---|
| `charge_mode` | `select` | `off` / `charge_to_target` / `charge_to_full` |
| `soc_estimate` | `sensor` (%) | 0–100; attrs: `uncertainty_pct`, `low_confidence`, `method` |
| `session_state` | `sensor` (string) | mirrors `SessionState`: `OFF_IDLE`, `CHARGING`, `WAITING_FOR_SCHEDULE`, `DONE_LATCHED_OFF`, `FAULT` |
| `fault` | `sensor` (string) | `ok` when no fault; mirrors `GuardrailFault` when faulted |
| `manual_override` | `switch` | on / off |

### Entities — runtime-configurable time

| Entity | Kind | Notes |
|---|---|---|
| `target_finish_time` | `time` | When the charge should reach target SoC by; survives morning reset; writable from dashboard. Charge start is derived — not user-set. |
| `morning_reset_time` | `time` | Hour at which modes reset to `off`; writable from dashboard |

### Entities — diagnostic

| Entity | Kind | Notes |
|---|---|---|
| `active_wh` | `sensor` (Wh) | Idle-subtracted active Wh this session; resets at session start |
| `target_wattage` | `sensor` (W) | CC-phase wattage cutoff; unavailable until calibrated |
| `relay_cycles` | `sensor` (count) | Total relay transitions this session |
| `session_start` | `sensor` (timestamp) | When current charge session began; unavailable outside CHARGING |

### Entities — recovery

| Entity | Kind | Notes |
|---|---|---|
| `acknowledge_fault` | `button` | Clears a non-fatal fault and returns to `OFF_IDLE` |

### Services

| Service | Parameters | Effect |
|---|---|---|
| `cyclesteward.set_mode` | `entry_id`, `mode`: off / charge_to_target / charge_to_full | Same write path as the `charge_mode` select; for automation use |
| `cyclesteward.manual_override` | `entry_id`, `enabled`: bool | Same write path as the `manual_override` switch; for automation use |
| `cyclesteward.start_calibration_session` | `entry_id`, `soc_report` (optional) | Start a guided full calibration charge; errors if a session is already active |
| `cyclesteward.import_history` | `entry_id`, `csv_path` | Import HA history CSV for calibration (ADR-0010); blocked while session is active |
| `cyclesteward.acknowledge_fault` | `entry_id` | Same action as the `acknowledge_fault` button; for automation use |

## Rationale

**Select entity for modes rather than two switches.** The modes are mutually
exclusive in the core (ADR-0009). A `select` mirrors that invariant directly and
requires no enforcement logic in the adapter. Two independent switches create
ambiguous intermediate states if both are on or both are off, and force the
adapter to own mutual-exclusion logic that already belongs to the core.

**Fault as a primary text sensor rather than a diagnostic binary sensor.** A fault
code string is usable in automation conditions without attribute template sensors
(`sensor.fault != "ok"`). A binary sensor would require attribute lookups to
distinguish fault types. Fault is primary rather than diagnostic because it is
actionable state that users must see without navigating to a diagnostics panel.
Keeping `fault` and `session_state` as separate entities preserves the semantic
split: `session_state` says where the state machine is; `fault` says why it got
there.

**Manual override as a switch entity, not service-only.** A switch is visible in
HA dashboards without writing a service-call card, making override discoverable.
The switch's own state reflects whether the override is active, so the adapter
does not need to synthesize a readable override state from service-call history.

**`time` entity for target finish time, not start time.** The user specifies when
the bike should be ready, not when charging should begin. The integration derives
the start time from the target finish time using profile-learned duration estimates
and a brief pre-charge SoC probe. This matches how the user thinks about the
problem ("ready by 7 AM") without requiring knowledge of charge duration. The
start time is an implementation detail, not a user-facing concept.

`morning_reset_time` is also a `time` entity for the same reason: users may adjust
it from one day to the next (e.g., different weekend wake-up time) without
re-entering the config flow.

All other thresholds — guardrail limits, temperature parameters — are
set-and-forget configuration that belongs in the config entry.

**The finish-time scheduling mechanism is not specified in this ADR.** The
target-finish-time entity shape is decided here. The algorithm that derives a
charge start from it — including: full-charge-duration estimation from the
calibration profile, pre-charge SoC probe cadence, margin policy, and fallback
behavior when the probe fails — introduces design questions not addressed by any
existing ADR. That mechanism requires a new ADR before it can be implemented.
See Open items.

**SoC estimate as a sensor with uncertainty attributes, not two sensors.** A second
sensor for uncertainty would double the entity count and fragment what is a single
logical reading. Attributes carry the epistemic metadata required by ADR-0002 and
ADR-0004 without inflating the primary entity list.

**Button entity for fault acknowledgment alongside the service.** Fault recovery is
the most common dashboard action a user will take after a guardrail trips. A
`button` entity makes it a single tap rather than a service-call card. The matching
service call exists so automations can also acknowledge and restart.

**No button entity for calibration.** Calibration initiates a supervised charge
session and may take an hour or more to complete. Surfacing it as a button risks
accidental triggering from a dashboard. It is service-only, which requires an
explicit automation or developer-tools call.

**Diagnostic entities are not hidden, only de-emphasized.** `active_wh`,
`target_wattage`, `relay_cycles`, and `session_start` are real observable state
that power users will reference in automations or for debugging. They belong in
HA's Diagnostics section rather than being suppressed.

**Services shadow entities, not replace them.** `cyclesteward.set_mode` and
`cyclesteward.manual_override` write to the same state as the corresponding
entities. They exist because HA automations that trigger on conditions often need a
`service` action block rather than an `entity` toggle; they do not create a
parallel control path.

## Consequences

**Enables:**
- A minimal but complete main dashboard card: mode select, SoC gauge, state
  badge, fault indicator, manual override toggle, and fault-clear button.
- Schedule editing (finish time + morning reset) from the dashboard without
  re-entering config flow.
- Automation-friendly runtime: all state is entities; all actions are services.
- Fault types are distinguishable in automation conditions without template sensors.
- A user mental model of "ready by X" rather than "start at Y".

**Constrains:**
- Every primary and diagnostic sensor must be derived exclusively from
  `TickResult`, `SocEstimate`, `GuardrailResult`, and `CalibrationProfile` fields;
  the adapter layer must carry no derived state of its own.
- `soc_estimate` must expose `uncertainty_pct` and `low_confidence` as attributes
  at all times; omitting them is a violation of ADR-0004.
- `charge_mode` writes must call `SessionController.set_mode()` synchronously on
  the same tick; the adapter must not buffer or debounce mode changes.
- Entity availability for all sensors must track whether the plug's power reading
  is fresh; a stale meter must mark affected sensors unavailable (per guardrail E
  in ADR-0005).
- `acknowledge_fault` must do nothing and surface an error when the fault is
  `FREEZE_LOCKOUT`; a freeze lockout requires the user to change the environment
  and then set a new mode deliberately — silent acknowledgment would mask a
  persistent safety condition.

**Open:**
- **[NEEDS NEW ADR] Finish-time scheduling mechanism.** This ADR decides the
  `target_finish_time` entity exists and that the start time is derived, not
  user-set. It does NOT decide the algorithm. The following design questions need
  a dedicated ADR (suggested: ADR-0012) before the HA adapter slice can be
  implemented:
  - How full-charge duration is estimated from the calibration profile (the profile
    stores observed session Wh and wattage anchors, but duration estimation from
    those is not currently implemented in the core).
  - Whether and how a brief pre-charge SoC probe is used to adjust the start-time
    estimate (probe mechanism, duration, failure/fallback behavior, interaction
    with ADR-0005's rescue probe which is separately opt-in).
  - The margin policy: how much buffer before the finish time to absorb estimation
    error (user-configurable vs. fixed; what happens if the charge runs long).
  - How `WAITING_FOR_SCHEDULE` in the state machine transitions given a derived
    (dynamic) start time rather than a fixed user-supplied start time.
- `charge_to_full` clears at morning reset, not at session completion (resolved:
  consistent with ADR-0009's morning-reset-as-safe-default rationale; no
  auto-revert code path needed).
- Low-battery probe/rescue toggle stays in the config entry, not a runtime entity
  (resolved: config-entry only; adding a `switch` entity later is purely additive
  to the adapter — no core changes — and can be done independently if desired).
- Whether a future `sensor` entity should expose calibration confidence or profile
  age as a first-class observable (deferred until the HA adapter slice begins).

## References

- ADR-0001: Smart plug wrapper
- ADR-0002: Wattage-anchor SoC estimation
- ADR-0004: Coarse SoC input and uncertainty
- ADR-0005: Guardrails and low-battery rescue
- ADR-0006: Pure core before HA adapters
- ADR-0009: Charge modes, scheduling, and safe defaults
- ADR-0010: Calibrating on HA history
- `docs/specs/setup-flow.md`
- `src/cyclesteward/session_control.py`
- `src/cyclesteward/guardrails.py`
