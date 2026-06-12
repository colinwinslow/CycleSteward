# Finish-Time Scheduling — BDD

## Status

Draft. Paired with [docs/specs/finish-time-scheduling.md](../../docs/specs/finish-time-scheduling.md).

## Why this BDD exists

Pins down the observable scheduling cycle: probe fires at the right moment,
session_reason is always present, computed_start_time advances after a successful
probe, and failure paths fall back to pessimistic start without retrying silently.

## Scenarios

### Scenario A — happy path: probe fires, SoC read, refined start time used

**Given** `charge_mode = CHARGE_TO_PERCENT`, `target_finish_time = 07:00`,
  profile with 2 h mean duration and 10 min stddev (max = ~2 h 20 min), margin = 30 min
**When** the clock reaches `probe_time = 07:00 − 2h20m − 30m − 10m = 04:00`
**Then** `session_state` transitions to `PROBING`; `session_reason` contains
  `"Probing"`; a `probe_start` logbook event is fired with expected duration ≤5 min

**When** a stable CC-phase wattage is read during the probe
**Then** `session_state` returns to `WAITING_FOR_SCHEDULE`; a `probe_result`
  logbook event is fired with the SoC estimate and an updated `computed_start_time`
  (later than the pessimistic default); `session_reason` contains `"Scheduled: waiting"`

**When** `now >= updated computed_start_time`
**Then** `session_state` transitions to `CHARGING`; a `session_start` logbook
  event is fired; `session_reason` contains the target finish time

### Scenario B — probe failure: fallback to pessimistic start time

**Given** same setup as Scenario A
**When** the probe fires but no stable CC-phase wattage is read within the probe
  timeout (5 min)
**Then** `session_state` returns to `WAITING_FOR_SCHEDULE`; a `probe_result`
  logbook event is fired with failure reason; `computed_start_time` remains
  at the pessimistic default (`target_finish_time − max_duration − margin`);
  no silent retry

### Scenario C — no profile yet: pessimistic 4 h default used for probe_time

**Given** a fresh profile with no duration observations, `target_finish_time = 07:00`,
  margin = 30 min
**When** the scheduling cycle begins
**Then** `estimated_duration_s()` returns `(14400s, 2880s)` (4 h mean ± 20%);
  `max_duration = mean + 2×stddev = 14400 + 5760 = 20160s (5 h 36 min)`;
  `pessimistic_start = 07:00 − 20160s − 1800s = 07:00 − 6 h 6 min = 00:54`;
  `probe_time = pessimistic_start − 600s = 00:44`;
  the probe fires at `probe_time`; `_pessimistic_start_time()` matches the computed value

### Scenario D — session_reason always present on non-idle states

**Given** the coordinator is running
**When** `session_state` is any of `WAITING_FOR_SCHEDULE`, `PROBING`, `CHARGING`,
  `DONE_LATCHED_OFF`, or `FAULTED`
**Then** `session_reason` in `TickResult` is a non-empty string; when
  `session_state == OFF_IDLE` the reason is empty or absent

### Scenario E — overrun detection

**Given** a charge session started at `computed_start_time`, `target_finish_time = 07:00`
**When** the clock passes `07:00` and `session_state` is still `CHARGING`
**Then** an `overrun` logbook event is fired; no fault is raised; charging
  continues until the normal cutoff (wattage threshold or guardrail)

### Scenario F — computed_start_time drives WAITING_FOR_SCHEDULE transition

**Given** `session_state = WAITING_FOR_SCHEDULE`,
  `computed_start_time = T` passed into `tick()`
**When** `now < T`
**Then** state remains `WAITING_FOR_SCHEDULE`

**When** `now >= T`
**Then** state transitions to `CHARGING`; `session_start` logbook event fired

## Evidence

The implementing slice produces an evidence file at
`bdd/ha-adapter/finish-time-scheduling-evidence.md` containing raw outputs (not
summaries) for each scenario, referencing the anchor trace at
`bdd/ha-adapter/finish-time-scheduling-trace.json`.
