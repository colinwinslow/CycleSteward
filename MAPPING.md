# Construct Mapping: Claude Code (native) ↔ Codex / VS Code

This workflow originated in a project driven by **Claude Code** and runs natively
on it: slash commands, subagents, and a lifecycle hook do the work the protocol
files describe. The kit was once ported to Codex (a leaner harness) and has now
been ported back to its native Claude Code form. This file records the mapping
both ways so the kit stays portable.

## The table

| Claude Code construct (this repo) | Codex / VS Code equivalent | Why |
|---|---|---|
| **`CLAUDE.md`** (project instructions, auto-loaded) | `AGENTS.md` (the open [agents.md](https://agents.md) standard) | Claude Code auto-loads `CLAUDE.md`; Codex auto-loads `AGENTS.md`. Same role — the always-on project contract. (Note Codex needs the **plural** `AGENTS.md`; a singular `AGENT.md` is not auto-loaded.) |
| **`.claude/commands/*.md`** (native slash commands) | `codex/*.md` protocol docs referenced from `AGENTS.md` | Claude Code runs `/startup`, `/closeout`, `/adr`, `/spec`, `/research` as first-class slash commands. Codex has no first-class slash command that runs a prompt file, so there the same procedure is a *documented protocol* the agent is told to follow. |
| **`.claude/agents/*.md`** (subagents, isolated context) | `codex/review-*.md` run as a standalone `codex exec` | The architecture review and BDD-evidence review run as subagents — fresh, isolated context for an honest read. Codex has no subagent system, so it approximates the isolation with a separate `codex exec` invocation. |
| **`.claude/settings.json` `SessionStart` hook** (auto drift-check) | Inline git commands written into the `/startup` protocol | Claude Code runs the git drift-check automatically on session start via a lifecycle hook. Codex has no hook parity, so the drift-check is written into the startup protocol as explicit commands the agent runs. |
| **`.claude/settings.json` permissions allowlist** | Codex approval modes | Claude Code governs tool/command approval through a per-pattern allowlist. Codex uses run modes (read-only / auto-edit / full-access). Configure to taste; the workflow doesn't depend on either. |
| MCP servers (e.g. a search tool) | MCP via `~/.codex/config.toml` | Both harnesses support MCP servers. Optional — not part of this core workflow. |

## What's native here vs. worth verifying elsewhere

- **Native in this repo:** Claude Code auto-loads `CLAUDE.md`; `.claude/commands/`
  give real `/startup`-style slash commands; `.claude/agents/` give isolated
  review subagents; the `SessionStart` hook runs the drift-check automatically.
- **If you port to Codex:** re-express the slash commands as protocol docs under
  `codex/`, run the reviews as standalone `codex exec`, and move the drift-check
  git commands inline into the startup protocol. (See the table above.)

## The one principle to keep

Whichever harness runs it, every procedure is also a **readable protocol file**.
That's what makes the kit portable: Claude Code automates more of it through
slash commands, subagents, and hooks, but a human (or a leaner agent) can follow
the same markdown protocols by hand and get the same result.
