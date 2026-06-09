---
id: 0012
title: Finish-time scheduling and probe transparency
status: draft
date: 2026-06-09
supersedes: []
superseded-by: null
tags: [scheduling, probe, transparency, ux, home-assistant]
---

# ADR-0012: Finish-time scheduling and probe transparency

## Context

ADR-0011 decided that the user-facing schedule entity is a `target_finish_time`
("ready by X") rather than a start time, and that the charge start is derived by
the integration. ADR-0011 explicitly did not decide the derivation algorithm, the
probe cadence, or the margin policy, flagging them as open design questions
requiring this ADR.

Separately, any mechanism that energizes the charger automatically — whether to
probe SoC for scheduling purposes or to perform a rescue charge (ADR-0005) —
creates a transparency problem: the user may see the charger switch on unexpectedly
and have no immediate explanation. This applies to both the scheduling probe
introduced here and the rescue probe described in ADR-0005.

This ADR records the decided transparency requirement, adds four open algorithm
questions that must be resolved before the HA adapter slice can begin, and flags
the UI surface work needed.

## Decisions

### Decided: probe transparency requirement

**Every automatic charger energization that is not a user-initiated charge session
must surface a human-readable explanation in the HA UI and record a timestamped
event in an activity log the user can review.**

Concretely:
- The `session_state` sensor (ADR-0011) gains a `session_reason` attribute
  containing a short, human-readable string describing the current automation
  action, e.g. `"Probing: estimating SoC (≤5 min)"`, `"Rescue charge: low battery
  detected, adding bounded Wh"`, `"Charging to 80% (target finish 07:00)"`.
  The attribute is always present; it is a non-empty string whenever `session_state`
  is not `OFF_IDLE`.
- The integration fires a Home Assistant logbook event for each significant
  automation transition: probe start, probe result, session start with reason,
  fault, fault acknowledgment, morning reset, schedule trigger. This provides
  a scrollable record the user can review without looking at HA's raw history.

This requirement applies to **all** automatic probe energizations in the
integration, including the rescue probe in ADR-0005 and the scheduling probe
introduced by this ADR. Neither probe implementation may energize the charger
silently.

### Open: finish-time scheduling algorithm

The following design questions must be answered in a future session before the
HA adapter scheduling slice begins. They are captured here so the ADR is the
single source of record for what is unresolved.

**Open A — Full-charge-duration estimation from profile.**
To derive a charge start time from a target finish time, the integration needs
to estimate how long a charge from the current SoC to the target SoC will take.
The calibration profile stores observed session Wh and wattage anchors, but
duration estimation from those is not currently implemented in the core. Questions:
- Should duration be estimated directly from observed per-session elapsed times
  (stored in the profile alongside Wh), from a wattage-curve integral, or from
  both with a cross-check?
- How is duration uncertainty represented and propagated into the start-time
  margin?

**Open B — Pre-charge SoC probe cadence and mechanism.**
The intended scheduling mechanism is: some time before the target finish, run a
brief charge (≈5 min) to read the CC-phase wattage and estimate current SoC, then
derive the start time. Questions:
- How long before `target_finish_time` should the scheduling probe run? (Must be
  long enough that the derived start time is still in the future even if SoC is
  near zero.)
- What happens if the probe fails to produce a usable wattage reading (e.g. meter
  stale, wattage noisy)? Fall back to a pessimistic start time? Notify the user?
- The rescue probe (ADR-0005) is a separate opt-in feature. Should the scheduling
  probe share the same probe infrastructure (same bounded energization + guardrail
  path) or be implemented separately? Sharing avoids duplicate relay logic;
  separating keeps rescue and scheduling independent.

**Open C — Margin policy.**
The ADR-0011 discussion referenced "~1 hour of margin." Questions:
- Is the margin a fixed project constant, a user-configurable value (exposed in
  the config entry), or derived from profile uncertainty?
- What happens if the charge runs long past `target_finish_time` despite the
  margin — is this a guardrail fault, a notification, or silently tolerated?

**Open D — Dynamic start time and `WAITING_FOR_SCHEDULE`.**
The current `SessionConfig` in the core holds a fixed `scheduled_start` datetime.
With derived start times, the start time changes as time passes (probe result
refines the estimate). Questions:
- Does `SessionController` need a new tick input for "computed start time" that
  the adapter updates after each probe, or should the adapter simply update the
  config's `scheduled_start` field before the window opens?
- How does `WAITING_FOR_SCHEDULE` behave when no probe has run yet (start time
  unknown)? Hold until a probe runs? Use a conservative early start?

## Rationale

**Transparency is a safety-adjacent requirement, not a cosmetic one.** A charger
switching on unexpectedly — even for a bounded 5-minute probe — can alarm a user
who does not understand why. If the user then manually turns the charger off to
stop the unexpected behavior, and the integration silently retries without
explanation, trust in the integration erodes quickly. A clear, always-visible
reason string and a persistent activity log give the user enough information to
understand, approve, or override what the integration is doing without reading
source code or looking at HA state history.

**`session_reason` as an attribute on `session_state`, not a new entity.** A
separate `session_reason` sensor would add an entity purely for explanatory text,
inflating the device card. An attribute on the already-primary `session_state`
sensor keeps the explanation co-located with the state it describes and is
accessible in automations via `state_attr('sensor.session_state', 'session_reason')`.

**Logbook events rather than a sensor-list attribute for the activity log.** HA's
logbook renders events as a scrollable, timestamped timeline in the UI without
custom dashboard cards. Storing a log as a sensor attribute list would require a
custom Lovelace card and would not persist across HA restarts. Logbook events are
the idiomatic HA solution for "things that happened", which is what probe history
is.

**Probe transparency applies to ADR-0005's rescue probe, not just the scheduling
probe.** The rescue probe predates this ADR, but it has the same transparency
problem. ADR-0005 did not specify a transparency mechanism because the pure core
did not address HA UI concerns. This ADR closes that gap: rescue probe
implementations must honor the same `session_reason` + logbook-event requirement.

## Consequences

**Enables:**
- Users can see at a glance why the charger is on, without reading HA state history.
- A timestamped activity log provides an audit trail for automation behavior and
  for debugging unexpected charge sessions.
- The transparency mechanism is reusable across all probe types.

**Constrains:**
- The HA adapter must always set `session_reason` before issuing a plug command;
  an energization without a reason string is a bug.
- The ADR-0005 rescue-probe implementation must be updated to fire logbook events
  and set `session_reason` as part of its HA adapter work — the core probe logic
  does not need to change, only the adapter wrapper.
- Logbook events must use a consistent schema (event type, reason, expected
  duration if applicable) so they are parseable by automations if needed.

**Open — UI surface design note needed:**
The `session_reason` attribute shape (string length, allowed values, localization)
and the logbook event schema (event type name, data fields) are implementation
details that should be specified in the HA adapter spec (`docs/specs/ha-entity-adapter.md`
or equivalent), not in this ADR. No additional ADR is needed for these; they are
adapter-layer decisions, not architectural ones. Flag this note when the adapter
spec is scaffolded.

## References

- ADR-0005: Guardrails and low-battery rescue (rescue probe must honor transparency)
- ADR-0009: Charge modes, scheduling, and safe defaults
- ADR-0011: Home Assistant entity and service surface (source of open questions A–D)
- `src/cyclesteward/session_control.py` (`WAITING_FOR_SCHEDULE`, `SessionConfig`)
- `docs/specs/setup-flow.md`
