---
description: Ground the session — interpret the git drift-check, read STATUS, name the next bounded packet, confirm the proof.
---

# `/startup` — Session Start Protocol

Use this when the user says `/startup` or asks to start a session. Ground the
session before changing anything.

The git **drift-check runs automatically** via the `SessionStart` hook in
`.claude/settings.json` — its output is already in your context. This protocol
interprets that result and grounds the rest of the session. (If the hook output
is missing, run the drift-check commands in step 1 yourself.)

## Steps

1. **Interpret the drift check.** The hook ran, from the repo root:

   ```bash
   git fetch origin
   git status --porcelain
   git rev-list --count main..origin/main    # commits behind origin
   ```

   - If the working tree is **non-empty** (uncommitted changes): surface to the
     user and do **not** proceed without their decision — stash, leave in place,
     or commit (user picks). Stash command:
     `git stash push --include-untracked --message "auto-stash from /startup <DATE>"`.
   - If `main` is **behind** `origin/main`: `git pull --ff-only origin main` and
     surface the new commits.
   - Re-run `git status --porcelain` to confirm clean.

   > NOTE: if your project has legitimate working-tree churn (e.g. a vendored
   > dependency dir), exclude it: `git status --porcelain | grep -v '<path>/'`.

2. **Read `STATUS.md` only.** Do not load other docs unless the work requires
   them. The doc map in `CLAUDE.md` says when to load what.

3. **Identify the next bounded packet** from `STATUS.md` "Active work" /
   "Next bounded packet". A *bounded packet* is one coherent, shippable unit of
   work with a clear proof — not an open-ended phase.

4. **Confirm what kind of work this session is:** implementation, research,
   BDD authoring, ADR drafting, or a mix.

5. **Confirm the proof required** for the next packet *before any code changes
   begin*. (Which unit tests? Which BDD scenarios? What real artifact verified
   on disk?)

6. **Report back:**
   - drift-check result (clean / fast-forwarded / stash created / pending user)
   - current phase
   - next bounded packet
   - kind of work
   - proof required
   - any blockers
   - any conflicts in the docs (stop and surface rather than normalize away)

## Rules

- Do not invent project direction. It comes from `STATUS.md` and the user.
- Do not begin implementation until the next packet is clear and the proof is
  confirmed.
- If docs conflict, report the conflict and wait for resolution.
- Keep the read set minimal: `STATUS.md`. Other docs load only when the work
  requires them.
- Never start grounding while the checkout has drifted state without an explicit
  user decision.
