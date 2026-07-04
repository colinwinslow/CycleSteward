---
id: 0014
title: Multi-battery support via a battery registry and per-meter profiles
status: accepted
date: 2026-07-03
supersedes: []
superseded-by: null
tags: [profile, multi-battery, home-assistant, guardrails, storage]
---

# ADR-0014: Multi-battery support via a battery registry and per-meter profiles

## Context

CycleSteward's data model assumes a 1:1 chain: one HA config entry -> one
`power_entity_id`/`plug_entity_id` pair -> one `ProfileStore` keyed by
`entry_id` -> one `CalibrationProfile` -> one `CyclestewardCoordinator` -> one
`HASensorWatcher` driving that plug. Invariant 3 (`CLAUDE.md`, ADR-0002,
ADR-0007) says a profile belongs to one charger+battery+meter combination —
but the current implementation further assumes each of those members appears
in exactly one combination.

Colin's actual household does not match that assumption: **multiple bikes,
each with its own charger and battery, charged through one or more metering
smart plugs — with any bike potentially plugged into any metered plug** (one
bike per plug at a time). Two consequences:

- The same meter serves different charger+battery combinations on different
  days, so one profile per config entry conflates curves that invariant 3
  requires to stay separate.
- The same charger+battery combination may appear on different meters, so a
  battery's identity (its name, rated capacity, coarse metadata) must not be
  trapped inside one config entry either.

The naive workaround — one config entry per charger+battery combination, all
pointing at the same `power_entity_id`/`plug_entity_id` — is unsafe, not just
redundant: every entry starts its own `HASensorWatcher`, each independently
subscribing to the shared power sensor and independently dispatching
`TURN_ON`/`TURN_OFF` to the shared switch, evaluating cutoff against
*different* anchors. It also breaks guardrail invariant 7: `relay_cycles`,
`min_dwell`, and command-confirmation state live per `GuardrailEvaluator`, so
N evaluators watching one relay cannot bound chatter or attribute faults.

Note on terminology: because each bike pairs a fixed charger with a fixed
battery, the user-facing identity unit is really the charger+battery pair.
This ADR calls it a **battery identity** for brevity; it names the pair, not
the cell pack alone.

## Decision

**Three separations, replacing the current 1:1:1 chain:**

1. **A config entry represents one physical meter+plug pair.** Exactly one
   `CyclestewardCoordinator`/`HASensorWatcher` ever drives a given plug,
   preserving single-owner relay control and guardrail invariant 7. Meters
   used concurrently (two bikes charging at once on two plugs) are simply two
   entries, as today.

2. **Battery identities live in a domain-level registry shared across all
   entries.** An identity carries the user-facing name and the coarse
   per-battery facts that are meter-independent: `charger_label`,
   `battery_label`, `rated_capacity_wh`, target SoC dots. Registering a
   battery once makes it selectable on every meter.

3. **A learned profile is keyed by (battery identity, config entry) — one
   profile per battery per meter, per invariant 3.** Wattage anchors learned
   through meter A are never applied to readings from meter B. Selecting a
   battery on a meter that has not seen it yet starts a fresh, uncalibrated
   profile for that pairing (seeded only with the registry's coarse facts,
   which are meter-independent).

**Which battery is plugged in is a manual, explicit choice — not inferred
from the wattage curve.** A new primary `active_battery` select entity per
entry (same pattern as `charge_mode`, ADR-0011) lists the registered
identities; selecting one loads the (identity, entry) profile into the
coordinator for the next session. Curve-fingerprint auto-detection is
rejected as the *selection* mechanism (see Rationale) but not foreclosed as a
future confirmation aid.

## Rationale

- **Wrong-profile selection is a safety-relevant mistake, not a UX
  inconvenience.** Anchors from the wrong battery/charger directly change the
  cutoff wattage and estimated SoC (ADR-0002). A misclassified curve could
  hold the wrong battery below or above its real target, silently. A manual
  select is unambiguous; the friction (one tap when swapping) is small
  against that risk.
- **Single relay owner is non-negotiable.** The guardrail model (ADR-0005)
  was designed and tested assuming one `GuardrailEvaluator` sees every relay
  transition on a given plug. Splitting ownership across N coordinators would
  rebuild chatter-prevention as a cross-instance concern — far larger than a
  select entity.
- **Identity and calibration have different scopes, so they get different
  homes.** A battery's name and rated capacity are true regardless of meter;
  its wattage anchors are not (meters differ in calibration and sampling —
  ADR-0013 territory). Registry-level identity plus per-meter profiles keeps
  each fact at exactly the scope where it is valid, instead of either
  duplicating identities per entry or illegally sharing anchors across
  meters.
- **Strict per-meter fork now; anchor transfer later, maybe.** It is
  tempting to seed meter B's profile from meter A's anchors with an offset.
  That is a research question (how much do consumer plug wattage readings
  actually diverge?), not a design default; invariant 3 says fork, so fork.
  A later ADR can relax this with evidence.
- **Auto-detection is deferred as a confirmation assist, not selection.** The
  probe accumulator (ADR-0012, packet 5) could plausibly fingerprint which
  known profile a session's onset wattage resembles — useful as "this looks
  like Battery B, confirm?" layered on the manual select, so a
  misclassification never silently drives cutoff.

## Consequences

**Enables:**
- Any bike on any metered plug, one at a time per plug, each pairing keeping
  its own undiluted learned curve.
- Two bikes charging concurrently on two plugs (two entries), each against
  the correct profile.
- Adding a battery is one registry entry, immediately selectable on every
  meter; adding a meter is one config entry, immediately offering every
  battery.

**Constrains:**
- `ProfileStore` schema changes from one `CalibrationProfile` per `entry_id`
  to (a) a domain-level battery registry and (b) per-entry keyed profile
  collections. Existing single-profile data must migrate: wrap the entry's
  current `charger_label`/`battery_label`/`rated_capacity_wh` as the first
  registry identity and its profile as that identity's profile for this
  entry — never discard.
- `CyclestewardCoordinator` must expose the active battery identity and a
  profile-swap method; swapping must be refused (or queued) while a session
  is live (CHARGING/PROBING), since changing anchors mid-session invalidates
  an in-progress cutoff decision.
- Exactly one coordinator/watcher per config entry remains enforced; nothing
  here permits a second watcher against the same plug.
- `config_flow.py`'s `charger_label`/`battery_label`/`rated_capacity_wh`
  fields move from entry data to the registry; the entry keeps only
  meter-scoped operational inputs (`power_entity_id`, `plug_entity_id`,
  `temp_entity_id`, `margin_s`, guardrail limits).
- Calibration state surfaced to the user (e.g. `target_wattage` sensor
  availability) is now per (battery, meter) pairing — a battery calibrated on
  one plug shows uncalibrated on another, and the UX must make that legible
  rather than looking like data loss.

**Open:**
- Registry storage home: a domain-level HA `Store` vs. piggybacking on a
  designated entry — and its own migration/versioning story alongside the
  `ProfileStore` `STORAGE_VERSION` bump. (resolved: domain-level `Store`
  keyed `cyclesteward.registry`, spec D1 of
  `docs/specs/battery-registry-storage.md`)
- UX for registering a new battery identity: options flow, inline "add new"
  on the `active_battery` select, or a service call.
- Whether selecting a battery that is currently active on another entry
  should warn (same physical pack cannot charge in two places; a stale
  selection elsewhere is the likely cause).
- Whether switching `active_battery` mid-session is blocked outright or
  queued until `OFF_IDLE`/`DONE_LATCHED_OFF`.
- Whether `relay_cycles` and other diagnostic counters reset on battery swap
  or remain meter-lifetime cumulative.
- Future work, each needing its own evidence/ADR: anchor transfer across
  meters with learned offsets; curve-fingerprint confirmation assist.

## References

- ADR-0001: Smart plug wrapper
- ADR-0002: Wattage-anchor SoC estimation with active-Wh calibration
- ADR-0005: Guardrails and low-battery rescue
- ADR-0007: Calibration lifecycle and full-charge maintenance
- ADR-0011: Home Assistant entity and service surface
- ADR-0012: Finish-time scheduling and probe transparency
- ADR-0013: Adapt to the sensor's observed behavior, not one device's
- `custom_components/cyclesteward/profile_store.py`
- `custom_components/cyclesteward/__init__.py`
- `custom_components/cyclesteward/config_flow.py`
