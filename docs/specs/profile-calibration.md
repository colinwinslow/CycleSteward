---
status: draft
date: 2026-06-08
depends-on-adrs: [0002, 0003, 0004, 0006, 0007, 0008, 0010]
---

# Calibration: Learned charger profile

## Status

Draft. Defines how CycleSteward learns and updates a charger/battery/meter
profile.

## Related docs

- [bdd/calibration/profile-calibration-bdd.md](../../bdd/calibration/profile-calibration-bdd.md) - observable behavior and scenarios
- [docs/specs/fixture-analyzer-anchor.md](fixture-analyzer-anchor.md) - first anchor artifact

## Context

The integration needs the two wattage anchors that define the SoC model
(ADR-0002) plus a curve signature for classifying later sessions. A natural
low/display-empty-to-full session is the best initial observation: it yields the
CC-start wattage, the CC->CV peak wattage, the taper floor, and — by integrating
active Wh across the full session — where a target percentage falls in wattage
terms. Partial observations with coarse user-reported SoC should also be stored.

## Behavior contract

A calibration profile stores:

- profile identity: charger label, battery label, meter entity identity
- user-supplied **rated battery capacity (Wh)** and the derived **overhead/efficiency
  estimate** = measured full-session active Wh / rated capacity, with confidence
- idle power baseline and confidence
- **wattage anchors**: `WATTS_AT_LOW` (CC-start wattage at a known low display
  state) and `WATTS_AT_TRANSITION` (wattage at the CC->CV peak), each with the
  assumed `SOC_AT_LOW` / `SOC_AT_TRANSITION` and confidence
- **taper floor**: the near-idle wattage the CV phase settles to before the plug
  is cut, used to detect completion
- full active Wh observations with timestamps and quality flags, used to locate
  the **target wattage** (e.g. the wattage that corresponds to 80%) along the CC
  ramp between the anchors
- curve landmarks and confidence
- SoC input reports with coarseness metadata
- profile state: uncalibrated, calibrating, calibrated, stale, faulted
- unresolved warnings such as missing samples or abnormal taper

Profile updates never overwrite a high-confidence full calibration with a lower-
confidence partial observation. Partial observations refine ranges.

### Guided calibration flow

A full calibration walks the user through the two anchors:

1. Run the battery down to its low display state (e.g. motor cutoff / 0 dots),
   plug in, and record the CC-start wattage as `WATTS_AT_LOW`.
2. Let the OEM charger finish normally; record the CC->CV peak as
   `WATTS_AT_TRANSITION` and the settled near-idle wattage as the taper floor.
3. Derive the wattage->SoC mapping and the target wattage from those two anchors
   plus the `SOC_AT_LOW` / `SOC_AT_TRANSITION` assumptions and the active-Wh
   integral across the session.

The flow must never instruct the user to deep-discharge below the display-empty
state, and must label `SOC_AT_LOW` / `SOC_AT_TRANSITION` as assumptions.

### Rated capacity and overhead

The user supplies the battery's rated capacity (Wh) at setup. After a full
session, `overhead_ratio = measured_active_full_wh / rated_capacity_wh` estimates
the combined charger efficiency and unused low-end reserve, bounding how many
measured wall Wh a full charge should take. Rated capacity is a nominal value, so
the derived overhead carries uncertainty.

### Opportunistic full-session calibration

CycleSteward classifies each completed session and, when one clearly starts near
the learned low anchor and runs to completion, treats it as a full-span datapoint
without prompting the user. Across several such sessions at different
temperatures, it learns how temperature shifts the measured Wh of a full charge,
feeding the compensation model (ADR-0008). Detection must be conservative: a
session that does not clearly start near the low anchor or reach completion is not
promoted to a full-span datapoint.

### Calibration data sources

Calibration runs identically on synthetic fixtures and on Home Assistant history
exported into the same plain sample format (ADR-0010). The core ingests plain rows
and never imports Home Assistant; an adapter/export step owns pulling recorder
history for the power and temperature sensors.

## Anchor artifact

A profile JSON showing one full calibration observation plus one coarse SoC
observation.

## Implementation order

1. Build on the fixture analyzer profile summary.
2. Add profile persistence model, including rated capacity and overhead.
3. Add calibration quality scoring.
4. Add partial observation ingestion.
5. Add opportunistic full-session detection and temperature/full-Wh learning.
6. Add Home Assistant history import into the plain sample format (ADR-0010).
7. Add profile stale/drift flags.

## Proof requirements

1. Unit tests for full calibration, overhead derivation from rated capacity,
   partial observations, coarse SoC reports, opportunistic full-session detection
   (accepted and rejected), and rejected bad data.
2. BDD scenarios in `bdd/calibration/profile-calibration-bdd.md` pass.
3. Evidence includes profile JSON before and after observation ingestion, and a
   calibration run over imported Home Assistant history.

## Non-goals

- Guaranteeing absolute BMS SoC.
- Forcing users to deep-discharge before calibration.
- Supporting non-lithium charging profiles in the first version.

## References

- ADR-0002
- ADR-0003
- ADR-0004
- ADR-0006
- ADR-0007
- ADR-0008
- ADR-0010
