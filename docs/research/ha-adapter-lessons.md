---
title: Home Assistant adapter lessons
status: open
date: 2026-06-08
---

# Research: Home Assistant adapter lessons

## Question

What Home Assistant-specific pitfalls should the integration's adapter layer
avoid? These were learned the hard way while prototyping the same behavior as raw
HA automations + template sensors, before this project existed.

## Context

These are adapter-layer (HA) concerns, not core estimation decisions, so they are
recorded here rather than as ADRs. The pure core (ADR-0006) sidesteps most of
them, but the HA config-flow/entity slice should read this before writing
entities and services.

## Notes

### Cutoff trigger must fire on the threshold itself

The wattage cutoff must trigger directly on the dynamic threshold crossing, not
on a fixed value plus a redundant template condition. In the prototype the cutoff
triggered on `power above <fixed>` and then re-checked `power >= cutoff`; because
the fixed trigger value was below the real cutoff, the condition was false at
trigger time and the cutoff never fired (the bike charged to full overnight). In
HA, trigger on a numeric-state threshold that reads from the cutoff entity; add a
small `for:` debounce if the wattage signal is noisy. In the integration, the
core evaluator owns this — fire on the first crossing, no second gate that can be
false at the crossing instant. (See `docs/specs/session-control.md`.)

### Always default `unknown` / `unavailable` readings

A transient `unknown`/`unavailable` reading (sensor restart, Zigbee hiccup) threw
`ValueError: float got invalid input 'unknown'` and errored the whole automation
or condition. Always coerce with a safe default; treat a missing reading as
no-progress / hold, never as a crash. (Captured as a guardrail in
`docs/specs/guardrails.md`.)

### Entity-id / template-sensor pitfalls

- `object_id` is not a valid key on template sensors in current HA; it silently
  invalidates the whole sensor (shows `unavailable`). Register entities with
  proper `unique_id` via the entity platform and let entity_id derive cleanly.
- A `name:` like "E-Bike ..." auto-generates `sensor.e_bike_...` (underscore
  after the lone "e"), which caused dashboard entity-id mismatches. Pick clean
  entity_ids in the integration.
- Duplicate automation IDs (one in the UI, one in `automations.yaml`) cause
  "does not generate unique IDs ... ignoring" and only one wins. The integration
  avoids hand-managed IDs entirely.

### Template / encoding gotchas

- Nested Jinja list filters like `[[x, 100] | min, 0] | max` were flaky; split
  into intermediate `{% set %}` steps.
- Special characters (`·`, `°`, `→`) edited on mobile caused suspected encoding
  issues; keep strings ASCII or localize them properly in the integration.

### Recompute on startup

The cutoff-watts helper recomputed only when garage temperature changed; make
sure the computed cutoff has a sane default and recomputes on startup so it is
never stale or empty at boot.

### Configure the real entities once

Wrong entity placeholders (`sensor.ebike_charger_power`, `sensor.garage_temperature`)
lingered from a template and silently broke things. The config flow should
discover/select the real switch, power, and temperature entities once and
validate them (ADR-0001 requires a dedicated metering plug).

## Open sub-questions

- Which of these become explicit validation steps in the config flow vs. internal
  invariants in the entity platform?
- Does the integration need a diagnostic that surfaces a stale/empty computed
  cutoff at startup?

## Resolution

Open. Promote relevant items into the setup-flow / session-control specs or into
the HA adapter implementation plan when that slice begins.
