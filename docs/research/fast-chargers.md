---
title: Fast charger compatibility
status: open
date: 2026-06-08
---

# Research: Fast charger compatibility

## Question

Are fast chargers different enough that CycleSteward should treat them as a
separate compatibility class?

## Context

The design assumes a repeatable CC/CV-like wall-power curve. The user asked
whether fast chargers are different. The answer matters for the curve classifier
and profile confidence model.

## Notes

Fast chargers for lithium-ion batteries often still have the same broad shape:
bulk/fast-charge constant current followed by voltage regulation/constant
voltage taper. Texas Instruments describes lithium-ion charging as CC then CV and
frames fast charging as depending heavily on precise constant-current regulation.
Battery University similarly describes lithium-ion charge stages with constant
current followed by topping/taper behavior.

However, fast chargers may differ in ways that matter to a wall-power learner:

- higher C-rate, making the curve steeper and shorter
- precharge or recovery behavior at very low battery voltage
- stepped or negotiated current limits
- thermal derating from the charger or battery/BMS
- charger fan loads or power-factor behavior visible at the wall
- current sharing with a system load for some devices
- stronger sensitivity to battery temperature and pack age

Initial conclusion: do not create a separate fast-charger mode yet. Treat fast
chargers as compatible when their wall-power curve is stable and learnable, but
add warnings/confidence flags for multi-stage, thermally derated, or interrupted
profiles.

## Open sub-questions

- What fixture shapes should be considered compatible fast charging?
- Should the setup flow ask the user whether the charger is OEM, standard, or
  fast/high-current?
- Should faster chargers have stricter temperature and meter-freshness defaults?
- Should profile confidence require more calibration sessions for fast chargers?

## Resolution

Open. Promote to an ADR once fast-charger fixture examples exist.

## References

- Texas Instruments, "Precise constant current regulation helps advance fast-charging": https://www.ti.com/document-viewer/lit/html/sszta38
- Texas Instruments BQ25170 page, describing precharge, fast-charge CC, and voltage regulation phases: https://www.ti.com/product/BQ25170
- Battery University, "BU-409: Charging Lithium-ion": https://batteryuniversity.com/learn/article/charging_lithium_ion_batteries
