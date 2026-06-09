---
title: Integration naming
status: resolved
date: 2026-06-08
---

# Research: Integration naming

## Question

What should this Home Assistant integration be called?

## Context

The name should imply learned charge-curve control without overclaiming true BMS
SoC or manufacturer-specific charger intelligence.

## Candidate names

### Strong candidates

- **CycleSteward** - frames the integration as a steward of charge cycles;
  general across charger/battery combinations and not tied to a specific curve
  feature. **Chosen** to match the repository name.
- **ChargeShape** - the original working name; emphasized the learned curve
  shape. Neutral and general, but read as too curve-specific.
- **SmartTaper** - evokes the CV taper and smart cutoff, but may sound too
  lithium-specific.
- **WattCycle** - emphasizes wall-power learning and bike charging cycles.
- **CurveCharge** - clear but a little generic.
- **ChargeCurve** - very clear; may already be widely used.
- **TaperPoint** - focused on the knee/taper concept; less general than the
  active-Wh model.
- **WattKnee** - memorable for CC/CV knee detection, but too technical and not
  accurate for all targets.

### Home Assistant style names

- **Adaptive Charger**
- **Learned Charger**
- **Metered Charger Control**
- **Smart Plug Charger**
- **Charge Profile Controller**

### Recommendation

Use **CycleSteward** as the repo and code-name. It leaves room for active-Wh
estimation, curve landmarks, fast chargers, and non-Shimano chargers without
promising exact SoC, and it matches the GitHub repository name.

## Open sub-questions

- Is the final HA integration domain `cyclesteward`, `cycle_steward`, or a more
  descriptive name such as `adaptive_charger`?
- Should the public name include "e-bike" or stay charger-general?

## Resolution

Resolved: the project name is **CycleSteward**, matching the repository. The
Python package and code-name are `cyclesteward`. The exact Home Assistant domain
slug is still open (see sub-questions) and can be settled when the config flow is
built.
