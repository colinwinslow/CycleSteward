# Probe CC/CV Disambiguation — BDD

## Status

Draft. Paired with [docs/specs/probe-cc-cv-disambiguation.md](../../docs/specs/probe-cc-cv-disambiguation.md).

## Why this BDD exists

The probe fires to estimate current SoC; this BDD pins the two distinct probe
outcomes (CC vs CV taper) and the SoC-latch behavior during taper so the
automation behaves correctly regardless of where in the charge curve the probe
catches the battery.

## Scenarios

### Scenario A — Probe classifies CC phase: wattage flat, start time updated

**Given** a `HASensorWatcher` with a calibrated profile (watts_at_low = 60 W,
watts_at_transition = 80 W), target_finish_time set 8 h ahead, and
WAITING_FOR_SCHEDULE state

**When** the watcher enters PROBING and receives `_MIN_PROBE_SAMPLES` (3) power
readings that are flat (e.g., 65 W, 66 W, 65 W) across the probe window

**Then**
- `_classify_probe_trend()` returns `"cc"`
- `probe_result` logbook event fires with `classification: "cc"` and a
  `computed_start_time` value that reflects the SoC-proportional remaining
  duration (later than the pessimistic start, earlier than the target)
- The plug is turned off; coordinator returns to WAITING_FOR_SCHEDULE

### Scenario B — Probe classifies CV taper: wattage falling, start time pushed late

**Given** the same watcher configuration as Scenario A

**When** the watcher enters PROBING and receives `_MIN_PROBE_SAMPLES` (3) power
readings that are clearly falling (e.g., 78 W, 65 W, 50 W — last_mean/first_mean ≈ 0.64 < 0.90)

**Then**
- `_classify_probe_trend()` returns `"cv_taper"`
- `probe_result` logbook event fires with `classification: "cv_taper"`,
  `first_mean_w`, `last_mean_w`, and a `computed_start_time` equal to
  `target_finish_time - margin`
- The plug is turned off; coordinator returns to WAITING_FOR_SCHEDULE

### Scenario C — Insufficient probe samples: falls back to timeout behavior

**Given** a watcher in PROBING state where the meter is unavailable for most of
the probe window, yielding fewer than `min_probe_samples` (3) watt readings
before the `max_probe_seconds` timeout expires

**Then**
- No CC/CV classification is attempted
- The controller's TURN_OFF (probe timeout) is honored
- `probe_result` logbook event fires with the existing timeout message (no
  `classification` field)
- `computed_start_time` remains the pessimistic start time

### Scenario D — SoC latch during CHARGE_TO_FULL taper

**Given** a `SessionController` in CHARGE_TO_FULL mode with a calibrated profile
(taper_floor_w known), where the session has built up a peak SoC estimate of
82%

**When** wattage drops below `taper_floor_w` (taper begins), and subsequent ticks
continue to see falling wattage

**Then**
- `tick()` returns `soc_estimate.estimated_soc_pct == 82.0` (the latched max)
  on every tick after taper start, not the (lower) value that `_estimate_soc`
  would return from the falling wattage
- `soc_estimate.low_confidence == True`
- `soc_estimate.note` contains `"taper phase: SoC held at session max"`
- When the taper duration threshold is met, the session transitions to
  DONE_LATCHED_OFF as normal
- After `reset()`, the latch is cleared and subsequent ticks compute SoC from
  wattage as normal

## Evidence

The implementing slice produces an evidence file at
`bdd/ha-adapter/probe-cc-cv-disambiguation-evidence.md` containing raw outputs
(not summaries) for each scenario, including the full content of the anchor
trace JSON and the pytest run output showing all scenarios green.
