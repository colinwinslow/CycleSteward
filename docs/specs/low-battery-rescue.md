---
status: draft
date: 2026-06-08
depends-on-adrs: [0005, 0007]
---

# Rescue: Low-battery probe and bounded rescue charge

## Status

Draft. Defines how CycleSteward avoids letting a display-empty battery sit low
while waiting for a later scheduled charge.

## Related docs

- [bdd/rescue/low-battery-rescue-bdd.md](../../bdd/rescue/low-battery-rescue-bdd.md) - observable behavior and scenarios

## Context

The motivating bike can show zero dots and stop assist while still powering
lights and electronic shifting. That state should not be treated as dangerous
true empty, but when the user has enabled this feature it should outrank simply
waiting for the next scheduled charge window. The integration needs a way to
detect and add a small bounded charge without leaving the charger on
indefinitely.

## Behavior contract

The probe/rescue feature is **off by default and only runs when the user enables
it** (ADR-0005). When disabled, CycleSteward never energizes the plug to probe and
this controller is inert. When enabled, the rescue controller:

- turns the plug on for a short probe window when policy allows
- ignores initial transients
- classifies median active power against the learned very-low charge signature
- if very-low, charges only until the rescue Wh or runtime bound is reached
- if normal or no bike is detected, turns the plug off and waits for schedule
- faults on stale meter data, command failure, or abnormal shape

## Anchor artifact

A state trace showing `PROBING -> RESCUE_CHARGE -> WAIT_FOR_SCHEDULE` for a
very-low signature and `PROBING -> WAIT_FOR_SCHEDULE` for a normal signature.

## Implementation order

1. Add the enable toggle (default off) and the inert-when-disabled path.
2. Add probe policy model.
3. Add classifier using learned low-start band.
4. Add bounded rescue Wh/runtime.
5. Add relay-cycle guardrail.

## Proof requirements

1. Unit tests for disabled (inert), low, normal, no-bike, and stale-meter probe
   outcomes.
2. BDD scenarios in `bdd/rescue/low-battery-rescue-bdd.md` pass.
3. Evidence includes trace artifacts and plug command history.

## Non-goals

- Frequent blind pulsing.
- Rescue charging to the user's daily target or to full.
- Treating zero dots as true battery empty.

## References

- ADR-0005
- ADR-0007
