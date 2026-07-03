---
status: accepted
date: 2026-07-03
depends-on-adrs: [0002, 0003, 0012]
---

# Probe CC/CV Disambiguation: classify the probe window and latch SoC during taper

## Status

Accepted. Implemented 2026-07-03. Closes packet 5 / review finding F7.

## Related docs

- [bdd/ha-adapter/probe-cc-cv-disambiguation-bdd.md](../../bdd/ha-adapter/probe-cc-cv-disambiguation-bdd.md) — observable behavior
- [STATUS.md](../../STATUS.md) — current phase and active work
- [ADR-0002](../decisions/0002-wattage-anchor-soc-estimation.md) — wattage is the primary SoC signal; CV taper makes it unreliable
- [ADR-0003](../decisions/0003-cc-cv-curve-feature-learning.md) — learn curve features, never hard-code universal thresholds
- [ADR-0012](../decisions/0012-finish-time-scheduling-and-probe-transparency.md) — probe mechanism and computed_start_time contract

## Context

The scheduling probe fires once per cycle to estimate current SoC and refine
`computed_start_time`. The existing probe logic grabs the first wattage sample
where `SocEstimate.low_confidence` is False. This works well when the charger is
in the CC (constant-current) bulk phase — wattage is flat or rising and maps
cleanly to SoC via the profile anchors.

It fails in two ways:

1. **CV taper sampled by mistake.** When the battery is near-full at probe time,
   the charger may already be in the CV (constant-voltage) taper phase: wattage
   is falling. The `low_confidence` flag catches obvious cases (wattage above
   `watts_at_transition`), but a falling trend within the CC-looking range is not
   caught. The probe may return a low SoC estimate and schedule an unnecessarily
   early start.

2. **SoC display counts down during taper.** Once taper begins during a
   CHARGE_TO_FULL session, wattage falls. `_estimate_soc()` maps this falling
   wattage back to a lower (and incorrect) SoC estimate, so the UI shows the
   battery appearing to lose charge as it finishes charging.

This spec addresses both:
- **Probe side:** accumulate samples across the probe window, classify the trend
  as CC or CV taper, and handle each case appropriately.
- **Session side:** latch `soc_estimate` at the session maximum once taper begins,
  so the display holds rather than counting down.

## Behavior contract

### Probe CC/CV classification (`custom_components/cyclesteward/watcher.py`)

The watcher accumulates `(timestamp, watts)` tuples in a `_probe_samples` list
during the PROBING window. Classification runs at probe conclusion (sufficient
samples gathered or timeout reached).

**Classification algorithm** (D1):

Given N = `len(_probe_samples)`:
- If N < `min_probe_samples` (default: 3): **insufficient** — fall back to
  existing first-stable-non-low-confidence behavior, or timeout.
- Else: compute `first_mean = mean(watts for first ⌊N/2⌋ samples)` and
  `last_mean = mean(watts for last ⌊N/2⌋ samples)`.
  - If `last_mean / first_mean >= cv_falling_ratio` (default: 0.90): **CC** —
    flat or rising; use existing SoC-to-start-time calculation.
  - Else (`last_mean / first_mean < 0.90`): **CV taper** — battery near-full;
    push `computed_start_time` late (see D2).

Both thresholds (`min_probe_samples`, `cv_falling_ratio`) live in `HASensorWatcher`
as class-level constants. They must not be tuned to a specific plug or battery.
They distinguish a trend direction, not a device-specific wattage level (ADR-0003).

**CC path** (no change to existing logic):
- Use the profile's `estimated_duration_s()` and the SoC estimate to compute
  `computed_start_time` as today.
- Fire `probe_result` logbook event with `classification: "cc"` added to the
  event data dict.

**CV taper path** (new) (D2):
- Battery is near-full; the charge session will be short.
- Set `computed_start_time = target_finish_time - timedelta(seconds=margin_s)`.
  (Start as late as possible while still meeting the finish-time target.)
- Call `coordinator.end_probe(now)` and turn the plug off.
- Fire `probe_result` logbook event with:
  - `classification: "cv_taper"`
  - `computed_start_time` (ISO 8601)
  - `first_mean_w`, `last_mean_w` (for diagnosis)

**Insufficient-samples path**: If the probe concludes (timeout) with fewer than
`min_probe_samples`, the controller's TURN_OFF is honored as today, and the
watcher fires `probe_result` with the existing timeout message. No classification
field is added. This path is unchanged from the current timeout handling.

### SoC latch during taper (`src/cyclesteward/session_control.py`)

`SessionController` gains:
- `_session_max_soc_pct: Optional[float]` — tracks the highest SoC estimate seen
  during the current CHARGING session. Updated on every tick that produces a
  non-None SoC estimate while CHARGING.
- `_taper_latched: bool` — set to True the first time `_taper_start` becomes
  non-None during CHARGE_TO_FULL. Once latched, `tick()` returns
  `_session_max_soc_pct` wrapped in a `SocEstimate` (with `low_confidence=True`
  and a note `"taper phase: SoC held at session max"`) instead of calling
  `_estimate_soc(power_w)`.

Both fields reset in `reset()`.

`_taper_latched` is set in the existing `CHARGE_TO_FULL` branch of `tick()`, at
the point where `_taper_start` is first assigned. No new state is introduced
into `SessionState`.

When the profile is not calibrated (`_session_max_soc_pct is None` at taper
start), the latch is skipped and `_estimate_soc` continues to be called as
before.

## Embedded decisions

**D1 — Classification thresholds:**
`min_probe_samples = 3`, `cv_falling_ratio = 0.90`. Three samples is the minimum
to make a trend meaningful; 10% falling ratio is a clear direction signal that
tolerates ordinary CC wattage wobble (typical Shimano variation ≤ 3%). These are
constants, not user-configurable. They must be revisited if we get fixture data
showing false positives on noisy plugs.

**D2 — CV-taper `computed_start_time`:**
Set to `target_finish_time - timedelta(seconds=margin_s)`. This is the latest
defensible start: a near-full battery needs only a short top-up, so we give it
the full margin but no more. The existing max-runtime guardrail caps runaway
(ADR-0005 A).

**D3 — CC classification replaces `not low_confidence` filter:**
When sufficient samples are available and the trend is classified as CC, the
watcher uses the wattage value from the probe window (average of the last half)
rather than the first non-low-confidence sample. This is more representative of
the stable CC-phase wattage, and removes the dependency on the `low_confidence`
flag for probe termination. The `low_confidence` flag on the `SocEstimate` still
propagates into the `probe_result` event data for transparency.

## Anchor artifact

A deterministic trace JSON at `bdd/ha-adapter/probe-cc-cv-disambiguation-trace.json`
produced by a unit test, containing:
- A CC-classified probe result (wattage flat across samples, classification field
  present, `computed_start_time` updated using SoC).
- A CV-taper probe result (wattage falling, classification `"cv_taper"`,
  `computed_start_time` set to `target_finish_time - margin`).
- A SoC-latch sequence: tick-by-tick output showing `soc_estimate` held at max
  after taper begins, then DONE_LATCHED_OFF.

## Implementation order

1. **SoC latch** (pure core; no HA dependency): add `_session_max_soc_pct` and
   `_taper_latched` to `SessionController`. Unit tests first; make them green.
   No watcher changes yet.

2. **Probe sample accumulation** (watcher): add `_probe_samples` list; populate
   it during each PROBING tick with `(now, power_w)` when `power_w is not None`.
   No classification logic yet — just confirm accumulation in tests.

3. **CC/CV classification** (watcher): add `_classify_probe_trend()` helper;
   integrate into the probe-reading section. Replace the first-stable-reading
   trigger with the classification-based trigger. Add unit tests for CC, CV, and
   insufficient-samples paths.

4. **Anchor artifact**: write the trace test that produces `probe-cc-cv-disambiguation-trace.json`.

5. **BDD evidence** (scenarios A–D).

## Proof requirements

1. Unit tests in `tests/test_session_control.py` for the SoC latch: taper begins
   → `soc_estimate` returns latched max with `low_confidence=True`; reset clears
   latch; no-profile case falls through without latch.
2. Unit tests in `tests/test_ha_wiring.py` (or a new test file) for
   `_classify_probe_trend()`: CC case, CV case, insufficient-samples case,
   edge case where first mean is zero.
3. BDD scenarios A–D in `bdd/ha-adapter/probe-cc-cv-disambiguation-bdd.md`
   evidenced by a test run with raw output.
4. Anchor trace verified on disk: `bdd/ha-adapter/probe-cc-cv-disambiguation-trace.json`
   read back and CC/CV classification fields confirmed present.
5. Full offline test suite (`python -m pytest`) green; `ruff check .` clean.

## Non-goals

- Modifying the profile calibration logic or how anchors are learned.
- Changing the probe cadence or when the probe fires (ADR-0012 B is unchanged).
- Adding a new `SessionState` for "in taper but not done."
- Real-time CC/CV classification outside the probe window — this spec covers only
  the probe window and the taper-latch during CHARGE_TO_FULL.
- Supporting non-CC/CV charging profiles (out of scope per CLAUDE.md).

## References

- `src/cyclesteward/session_control.py` — `SessionController`, `_taper_start`, `_estimate_soc()`
- `custom_components/cyclesteward/watcher.py` — `HASensorWatcher._do_tick()`, probe reading section
- `docs/specs/finish-time-scheduling.md` — probe infrastructure this extends
- `docs/specs/stale-meter-guardrail.md` — precedent for probe-window None handling
