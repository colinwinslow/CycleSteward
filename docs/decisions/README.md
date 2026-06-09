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
- 0002 - Wattage-anchor SoC estimation with active-Wh calibration
- 0003 - CC/CV curve feature learning
- 0004 - Coarse SoC input and uncertainty
- 0005 - Guardrails and low-battery rescue
- 0006 - Pure core before Home Assistant adapters
- 0007 - Calibration lifecycle and full-charge maintenance
- 0008 - Temperature-aware charging and storage policy
- 0009 - Charge modes, scheduling, and safe defaults
- 0010 - Calibrating the pure core on Home Assistant history
- 0011 - Home Assistant entity and service surface
- 0012 - Finish-time scheduling and probe transparency
