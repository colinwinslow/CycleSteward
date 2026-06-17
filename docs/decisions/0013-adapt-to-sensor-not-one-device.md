---
id: 0013
title: Adapt to the sensor's observed behavior, not one device's
status: accepted
date: 2026-06-16
supersedes: []
superseded-by: null
tags: [sensors, guardrails, generality, calibration]
---

# ADR-0013: Adapt to the sensor's observed behavior, not one device's

## Context

CycleSteward's first install uses an Aqara Zigbee metering plug that reports power
**on change** — during the flat CV plateau it legitimately goes quiet for minutes
(median 365 s, max 788 s between updates in `fixtures/real-swoop-asm-charge.csv`,
power flat across the gaps). While building the stale-meter guardrail (review F5)
we nearly inferred staleness from update cadence: "no update for N seconds ⇒
frozen meter." That heuristic is correct for a fixed-interval sensor but
catastrophically wrong for an on-change one — it would fault a healthy charge on
the user's own hardware. The integration is meant to wrap **any** charger/plug
combination (CLAUDE.md identity), and reporting cadence, availability semantics,
and value granularity all vary by device. A design tuned to the one plug we
happen to own is a latent generality bug.

## Decision

Mechanisms that depend on sensor behavior must either use a **universal signal**
or **learn/adapt to the observed sensor at runtime** — **never hard-code a
threshold or assumption tuned to one device's behavior.** Where a universal floor
exists (e.g. Home Assistant `unavailable`/`unknown` → `None` for a dead meter),
prefer it; layer device-specific refinements only when they adapt to what the
sensor actually does.

## Rationale

- **Generality is a core promise.** The project exists to wrap arbitrary
  charger + battery + metering-device configurations; overfitting to the Aqara
  contradicts that and would surface as false faults or missed detections on other
  users' hardware.
- **Cadence is not universal.** On-change sensors (Aqara) and fixed-interval
  sensors (many Wi-Fi plugs; Zigbee with periodic reporting) have opposite
  silence semantics. A single hard-coded cadence threshold cannot serve both;
  an adaptive one (learn the observed interval) serves both and auto-disables
  where silence is meaningless.
- **Availability is universal.** A genuinely dead meter (Zigbee drop, reboot,
  Wi-Fi outage) is marked `unavailable`/`unknown` by HA regardless of vendor, so
  availability-based detection is a safe floor for every sensor.
- **One real fixture is thin evidence.** Tuning constants to a single captured
  session bakes that session's quirks into the product; behavior derived from it
  must be checked for generality before it becomes load-bearing.

## Consequences

**Enables:**
- A stale-meter guardrail that works on any sensor today (availability-based;
  see spec `stale-meter-guardrail`), with a clear path to an adaptive
  cadence-based freeze detector later (STATUS open-queue (l)).
- A consistent rule for future slices (calibration windows, config defaults,
  SoC anchors) when a choice leans on observed sensor behavior.

**Constrains:**
- No fixed cadence/staleness threshold tuned to the Aqara. A cadence-based freeze
  detector, if built, must learn the sensor's reporting interval at runtime.
- Constants derived from `fixtures/real-swoop-asm-charge.csv` must be justified as
  general (or made adaptive/configurable), not "what the one fixture showed."
- Reinforces invariant 3 (profile scope is narrow): per-configuration behavior is
  learned, not assumed.

**Open:**
- The adaptive cadence-based freeze detector itself (open-queue (l)): how to learn
  the interval, the silence multiple that should fault, and how it composes with
  the availability-based floor.
- Whether sensor reporting mode should be partly user-declared in the config flow
  versus fully inferred.

## References

- [ADR-0005](0005-guardrails-and-low-battery-rescue.md) — guardrails this principle
  shapes (stale-meter named explicitly).
- [ADR-0006](0006-pure-core-before-home-assistant-adapters.md) — keep adaptive
  logic testable in the pure core.
- [docs/specs/stale-meter-guardrail.md](../specs/stale-meter-guardrail.md) —
  decision D1 (availability-based now; adaptive cadence deferred).
- `STATUS.md` open-queue (l) — adaptive cadence-based freeze detection.
- `CLAUDE.md` identity (wrap any charger/battery/metering-device) and invariant 3.
