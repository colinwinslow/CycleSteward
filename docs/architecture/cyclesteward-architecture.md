# CycleSteward architecture

## Context

CycleSteward learns from the wall-power curve of a charger/battery combination
plugged into a metered smart plug. The motivating case is a Shimano e-bike
charger on an Aqara Zigbee metering plug, but all charger-specific data must be
learned through profiles rather than hard-coded.

## Architectural shape

```text
Home Assistant entities/services
        |
        v
HA adapter layer
  - config flow
  - entity adapters for switch, power sensor, optional temp sensor
  - persistent profile storage
  - user actions: calibrate, charge to target, probe, full charge once
        |
        v
Pure CycleSteward core
  - sample normalization
  - idle-subtracted active Wh integration
  - charge-session state machine
  - learned profile store model
  - curve landmark detection
  - target estimator with uncertainty
  - guardrail evaluator
        |
        v
Artifacts and evidence
  - fixture CSV in
  - profile-summary JSON out
  - BDD evidence markdown out
```

## Core concepts

### Charger profile

A profile is scoped to one charger, one battery or battery family, and one
metering device. It stores idle power, active full-charge Wh observations,
learned curve landmarks, completion/taper behavior, sampling assumptions, and
uncertainty metadata.

### Active wall Wh

The primary progress metric is:

```text
active_power_w = max(measured_power_w - idle_power_w, 0)
active_Wh = integral(active_power_w over time)
```

This is not stored battery energy and not true BMS SoC. It is a repeatable
wall-side proxy used for per-profile charge progress.

### Curve landmarks

The CC/CV-like profile learner should identify, when present:

- idle/standby level
- active charging start
- initial stable charging band
- rising bulk region
- peak/knee candidate
- taper region
- completion/near-idle threshold
- abnormal interruptions or flat regions

### SoC reports and uncertainty

A user's bike display may report a precise percentage, a coarse dot/segment
count, a named anchor such as display empty or full, or nothing. The model must
preserve this input as an interval or label. A 0-of-5 dot display is not true
0% SoC; it is a learned anchor such as `display_empty` or `assist_cutoff_empty`.

## Session state machine

```text
OFF_IDLE
  -> PROBING
  -> WAIT_FOR_SCHEDULE
  -> RESCUE_CHARGE
  -> CHARGE_TO_TARGET
  -> FULL_CALIBRATION
  -> DONE_LATCHED_OFF
  -> FAULT
```

`FAULT` is used for automation anomalies: stale sensor data, plug command
failure, unexpected energy/runtime, temperature outside configured bounds, or a
curve that no longer resembles the learned profile. Faulting should not imply
that the OEM charger is unsafe; it means CycleSteward is no longer confident in
its automation.

## Home Assistant boundary

The Home Assistant layer is responsible for entity discovery, service calls,
notifications, persistent storage, and user configuration. The pure core must be
runnable from tests and fixtures without Home Assistant installed.

## References

- ADR-0001 through ADR-0007
- `docs/specs/fixture-analyzer-anchor.md`
- `bdd/anchor/fixture-analyzer-anchor-bdd.md`
