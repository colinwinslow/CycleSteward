# Agentic Workflow Kit — How to Use

A portable, agent-driven engineering workflow extracted from a real
multi-project codebase and running natively on **Claude Code**. It gives you a
repeatable session loop, a disciplined doc structure, and review passes that
keep an AI agent honest.

You don't need any specific tool to *follow* it — every step is a readable
markdown protocol. Claude Code (or Codex, or a human) executes the protocols;
Claude Code just automates more of it through slash commands, subagents, and a
lifecycle hook. (See `MAPPING.md` for the Codex equivalents.)

---

## 1. The philosophy (why this exists)

Agentic development falls apart in predictable ways: the agent loses the thread
between sessions, drifts from the architecture, claims "done" without proof, and
makes silent decisions nobody recorded. This workflow is a set of habits that
prevent each of those.

| Principle | What it means | The failure it prevents |
|---|---|---|
| **Single source of truth** | `STATUS.md` holds current state; `/startup` reads only it | Agent re-deriving context from scratch (or wrongly) each session |
| **Bounded packets** | Work is sliced into one shippable unit with a defined proof | Open-ended sessions that sprawl and never close |
| **BDD before implementation** | Write the scenario that defines success first; code makes it pass | Building the wrong thing; "done" with no definition |
| **Three layers of proof** | Unit tests + BDD evidence + an anchor artifact | False confidence from green tests that prove nothing user-visible |
| **Verify on disk** | A slice isn't done until the real artifact is confirmed on disk | "Tests pass" mistaken for "the feature works" |
| **Anchor-artifact first** | Build the simplest observable version before plumbing | Infrastructure built for a feature that never materializes |
| **Decisions are recorded** | Every non-obvious choice becomes an ADR | Re-litigating settled questions; mystery architecture |
| **Review passes** | An architecture pass and a BDD-evidence pass before closeout | Invariant violations and dishonest evidence slipping through |
| **Rolling session log** | `STATUS.md` keeps the last 5 sessions; older ones live in git | Continuity docs that grow without bound |

---

## 2. The session loop

```
  /startup  ──►  do the bounded packet  ──►  review passes  ──►  /closeout
     ▲                                                                │
     └────────────────────────────────────────────────────────────--┘
```

1. **`/startup`** — the `SessionStart` hook drift-checks git automatically; the
   command interprets that result, reads `STATUS.md`, names the next bounded
   packet, and confirms the proof required *before* touching code.
2. **Do the work** — anchor artifact first, then supporting code, tests red→green.
3. **Review** — invoke the `review-architecture` subagent for non-trivial
   changes; invoke the `review-bdd-evidence` subagent if scenarios were
   implemented.
4. **`/closeout`** — update `STATUS.md` (rolling log), sync doc indexes, commit
   with a completion report. Ask before pushing.

Each slash command lives in `.claude/commands/`; each review subagent lives in
`.claude/agents/`. They're self-contained.

---

## 3. Operating it in Claude Code

- **`CLAUDE.md` is read automatically** on session start. It points at
  everything else. Keep it short.
- **Session commands are real slash commands.** Typing `/startup`, `/closeout`,
  `/adr`, `/spec`, or `/research` runs the matching prompt file in
  `.claude/commands/`. The file is also a readable protocol, so a human can
  follow it without the slash command.
- **Review passes are subagents:**
  - *Architecture review* → the `review-architecture` subagent reads the diff in
    its own isolated context, so it isn't anchored by the implementation work.
  - *BDD-evidence review* → the `review-bdd-evidence` subagent checks the
    evidence you just produced; run it during `/closeout`.
- **The drift-check is a `SessionStart` hook.** It runs git fetch/status/rev-list
  automatically and surfaces the result as context for `/startup` to interpret.
  Configure it (and the permissions allowlist) in `.claude/settings.json`.

---

## 4. What's in the kit

```
agentic-workflow-kit/
  HOW-TO-USE.md            ← you are here
  MAPPING.md               ← Claude Code ↔ Codex construct mapping
  CLAUDE.md                ← the project contract (fill in the placeholders)
  .claude/
    settings.json          ← SessionStart drift-check hook + permissions allowlist
    commands/
      startup.md           ← /startup slash command
      closeout.md          ← /closeout slash command
      adr.md               ← /adr scaffolder
      spec.md              ← /spec (spec + BDD) scaffolder
      research.md          ← /research scaffolder
    agents/
      review-architecture.md   ← architecture review subagent
      review-bdd-evidence.md   ← BDD-evidence review subagent
  templates/
    STATUS.md              ← current-state file (the heartbeat)
    HANDOFF.md             ← slow-changing orientation doc
    docs/decisions/        ← ADR index + template
    docs/specs/            ← spec index + template
    docs/research/         ← research index + template
    bdd/README.md          ← BDD-tree + evidence convention
```

---

## 5. Setup checklist (copy into your own repo)

1. **Copy** the kit's contents into your repo:
   - `CLAUDE.md` → repo root
   - `.claude/` → repo root (commands, agents, settings.json)
   - `templates/STATUS.md` → repo root as `STATUS.md`
   - `templates/HANDOFF.md` → repo root as `HANDOFF.md`
   - `templates/docs/*` → `docs/`
   - `templates/bdd/README.md` → `bdd/README.md`
2. **Fill in `CLAUDE.md`**: replace every `<PLACEHOLDER>`. The most important
   section is **Invariants** — the 3–8 load-bearing rules of *your* project.
   The architecture review subagent checks against these, so they must be real
   and specific.
3. **Fill in `STATUS.md`**: current phase, the first bounded packet, an empty
   rolling log.
4. **Write your first ADR** with `/adr` for any architecture you've already
   committed to (so it's recorded, not implicit).
5. **Adjust `CLAUDE.md` "Build & test"** to your actual commands, and the
   `.claude/settings.json` permissions allowlist to taste.
6. **Run `/startup`** and confirm the agent grounds correctly.

---

## 6. Conventions that matter

- **One ADR per decision; immutable once accepted.** Change a decision by
  superseding, not editing. See `docs/decisions/README.md`.
- **One spec per feature; scenarios in `bdd/`, not inline.** See
  `docs/specs/README.md` and `bdd/README.md`.
- **Evidence files show raw output, never "✓ passed."** This is what makes the
  BDD-evidence review meaningful.
- **`STATUS.md` rolling log stays at 5 entries.** Trim at `/closeout`.
- **Commit messages say *why*.** ADR commits get `[ADR-NNNN]`; spec commits get
  `[spec:<feature>]`.

That's the whole system. It's deliberately small — the value is in following it
every session, not in the number of files.
