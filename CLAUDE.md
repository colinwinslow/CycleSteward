# CLAUDE.md - CycleSteward Agent Contract

## Identity

CycleSteward is a Home Assistant custom-integration project for learning an
e-bike charger/battery wall-power signature from a metered smart plug and using
that learned profile to automate charge timing and charge cutoff.

The integration wraps normal chargers rather than replacing them. Its first use
case is a Shimano e-bike system plugged into an Aqara Zigbee metering smart plug,
but the design must stay general enough for any charger/battery combination with
a repeatable CC/CV-like curve. The core estimator should live outside Home
Assistant-specific I/O so it can be tested with fixtures before being exposed as
HA entities and services.

This project is developed agentically. The human provides direction and
oversight; the agent does the implementation. Work is reviewed by reading
commits, decision records (ADRs), specs, and the inspectable evidence that tests
produce.

## Session start: read this only

On session start, run `/startup`. The `SessionStart` hook in
`.claude/settings.json` performs the git drift-check automatically and surfaces
its output as context; `/startup` interprets that result, then reads `STATUS.md`.
The required read set is `STATUS.md` only. It is the single source for current
phase, current bounded packet, and the rolling session log.

Do not load other docs unless the work requires them. The doc map below tells
you when to load what.

## Doc map

| Question | Read |
|---|---|
| What's the current state of the project? | `STATUS.md` |
| What is this project, architecturally? | `docs/architecture/cyclesteward-architecture.md` |
| Why did we decide X? | `docs/decisions/NNNN-*.md` |
| What does feature Y do? | `docs/specs/<feature>.md` |
| What are the scenarios for feature Y? | `bdd/<feature>/<slug>-bdd.md` |
| Is Z still an open question? | `docs/research/<topic>.md` |
| What's the implementation plan for slice N? | `docs/implementation/<slug>-implementation-plan.md` |
| How does the project build/test? | This file, "Build & test" |
| What session commands exist? | `.claude/commands/` |

If the question does not fit the table, ask. Do not guess.

## Invariants (load-bearing; do not violate)

1. **Wrapper, not charger** - CycleSteward may control AC power to a user-selected
   metered plug and read optional sensors, but it must not bypass, emulate, or
   replace the original charger/BMS safety logic. (`ADR-0001`, `ADR-0005`)
2. **Estimates, not BMS truth** - User-facing charge state derived from wall
   power must be labeled as estimated and must carry uncertainty when the inputs
   are coarse or inferred. (`ADR-0002`, `ADR-0004`)
3. **Profile scope is narrow** - A learned profile belongs to one
   charger+battery+metering-device configuration. Changing any member invalidates
   or forks the profile. (`ADR-0002`, `ADR-0007`)
4. **Wattage is the primary SoC/cutoff signal; active Wh is for calibration** -
   Estimate SoC and trigger cutoff from instantaneous CC-phase wattage, mapped
   between two learned anchors. Use integrated `max(power_w - idle_w, 0)` for
   calibration (locating the target wattage) and as a max-energy guardrail, not
   as the runtime SoC metric. (`ADR-0002`)
5. **Learn curve features; do not hard-code universal thresholds** - Charger
   shape detection may use CC/CV features such as rising bulk power, peak/knee,
   taper, and completion, but fixed watt values and knee-equals-SoC rules are
   forbidden outside fixtures. (`ADR-0003`)
6. **Coarse SoC reports stay coarse** - Inputs such as 0-5 dots, ranges, and
   named anchors must be stored as intervals or labels, not silently converted
   to precise percentages. (`ADR-0004`)
7. **Guardrails bound automation failures** - Runtime, energy, temperature,
   stale-meter, command-failure, and relay-chatter guardrails are required for
   control slices even though the OEM charger remains the battery safety layer.
   (`ADR-0005`)
8. **Core model before HA plumbing** - The charge estimator, profile model, and
   state machine must be testable in pure Python before Home Assistant entity
   adapters wrap them. (`ADR-0006`)

For the deep "why" behind each, see the cited ADRs.

## Workflow

### BDD before implementation

Every implementation slice begins with a small, inspectable BDD that defines the
artifact proving success. Tests derive from the BDD; code makes the tests pass.
Scaffold a spec + paired BDD with `/spec <slug>`.

### Three layers of correctness proof

| Layer | Owns | When | Format |
|---|---|---|---|
| Unit tests (red/green TDD) | Failure paths, edge cases, regression net | Every code change; failing tests block commit | test runner output |
| BDD evidence | User-facing happy path + catastrophic/irreversible failures | After feature work; human reviews | Markdown evidence file referenced from the BDD |
| Anchor artifact | The simplest concrete observable version of the thing | Built first, before supporting code | For the first slice: profile-summary JSON from a CSV fixture |

### Verify on disk

A slice is not done until the real artifact has been verified on disk by reading
the changed files or generated outputs back and confirming expected content is
present. "Tests pass" is necessary but not sufficient.

### Anchor-artifact discipline

Build the simplest concrete observable version of the thing first, before
supporting infrastructure. For this project, the first visible thing should be a
fixture analyzer that outputs a learned profile summary, not a Home Assistant
config flow.

## Session commands

These are native Claude Code slash commands; each runs the prompt file under
`.claude/commands/`.

| Command | Command file | Purpose |
|---|---|---|
| `/startup` | `.claude/commands/startup.md` | Interpret the drift-check + read STATUS + identify next bounded packet + confirm proof |
| `/closeout` | `.claude/commands/closeout.md` | Update STATUS rolling log + sync doc indexes + run BDD-evidence review + commit |
| `/adr <slug>` | `.claude/commands/adr.md` | Scaffold a new ADR with auto-numbering |
| `/spec <slug>` | `.claude/commands/spec.md` | Scaffold a new spec + paired BDD |
| `/research <slug>` | `.claude/commands/research.md` | Scaffold a new research note |

## Review passes

These run as **subagents** (`.claude/agents/`), so the reviewer reads the diff in
its own isolated context instead of the rationalizations built up while
implementing.

| Review | Subagent | When | How to run |
|---|---|---|---|
| Architecture review | `.claude/agents/review-architecture.md` | Before completing a non-trivial implementation | Invoke the `review-architecture` subagent for a fresh, un-anchored read of the diff against the invariants |
| BDD-evidence review | `.claude/agents/review-bdd-evidence.md` | After a test run on a feature with BDD scenarios | Invoke the `review-bdd-evidence` subagent during `/closeout` |

## Build & test

```bash
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
```

Current test posture: seed scaffold only. The included test verifies that the
workflow and design docs expected by the first slice are present.

## Commit norms

- One commit per coherent change. Messages describe why, not just what.
- ADR commits: `[ADR-NNNN]` prefix. Spec commits: `[spec:<feature>]` prefix.
- Never skip hooks (`--no-verify`) unless the user explicitly asks. If a hook
  fails, fix the underlying issue and create a new commit; do not amend.
- Stage specific files. Never blanket `git add -A` / `git add .`.
- Ask before pushing. Default is commit-only.

## What is out of scope (now)

- Replacing or modifying OEM charger/BMS battery-safety behavior.
- Direct Shimano protocol integration or reading private Shimano battery data.
- Claiming precise BMS SoC from wall-power data alone.
- Supporting non-CC/CV charging chemistries in the first implementation.
- Building Home Assistant UI/plumbing before the pure-core anchor artifact.

## When in doubt

Ask the human. Direction is the human's call; implementation details are yours.
If a spec is ambiguous, surface the ambiguity in chat and write the resolution
into the spec before coding.
