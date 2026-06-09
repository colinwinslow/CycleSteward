---
id: 0012
title: Finish-time scheduling and probe transparency
status: accepted
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

This ADR records the decided transparency requirement, resolves four algorithm
questions required before the HA adapter slice can begin, and flags the UI
surface work needed.

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

### Decided: full-charge-duration estimation from profile (A)

`CalibrationProfile.ingest_full_session` gains an `elapsed_seconds` parameter
and stores observed session durations alongside `active_wh`. The profile exposes
an `estimated_duration_s()` method that returns the mean observed elapsed time
(or a configurable pessimistic default when no observations exist, e.g. 4 h).
Uncertainty is expressed as `±stddev` across observations (or a fixed ±20 % of
mean when fewer than three observations are available). The duration estimate
feeds directly into the margin calculation (see C below). Wattage-curve
integration is deferred as a future optimization; the empirical elapsed-time
approach is sufficient for the adapter slice.

### Decided: pre-charge SoC probe cadence and mechanism (B)

The scheduling probe fires once per charge cycle at:

```
probe_time = target_finish_time − estimated_max_duration − margin − probe_headroom
```

where `estimated_max_duration` is `mean + 2×stddev` from profile observations,
falling back to the 4 h pessimistic default before the profile has data, and
`probe_headroom` is a small fixed buffer (default 10 min) for probe execution
and processing.

If the probe fails to produce a usable wattage reading (stale meter, noisy
signal, or no CC-phase detected), the system falls back to the pessimistic start
time (`target_finish_time − max_profile_duration − margin`) and fires a logbook
event describing the failure. No silent retry.

The scheduling probe **shares probe infrastructure with the rescue probe
(ADR-0005)**. Both are bounded energizations that require the same guardrail
path, `session_reason` attribute, and logbook-event transparency. A `PROBING`
session state is added to `SessionController` to represent an active probe
regardless of probe type. Duplicating relay logic for a cosmetic separation is
rejected.

### Decided: margin policy (C)

The scheduling margin is a **fixed default of 30 minutes**, exposed as a
user-configurable value in the HA config entry. Profile-derived margin (computed
from duration stddev once sufficient observations exist) is deferred to a future
enhancement.

If a charge session runs past `target_finish_time` despite the margin, the
integration fires a logbook event describing the overrun. This is **not** a
guardrail fault — modest overruns are expected behavior, and the max-runtime
guardrail (ADR-0005 slice A) already provides the hard cap against runaway
charges.

### Decided: dynamic start time and `WAITING_FOR_SCHEDULE` (D)

`SessionController.tick()` gains a new optional parameter `computed_start_time:
Optional[datetime]`. The controller uses this value when in `WAITING_FOR_SCHEDULE`
to check `now >= computed_start_time`; it is stateless about how the start time
was derived. The adapter owns the derivation and updates `computed_start_time`
after each probe.

Before any probe has run, `computed_start_time` defaults to:

```
target_finish_time − max_profile_duration − margin
```

This is the conservative worst-case start. As the probe refines the SoC
estimate, the adapter passes an updated (later) `computed_start_time` on
subsequent ticks. The controller sees the value move forward without caring
why.

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
