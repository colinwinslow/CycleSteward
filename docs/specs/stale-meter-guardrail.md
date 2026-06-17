---
status: accepted
date: 2026-06-16
depends-on-adrs: [0005, 0006, 0013]
---

# Stale-meter guardrail: don't charge blind on a dead meter

## Status

Accepted 2026-06-16. Defines the contract surface for the stale-meter guardrail
per ADR-0005 (automation guardrails) and invariants 7 (guardrails bound
automation failures) and 8 (core model before HA plumbing). Closes review finding
F5 (`docs/research/codebase-review.md`). Evidence:
[stale-meter-guardrail-evidence.md](../../bdd/ha-adapter/stale-meter-guardrail-evidence.md).

## Related docs

- [bdd/ha-adapter/stale-meter-guardrail-bdd.md](../../bdd/ha-adapter/stale-meter-guardrail-bdd.md) — observable behavior
- [STATUS.md](../../STATUS.md) — current phase and active work

## Context

`HASensorWatcher` drives `coordinator.tick()` from two sources: real power
state-change events, and a 60 s keepalive timer (`watcher.py` `_handle_keepalive`).
The keepalive feeds the **last cached** power reading (`self._cached_power_w`),
which is only refreshed by a real state-change event.

The original framing of F5 assumed staleness could be inferred from *event
cadence* — if no update arrives for N seconds, treat the meter as frozen. That
holds only for sensors that report on a **fixed interval**. CycleSteward must
work with any metered plug, and reporting behavior varies by hardware:

- **On-change sensors** (e.g. the Aqara Zigbee plug used for the first install)
  emit an update only when the value changes, so during the flat CV plateau they
  legitimately go quiet for minutes. In `fixtures/real-swoop-asm-charge.csv`
  (80 samples over 456 min) inter-sample gaps run a **median of 365 s, p90 of
  464 s, and a max of 788 s**, with 63 of 79 gaps exceeding 300 s and power
  essentially flat across them (`74.4 → 74.7 W` over 788 s). For this class, a
  frozen meter and a healthy quiet meter are **indistinguishable by gap timing**.
- **Fixed-interval sensors** (many Wi-Fi plugs; Zigbee plugs configured with
  periodic reporting) push an update every N seconds *even when power is flat*.
  For this class, a silence much longer than N genuinely does signal a freeze,
  and cadence-based detection is worthwhile.

The lesson is **not** "never use cadence" — that would overfit the design to
on-change hardware. It is: **never hard-code a cadence threshold tuned to one
device.** A cadence-based freeze detector, if added, must adapt to the sensor's
observed reporting behavior (and naturally disable itself for on-change sensors,
whose observed max-gap is effectively unbounded). That adaptive detector is a
deferred enhancement (open-queue (l)); this slice does not implement it.

What this slice **does** implement is the universal floor that works for every
sensor regardless of cadence: a genuinely dead meter — Zigbee drop, device
reboot, Wi-Fi outage — makes Home Assistant mark the entity **`unavailable`** (or
`unknown`), and the watcher already converts those to `None` via `_parse_float`
(`watcher.py:44`). The core then holds safely (`session_control.py` step 6:
"power reading unavailable; holding") — no action, no cutoff misfire. The
remaining gap is narrow:

- The core holds on `None` **indefinitely**. Invariant 7 requires a stale-meter
  guardrail; a charge that has been blind (entity `unavailable`/`unknown`) for a
  prolonged period while CHARGING should fail safe (cut power, enter FAULTED)
  rather than charge unobserved forever.

What this slice deliberately does **not** catch: a meter that stays `available`
while silently frozen on a constant value. On an on-change sensor that is
indistinguishable from a flat plateau; on a fixed-interval sensor it is catchable
but requires the deferred adaptive-cadence detector. The max-runtime and max-Wh
guardrails remain the backstop for that mode in the meantime.

## Resolved decisions

- **D1 — availability-based detection only this slice; cadence detection deferred
  and must be adaptive (revised 2026-06-16).** Staleness is signalled by HA
  reporting the entity `unavailable`/`unknown` (→ `None`), which is universal
  across sensor hardware. The watcher does **not** infer staleness from
  time-since-last-event, because that is unsafe for on-change sensors. A future
  cadence-based freeze detector (open-queue (l)) must *learn* the sensor's
  reporting interval rather than assume a fixed threshold; it is explicitly out of
  scope here. This generalizes the rule in [ADR-0013](../decisions/0013-adapt-to-sensor-not-one-device.md):
  adapt to the sensor's observed behavior, never hard-code a device-tuned threshold.
- **D2 — prolonged-blind fault threshold (core) = 1800 s.** Once power has been
  `None` continuously while in CHARGING for 1800 s (30 min), the `STALE_METER`
  guardrail faults: TURN_OFF + FAULTED + event-log entry. The threshold is a
  *tolerance for transient unavailability* — a Zigbee re-pair, Wi-Fi blip, or HA
  restart should not fault a charge — not a function of any sensor's reporting
  cadence (a quiet window on an on-change sensor never produces `None`, so it
  never starts the blind-run clock). Cutting power is fail-safe — the OEM
  charger/BMS remains the battery-safety layer (invariant 1). Hard-coded default
  constant for now; wiring it to a config option is deferred to open-queue (b).
- **D3 — placement: pure core guardrail; no watcher freshness logic.** The fault
  decision lives entirely in the pure `GuardrailEvaluator` so it is testable
  without HA (invariant 8). The watcher needs no cadence tracking — it already
  propagates `unavailable`/`unknown` → `None`. The watcher's only addition is
  one-shot observability events on the `None`↔numeric transition.

A power reading that recovers (entity becomes available again, numeric value)
before the fault threshold clears the blind-run clock; no fault fires and charging
continues.

## Behavior contract

### Core (`src/cyclesteward/guardrails.py`)

- New `GuardrailFault.STALE_METER = "stale_meter"`; it **is** a session fault
  (`is_session_fault` → True, alongside MAX_RUNTIME / MAX_ACTIVE_WH /
  SWITCH_COMMAND_FAILURE).
- New `GuardrailsConfig.stale_meter_fault_seconds: float = 1800.0`.
- The evaluator tracks the start of the current blind run. A new method
  `check_stale_meter(power_is_missing: bool, now: datetime) -> Optional[GuardrailResult]`:
  - When `power_is_missing` is False: clear the blind-run start, return None.
  - When `power_is_missing` is True: lazily record the blind-run start; return a
    `STALE_METER` `GuardrailResult` once `now - start ≥ stale_meter_fault_seconds`,
    else None.
  - `reset()` clears the blind-run start.

### Core (`src/cyclesteward/session_control.py`)

- In step 6 (the `power_w is None` path), when the state is CHARGING, consult
  `check_stale_meter(True, now)` before returning the hold. Under the threshold it
  still returns the existing "power reading unavailable; holding" hold so the
  blind run is measured; at/over the threshold it escalates to FAULTED.
- When a numeric reading is processed while CHARGING (step 9), call
  `check_stale_meter(False, now)` to clear the blind-run clock so recovery resets
  it.
- A `None` reading while *not* CHARGING (IDLE / WAITING / PROBING) continues to
  hold with no fault and does not start the blind-run clock; the guardrail only
  applies to an active charge.
- On fault: set state FAULTED, append `guardrail/stale_meter: <reason>` to
  `event_log`, return `TickResult(TURN_OFF, FAULTED, None, reason,
  fault=GuardrailFault.STALE_METER)`.

### Watcher (`custom_components/cyclesteward/watcher.py`) — observability only

- No cadence tracking, no `None` substitution, no new threshold constant. The
  watcher already feeds `None` to the core when HA reports the entity
  `unavailable`/`unknown`.
- Fire a one-shot `meter_unavailable` logbook event (via the existing
  `_fire_event` helper) when the fed power transitions numeric → `None` during an
  active charge, and a `meter_recovered` event on the `None` → numeric transition.
  One event per transition, not per keepalive tick. These are breadcrumbs ahead of
  the eventual core fault; they are not load-bearing for the fault itself.

## Anchor artifact

`bdd/ha-adapter/stale-meter-guardrail-trace.json` — a synthetic pure-core trace
(coordinator/controller, matching the existing `guardrails-trace.json` harness)
that drives: IDLE → CHARGING (normal) → meter unavailable (`None`) → blind run
reaches 1800 s → STALE_METER fault (TURN_OFF + FAULTED). A second leg shows
recovery before the threshold (numeric reading resumes → blind-run clock cleared →
no fault). The trace's `expected` block pins the exact fault timestamp, the
`guardrail/stale_meter` event-log entry, and that the recovery leg produced no
fault. Verified on disk by reading it back in the evidence file.

## Implementation order

Concrete-first:

1. **Anchor artifact + core guardrail.** Add `STALE_METER`, config field,
   `check_stale_meter`, and reset handling in `guardrails.py`; wire the CHARGING
   `None` path in `session_control.py`. Build the trace and unit tests first
   (red), then make them green. This is the pure, HA-free core — the load-bearing
   change.
2. **Watcher observability.** One-shot `meter_unavailable` / `meter_recovered`
   transition events in `_do_tick`. No threshold logic.

## Proof requirements

1. Unit tests for `check_stale_meter` (blind-run accrual, reset on recovery,
   fault at threshold, no fault below threshold, no fault outside CHARGING) green
   in the guardrails test suite; `session_control` test for the CHARGING-blind →
   FAULTED escalation and for recovery clearing the clock.
2. Watcher tests (offline, via `tests/ha_stubs.py`): a numeric → `None`
   transition while charging fires `meter_unavailable` once; `None` → numeric
   fires `meter_recovered` once; no event on repeated same-state ticks.
3. BDD scenarios in `bdd/ha-adapter/stale-meter-guardrail-bdd.md` pass; evidence
   file holds raw outputs.
4. Anchor trace produces the expected fault + recovery legs; eyes-on confirmed by
   reading `stale-meter-guardrail-trace.json` and the evidence back from disk.
5. `python -m pytest` and `python -m ruff check .` clean.

## Non-goals

- **No cadence-based freeze detection in this slice.** It is deferred to
  open-queue (l) and, when built, must adapt to the sensor's observed reporting
  interval rather than hard-code a device-tuned threshold (unsafe for on-change
  sensors like the Aqara; see Context). A silently-frozen-but-`available` meter is
  not caught here; max-runtime / max-Wh guardrails are the backstop.
- No new config-flow field for the fault threshold (constant default; open-queue
  (b) covers later tuning/exposure).
- No change to the max-runtime or max-active-Wh guardrails; this is an
  independent fail-safe.
- No attempt to distinguish *why* the meter is unavailable (Zigbee vs. recorder
  vs. device) — the controller only knows it is blind.
- No recovery automation beyond clearing the blind-run clock; a fault still
  requires the existing acknowledge-fault path to clear.

## References

- [ADR-0005](../decisions/0005-guardrails-and-low-battery-rescue.md) — guardrails required
  for control slices; stale-meter named explicitly.
- [ADR-0013](../decisions/0013-adapt-to-sensor-not-one-device.md) — adapt to the
  sensor's observed behavior; never hard-code a device-tuned threshold (D1).
- `CLAUDE.md` invariants 7 (guardrails bound automation failures) and 8 (core
  model before HA plumbing).
- `docs/research/codebase-review.md` — finding F5.
- [docs/specs/guardrails.md](guardrails.md) — existing guardrail contract this extends.
- [docs/specs/finish-time-scheduling.md](finish-time-scheduling.md) — watcher
  keepalive / `_do_tick` structure this builds on.
