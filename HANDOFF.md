# HANDOFF - CycleSteward

## Repository

```text
Local path:  <set by user after unzipping>
GitHub:      <set by user>
```

## What this project is

CycleSteward is a Home Assistant custom-integration concept that learns an
e-bike charger/battery wall-power signature from a metered smart plug. It uses
that learned profile to automate just-in-time charging, partial-charge cutoff,
low-battery rescue behavior, and anomaly detection while leaving the OEM charger
and BMS as the true battery-safety system.

## Current direction

The current goal is to prove the modeling core before building Home Assistant
plumbing. The first implementation should be a pure-Python fixture analyzer that
reads a CSV charge session and emits a learned profile summary JSON.

## Latest completed work

Seed design docs were created: ADRs, specs, BDDs, architecture, research notes,
and a minimal Python scaffold.

## Recommended next step

Run `/startup`, then implement the `Fixture analyzer anchor artifact` packet in
`STATUS.md`. Keep the proof tied to `bdd/anchor/fixture-analyzer-anchor-bdd.md`.

## Constraints / guardrails

- Do not claim wall-power estimates are true BMS SoC.
- Do not build Home Assistant UI before the core model is demonstrable from a
  fixture.
- Do not hard-code Shimano-specific wattage values into the estimator.
- Keep charger safety delegated to the OEM charger/BMS, but keep automation
  guardrails for stale meters, bad profiles, and stuck plugs.
