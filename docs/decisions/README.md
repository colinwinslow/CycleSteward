# Architecture Decision Records

One file per decision: `NNNN-<slug>.md`, zero-padded, monotonic. Scaffold with
`/adr <slug>` (see `.claude/commands/adr.md`).

## Lifecycle

- ADRs are authored as `status: draft`.
- A `draft` is promoted to `accepted` once the decision is made.
- Accepted ADRs are immutable. To change a decision, write a new ADR that names
  the old one in `supersedes:` and set the old one's `superseded-by:`.

## Current ADRs

- 0001 - Smart plug wrapper
- 0002 - Active wall energy learned profiles
- 0003 - CC/CV curve feature learning
- 0004 - Coarse SoC input and uncertainty
- 0005 - Guardrails and low-battery rescue
- 0006 - Pure core before Home Assistant adapters
- 0007 - Calibration lifecycle and full-charge maintenance
