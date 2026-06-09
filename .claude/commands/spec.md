---
description: Scaffold a new spec plus its paired BDD file under bdd/<feature>/.
argument-hint: <slug>
---

# `/spec <slug>` — Spec + BDD Scaffolder Protocol

Scaffold a new spec at `docs/specs/<slug>.md` and a paired BDD file at
`bdd/<feature>/<slug>-bdd.md`.

The slug is `$ARGUMENTS` (e.g. `windows-provider` or `profile-apply`).

## Steps

1. **Validate slug.** Lowercase, hyphen-separated. Ask if invalid.

2. **Decide the feature directory** for the BDD pair (`bdd/<feature>/`). Group
   BDDs by feature area. New top-level area → ask the user before creating a new
   `bdd/<feature>/` directory.

3. **Check for collision.** If `docs/specs/<slug>.md` or the BDD file exists,
   ask the user (overwrite, supersede, or pick a new slug).

4. **Create `docs/specs/<slug>.md`** from this template:

   ```markdown
   ---
   status: draft
   date: YYYY-MM-DD
   depends-on-adrs: []
   ---

   # <Feature>: <Short title>

   ## Status

   Draft. Defines the contract surface for <feature> per <relevant ADR>.

   ## Related docs

   - [bdd/<feature>/<slug>-bdd.md](../../bdd/<feature>/<slug>-bdd.md) — observable behavior
   - [STATUS.md](../../STATUS.md) — current phase and active work

   ## Context

   [Why does this feature exist? What user-visible behavior does it enable?]

   ## Behavior contract

   [The contract: public types, signatures, CLI flags, file outputs. Reference
   the ADRs that constrain it.]

   ## Anchor artifact

   [The simplest concrete observable version of the thing — built first. e.g.
   "one CLI command that returns one result for one fixture input."]

   ## Implementation order

   [Concrete-first: anchor artifact, then supporting code. Ordered slices.]

   ## Proof requirements

   1. [e.g. "Unit tests for X in <test path> green."]
   2. [e.g. "BDD scenarios in bdd/<feature>/<slug>-bdd.md pass."]
   3. [e.g. "Real-artifact proof produces expected output; eyes-on confirmed."]

   ## Non-goals

   [What this spec explicitly does NOT cover.]

   ## References

   - [Other specs, ADRs, architecture sections]
   ```

5. **Create `bdd/<feature>/<slug>-bdd.md`** from this scaffold:

   ```markdown
   # <Feature>: <Short title> — BDD

   ## Status

   Draft. Paired with [docs/specs/<slug>.md](../../docs/specs/<slug>.md).

   ## Why this BDD exists

   [1–2 sentences on the user-visible behavior this pins down.]

   ## Scenarios

   ### Scenario A — happy path: <one-line description>

   **Given** <setup state>
   **When** <triggering action>
   **Then** <observable result, with the artifact the user can inspect>

   ### Scenario B — <next case>

   ...

   ## Evidence

   The implementing slice produces an evidence file at
   `bdd/<feature>/<slug>-evidence.md` containing raw outputs (not summaries) for
   each scenario.
   ```

6. **Report both paths.** Status starts at `draft`; the user accepts to promote.

## Rules

- Specs are immutable once `accepted`. Supersede by writing a new spec.
- BDD lives in `bdd/<feature>/<slug>-bdd.md`, separate from the spec.
- Evidence files contain raw outputs, not "✓ passed" summaries (the
  BDD-evidence review pass checks this).
