# Token Tracking Protocol (Claude Code)

Use this only when `claude/workflow-config.json` has `"token_tracking": true`.

Token tracking attaches local Claude Code usage metadata to commits through Git
hooks. It reads session data from `~/.claude/projects/` (Claude Code's local
session JSONL files) rather than Codex's `~/.codex/` history.

The formal JSON Schema for `Claude-Token-Usage` lives at
`docs/schemas/claude-token-usage-v1.schema.json`.

## How it differs from the Codex version

| Aspect | Codex | Claude Code |
|---|---|---|
| Session data source | `~/.codex/sessions/*.jsonl` | `~/.claude/projects/<encoded-path>/*.jsonl` |
| Token accounting | Cumulative totals → compute deltas | Per-turn counts → sum directly |
| Token fields | `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens` | `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens` |
| Commit trailer | `Codex-Token-Usage` | `Claude-Token-Usage` |
| Schema | `codex-token-usage/v1` | `claude-token-usage/v1` |
| Python source | `scripts/codex_token_usage.py` | `scripts/cc_token_usage.py` |
| Hook launcher | `scripts/git-hooks/run-codex-token-helper.sh` | `scripts/cc-hooks/run-cc-token-helper.sh` |
| Startup trigger | Manual step in `/startup` | SessionStart hook in `.claude/settings.json` |

## Token fields

Claude Code's Anthropic API responses break input into three categories:

- **`input_tokens`** — uncached input tokens processed normally
- **`cache_creation_input_tokens`** — tokens written to a new prompt cache entry
- **`cache_read_input_tokens`** — tokens served from an existing cache entry
- **`output_tokens`** — generated output tokens

`total_tokens` in the trailer = sum of all four. Cost calculation requires all
three input categories because they carry different per-token rates
(see `claude/pricing.json`).

## Startup

The `.claude/settings.json` `SessionStart` hook runs the startup offload
automatically. If the hook isn't active, run manually:

```bash
bash scripts/cc-hooks/run-cc-token-helper.sh startup
```

This configures local `core.hooksPath` to `scripts/cc-hooks`, initializes the
ignored token baseline from current `~/.claude/projects/` session history, and
records the session-start marker.

If no local Claude Code session history exists yet for this project, the helper
records the session marker but leaves hook routing unchanged and prints the
baseline action to retry later.

## Closeout

Commit normally. Do not generate or paste token metadata manually.

The installed hooks manage:

- `prepare-commit-msg`: injects/replaces `Claude-Token-Usage: {...}`
- `commit-msg`: validates the token trailer schema
- `post-commit`: refreshes the local ignored token baseline

## Trailer

`Claude-Token-Usage` stores aggregate token counts, model rows, totals, local
baseline timing, and optional durable work metadata. It is the authoritative
aggregate commit delta.

Neither the trailer nor the baseline may store prompts, transcripts, file
paths, session IDs, credentials, or cost estimates.

When a branch name contains a Jira-style key such as `KAG-482`, the helper
adds:

```json
"work": {"system": "jira", "id": "KAG-482", "source": "branch"}
```

For normal Git commits, set `CC_WORK_ID` / `CC_WORK_SYSTEM` when the branch
is not the durable work reference.

Token deltas are additive across commits. The optional session `elapsed_seconds`
value is a startup-to-commit wall-clock observation for that commit only; do
not sum it across commits.

## Rules

- Never write cost or credits into git commit trailers — display and local
  ledger only (see `claude/spend-tracking.md`).
- Never store prompts, transcripts, file paths, session IDs, or credentials in
  any trailer or baseline file.
- `build/cc-token-usage/` is ignored via `.git/info/exclude`; never commit it.
