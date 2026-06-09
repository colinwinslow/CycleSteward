---
id: 0008
title: Temperature-aware charging and storage policy
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [temperature, safety, guardrails, estimation]
---

# ADR-0008: Temperature-aware charging and storage policy

## Context

Temperature affects both the wattage signal and battery health:

- Cold cells have higher internal resistance, so for a given SoC the wall wattage
  reads higher when cold. This biases the wattage-anchor SoC model (ADR-0002).
- Charging a lithium pack below freezing causes lithium plating and permanent
  damage. A pack merely *sitting* in the cold (not charging) is fine well below
  freezing.
- Sustained heat accelerates calendar aging even at rest, and charging during
  extreme heat is undesirable.
- A user's temperature sensor may sit some distance from the charger (different
  height or spot), so its reading can be offset from the charger's actual
  environment. Many users will have no temperature sensor at all.

## Decision

**When an optional temperature sensor is configured, CycleSteward will apply
temperature compensation and temperature gating; with no sensor configured, all
temperature behavior is disabled and charging proceeds uncompensated and
ungated.** Specifically, with a sensor:

- **Compensation**: slide the wattage anchors and the cutoff threshold by a
  **configurable linear coefficient** about a **configurable baseline**, so the
  SoC estimate and cutoff use the same temperature-adjusted model.
- **Freeze lockout**: refuse to *start* charging below a **configurable freeze
  threshold**, adjusted by a **configurable sensor-location offset (default 0)**
  to account for the sensor reading differently than the charger's location. A
  pack sitting cold is never acted on; only charging is gated.
- **Heat delay (not block)**: above a **configurable heat-delay threshold**,
  delay charging until the temperature falls below it; if it has not cooled by a
  **configurable deadline**, skip the session and notify.
- **Heat-storage notification**: when temperature stays above a **configurable
  threshold** for a **configurable duration**, notify the user to move the
  battery somewhere cooler.

## Rationale

- Freeze lockout protects against real, permanent battery damage; it is the one
  temperature rule with a hard-stop safety justification.
- Heat is a degradation and comfort concern, not an acute hazard, so delaying and
  notifying is preferable to hard-blocking a needed charge.
- Compensation keeps the wattage model honest across a garage's temperature
  swing, though the dominant accuracy lever is the anchors themselves; the
  coefficient is a small correction and is configurable because it needs
  per-setup calibration.
- Making thresholds and the sensor-location offset configurable avoids baking in
  one garage's geometry; a user whose sensor sits beside the charger sets the
  offset to 0.

## Consequences

**Enables:**
- Safe cold-weather behavior without forcing users to move the battery indoors.
- Accurate-enough SoC estimates across normal garage temperatures.
- Heat-aware scheduling and storage nudges.

**Constrains:**
- The temperature sensor is optional; the model and guardrails must degrade
  cleanly to "no temperature behavior" when it is absent.
- Compensation must be applied to both anchors and the cutoff together, or the
  SoC estimate and cutoff will disagree.
- Defaults must be conservative but overridable.

**Open:**
- Sensible default values for the freeze threshold, offset, coefficient,
  baseline, heat-delay/deadline, and heat-storage duration.
- The exact method for fitting the compensation from the temperature/full-Wh
  datapoints that ADR-0007 collects (the decision to learn it is made; the
  regression/fit approach is open).

## References

- ADR-0002: Wattage-anchor SoC estimation with active-Wh calibration
- ADR-0005: Guardrails and low-battery rescue
