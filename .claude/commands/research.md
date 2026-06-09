---
description: Scaffold a new research note under docs/research/.
argument-hint: <slug>
---

# `/research <slug>` — Research Note Scaffolder Protocol

Scaffold a research note at `docs/research/<slug>.md`.

The topic slug is `$ARGUMENTS` (e.g. `packaging-strategy` or `rollback-tradeoffs`).

## Steps

1. **Validate slug.** Lowercase, hyphen-separated. Ask if invalid.

2. **Check for collision.** If it exists, ask the user (overwrite, append, or
   pick a new slug).

3. **Create `docs/research/<slug>.md`** from this template:

   ```markdown
   ---
   title: <Human-readable topic>
   status: open
   date: YYYY-MM-DD
   ---

   # Research: <Topic>

   ## Question

   [What are we trying to figure out?]

   ## Context

   [Why does this matter? What downstream decision depends on it? Which ADR or
   spec would change based on the resolution?]

   ## Notes

   [Free-form. Add sections as the thinking takes shape.]

   ## Open sub-questions

   - ...

   ## Resolution

   [When this promotes to a spec or ADR, link it here. When abandoned, say why.]
   ```

4. **Report the path.**

## Rules

- Research notes are not load-bearing decisions. They are scratch space that
  may or may not promote.
- When the thinking stabilizes, promote: write a spec (`/spec`) or ADR
  (`/adr`), then update the note's `Resolution` and `status`
  (`promoted-to-spec`, `promoted-to-adr`, or `abandoned`).
