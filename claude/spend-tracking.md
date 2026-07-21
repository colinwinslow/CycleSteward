# Spend Tracking Protocol (Claude Code)

Use this only when `claude/workflow-config.json` has `"spend_tracking": true`.

Spend tracking renders a **status box** and a **gas-gauge footer** at
`/startup` and `/closeout` that show **tokens and dollars** together:

- **Tokens** come from Claude Code's own session history — the local
  `~/.claude/projects/` JSONL files, parsed by `scripts/cc_token_usage.py`.
- **Dollars** are computed at render time from `claude/pricing.json` (Anthropic
  per-token rates).

It is **display + local-ledger only**. Cost figures are never written into git
commit trailers.

## Cross-repo by design

Every repo using the kit appends to **one shared ledger above all repos**:

```
~/.agentic-workflow-kit/spend-ledger-claude.csv      (override dir with CC_SPEND_DIR)
```

The gauge reads the whole ledger, so a developer working across 2–3 repos sees
one combined daily/weekly/monthly total, split per repo.

> **Kept separate from the Codex ledger.** Codex writes `spend-ledger.csv` in the
> same shared directory; Claude writes `spend-ledger-claude.csv`. They are
> deliberately distinct files because the two tools' token columns differ
> (Codex has `cached_input_tokens` + `reasoning_output_tokens`; Claude has
> `cache_creation_input_tokens` + `cache_read_input_tokens`), so one CSV can't
> hold both without a header collision. The daily-dashboard latch is likewise
> per-tool (`dashboard-shown-claude.txt`).

## Budget

- **Weekly budget: $500** (the gas-gauge cap). Override with `CC_WEEKLY_BUDGET_USD`.
- **Daily soft cap: $100**. Exceeding the daily cap is a 🟡 watch; the weekly
  gauge turns 🔴 at 80%.

Both live in `claude/pricing.json` (`weekly_budget_usd`, `daily_budget_usd`).

## Startup

```bash
bash scripts/cc-hooks/run-cc-spend.sh record --event startup
bash scripts/cc-hooks/run-cc-spend.sh dashboard --packet "<next packet>" --next "STATUS.md"
bash scripts/cc-hooks/run-cc-spend.sh gauge --tier auto
```

`record --event startup` snapshots this repo's cumulative Claude tokens into a
local baseline (`build/cc-token-usage/spend-baseline.json`) and appends a
startup timing row to the ledger.

## Closeout

```bash
bash scripts/cc-hooks/run-cc-spend.sh mark-closeout          # step 0 of /closeout
bash scripts/cc-hooks/run-cc-spend.sh refresh-pricing        # re-sync rates if stale
bash scripts/cc-hooks/run-cc-spend.sh record --event closeout
bash scripts/cc-hooks/run-cc-spend.sh gauge --tier thicker
```

`record --event closeout` computes `cumulative_now − startup_baseline` per
model, prices it, appends a `session_delta` row, then advances the baseline.

Run `refresh-pricing` **before** `record`, so the session is priced at current
rates rather than last week's.

## Keeping rates current

A stale rate card is silently wrong rather than loudly broken — the gauge keeps
rendering a confident dollar figure computed from obsolete prices. Two
mechanisms keep it honest, covering different failure modes:

**Effective-dated rates (no network).** A scheduled change that is already
published is stored as dated windows and resolved against the current date:

```json
"claude-sonnet-5": [
  { "until": "2026-08-31", "input": 2.00, "output": 10.00, "...": "..." },
  { "from":  "2026-09-01", "input": 3.00, "output": 15.00, "...": "..." }
]
```

The flip happens on schedule even on a machine that never refreshes. A model
with no scheduled change stays a plain rate object; both forms are accepted.

**Refresh from the published card.** `refresh-pricing` re-parses Anthropic's
pricing table and rewrites `claude/pricing.json`, catching anything unforeseen —
a new model, an unannounced change. There is no pricing API (`/v1/models`
returns capabilities but not rates), so the public docs page is the source; no
API key is needed.

| Behaviour | Detail |
|---|---|
| Cadence | Only fetches when `fetched` is ≥ 7 days old. `--force` overrides; `--max-age-days N` retunes. |
| On change | Rewrites the file and prints a per-model before/after diff, then asks you to review it before committing. The rates land in your working tree — **your commit review is the gate**. |
| On failure | Warns with the cached table's age and **exits 0**. A DNS hiccup or a docs-format change must never block a closeout. |
| Preserved | `weekly_budget_usd`, `daily_budget_usd`, `credit_usd`, and `default_model` are yours, not Anthropic's, and are never overwritten. |
| Source override | `CC_PRICING_URL` points at a mirror or a local copy. |

Aliases shadowed by a real model entry are dropped on refresh: an alias resolves
*before* the model table, so once the card lists `claude-opus-4` ($15/MTok) an
alias pointing it at `claude-opus-4-8` ($5/MTok) would misprice it 3×.

## Pricing & cost calculation

Claude Code has three distinct input token categories (unlike Codex's one):

```
cost = (input_tokens * input_rate
        + cache_creation_input_tokens * cache_write_rate
        + cache_read_input_tokens * cache_read_rate
        + output_tokens * output_rate) / 1_000_000
```

Cache reads are billed at 10% of input rate; cache creation at 125% of input
rate. Heavy prompt caching significantly reduces actual cost vs. naive
all-input estimates.

## Rules

- Read-only and **non-blocking**: any error degrades to one line + exit 0.
- Never write cost or credits into git commit trailers.
- The ledger is local machine state; do not commit it into any repo's history.
