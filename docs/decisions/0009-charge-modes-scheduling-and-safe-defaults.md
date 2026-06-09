---
id: 0009
title: Charge modes, scheduling, and safe defaults
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [ux, scheduling, modes, safety]
---

# ADR-0009: Charge modes, scheduling, and safe defaults

## Context

Lithium longevity favors keeping daily charges in a partial band and only
charging to full right before long rides. The user wants a battery-healthy daily
default, an occasional full charge, scheduled overnight charging, and a manual
override — without a forgotten setting causing the battery to sit at high SoC.
Because the cutoff is a wattage threshold (ADR-0002), the bike can rest at the
target indefinitely, so charging does not need to be timed to finish at
departure.

## Decision

**CycleSteward will expose two mutually-exclusive charge modes — "Charge to
target" (daily, battery-healthy default) and "Charge to full" (pre-ride) — both
off by default and auto-reset at a configurable morning time, so a forgotten
setting means no charge.** Scheduled charging starts at a **configurable time**
(not a fixed hour). A **manual override** directly toggles the plug, but the
active mode's wattage cutoff still applies, because the cutoff watches wattage
regardless of how the plug was energized.

## Rationale

- Off-by-default with a morning reset makes the safe outcome (no charge, battery
  rests where it is) the failure mode when the user forgets.
- Mutually-exclusive modes avoid ambiguous "both 80% and 100%" states.
- A configurable schedule generalizes beyond one household's 11 PM habit.
- A manual override that still honors the cutoff prevents an accidental
  overcharge when the user just wanted to top up briefly.
- Resting at a wattage-defined target removes the just-in-time finish-timing
  problem; departure-time scheduling becomes optional, not load-bearing.

## Consequences

**Enables:**
- A simple daily experience: leave it plugged in, it tops to target and rests.
- Pre-ride full charges on demand without changing the daily default.
- Override behavior that is convenient but still bounded by the cutoff.

**Constrains:**
- Mode state must be explicit and mutually exclusive in the core, not just in the
  UI.
- The cutoff evaluator must run independently of how the plug was turned on.
- The morning reset and schedule times must be configurable, with safe defaults.

**Open:**
- Default morning-reset time, default scheduled start time, and whether to also
  support an optional target-ready ("ready by") time.
- Whether "Charge to full" should auto-revert to "Charge to target" after one
  session.

## References

- ADR-0002: Wattage-anchor SoC estimation with active-Wh calibration
- ADR-0005: Guardrails and low-battery rescue
- ADR-0008: Temperature-aware charging and storage policy
