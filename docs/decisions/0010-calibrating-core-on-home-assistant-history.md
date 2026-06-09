---
id: 0010
title: Calibrating the pure core on Home Assistant history
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [calibration, home-assistant, testing, data]
---

# ADR-0010: Calibrating the pure core on Home Assistant history

## Context

ADR-0006 keeps the estimator in a pure-Python core that runs without Home
Assistant. Synthetic fixtures prove the model's logic, but real calibration — the
wattage anchors (ADR-0002), the overhead and temperature/full-Wh learning
(ADR-0007), and opportunistic full-session detection — needs *real* recorded
charge sessions. The prototype's data already lives in Home Assistant's recorder
(the power sensor, and optionally the temperature sensor). We want to calibrate on
that real history without making the core depend on Home Assistant.

## Decision

**The pure core will ingest charge-session data through a plain tabular/JSON
sample format (the same shape as fixtures), and a thin export/adapter step will
pull Home Assistant recorder/history for the configured power and temperature
sensors into that format. The core must not import `homeassistant`; Home
Assistant data enters only as plain rows.** Calibration, overhead estimation, and
opportunistic full-session detection run identically on synthetic fixtures and on
exported Home Assistant history.

## Rationale

- Real recorded sessions are the only honest basis for per-setup calibration; a
  synthetic curve cannot capture a specific charger's overhead or temperature
  behavior.
- Routing Home Assistant data through a plain sample format preserves the ADR-0006
  boundary: the core stays testable and HA-free, and the same code path serves
  fixtures and real data.
- A history export also lets a user backfill calibration from sessions that
  happened before the integration was installed.

## Consequences

**Enables:**
- Calibration and recalibration on real recorded charge sessions.
- Reuse of the fixture analyzer and calibration code on exported HA history.
- Opportunistic full-session detection over historical data, not just live
  sessions.

**Constrains:**
- The core's input contract is a documented plain format; the HA adapter owns the
  recorder/history query and the conversion to that format.
- The core must not gain a direct Home Assistant dependency to read history.
- Exported history must carry timestamps and units the core can validate, and
  must tolerate gaps and `unknown`/`unavailable` rows.

**Open:**
- Export mechanism: a Home Assistant service/script, the history/recorder API, or
  a manual CSV export — and which to support first.
- How much history to pull, and how to deduplicate sessions across exports.

## References

- ADR-0006: Pure core before Home Assistant adapters
- ADR-0007: Calibration lifecycle and full-charge maintenance
- `docs/specs/profile-calibration.md`
- `docs/specs/fixture-analyzer-anchor.md`
