# Stale-meter guardrail: don't charge blind on a dead meter — BDD

## Status

Draft. Paired with [docs/specs/stale-meter-guardrail.md](../../docs/specs/stale-meter-guardrail.md).

## Why this BDD exists

Pins down what a user observes when the metering plug stops reporting mid-charge
because the entity goes `unavailable`/`unknown` (Zigbee drop, device reboot): the
integration holds safely, surfaces that the meter went dark, and — if it stays
blind too long while charging — fails safe by cutting power and entering FAULTED
rather than charging unobserved indefinitely.

> **Not in scope** (see spec Context): a meter that stays `available` while
> silently frozen on a constant value. Real meter cadence (median 365 s, max
> 788 s between updates, power flat across the gaps) makes a frozen value
> indistinguishable from a normal CV plateau, so it cannot be caught by timing
> without false-faulting healthy charges. The max-runtime / max-Wh guardrails are
> the backstop for that mode.

## Scenarios

### Scenario A — happy path: brief unavailability, then recovery (no fault)

**Given** an active charge in CHARGING with a learned profile
**When** the power entity reports `unavailable` (fed to the core as `None`) for
less than the 1800 s blind-fault window, then a numeric reading resumes
**Then** the core holds CHARGING with "power reading unavailable; holding" while
blind, the blind-run clock is cleared on the first numeric reading, no
`STALE_METER` fault fires, and charging continues — observable in the trace as
zero `STALE_METER` faults and a continuing CHARGING state.

### Scenario B — meter goes dark: hold safely + observability breadcrumb

**Given** an active charge in CHARGING with a numeric power reading
**When** the power entity transitions to `unavailable` (`None`)
**Then** the core returns the "power reading unavailable; holding" hold (no cutoff
misfire, no Wh accrual), and the watcher fires a single `meter_unavailable`
logbook event on the numeric → `None` transition — observable in the watcher
event log and the tick result.

### Scenario C — catastrophic: prolonged blindness while charging → STALE_METER fault

**Given** an active charge in CHARGING that has gone blind (power `None`)
**When** power remains `None` continuously for 1800 s while CHARGING
**Then** the `STALE_METER` guardrail faults: the tick returns `TURN_OFF` +
`FAULTED` with `fault=GuardrailFault.STALE_METER`, the plug is commanded off, and
`event_log` contains a `guardrail/stale_meter` entry — the charge fails safe
rather than running unobserved (OEM charger/BMS remains the battery-safety layer).

### Scenario D — recovery before the fault threshold clears the blind-run clock

**Given** an active charge that went blind (power `None`) for less than 1800 s
**When** a numeric power reading arrives
**Then** the blind-run clock is cleared, no `STALE_METER` fault fires, the watcher
fires a single `meter_recovered` event on the `None` → numeric transition, and
normal cutoff/SoC evaluation resumes on the live reading.

> Edge cases covered by unit tests rather than BDD scenarios: blindness while
> *not* CHARGING (IDLE / WAITING) must never fault and must not start the
> blind-run clock; and the guardrail measures wall-clock blind time across
> irregular tick intervals. See the guardrails and session-control test suites.

## Evidence

The implementing slice produces an evidence file at
`bdd/ha-adapter/stale-meter-guardrail-evidence.md` containing raw outputs (not
summaries) for each scenario: the anchor trace
(`stale-meter-guardrail-trace.json`) with its `expected` block read back from
disk, the relevant unit-test run output, and the watcher event-log dumps showing
the single `meter_unavailable` / `meter_recovered` transitions.
