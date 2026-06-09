---
id: 0006
title: Pure core before Home Assistant adapters
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [architecture, testing, home-assistant]
---

# ADR-0006: Pure core before Home Assistant adapters

## Context

Home Assistant integrations have lifecycle, config-flow, entity, storage, and
async concerns that can obscure whether the core estimator works. The agentic
workflow kit also recommends building an anchor artifact before plumbing. The
project needs fixture-driven evidence that profile learning works before UI and
entity layers are added.

## Decision

**CycleSteward will keep the charge-session model, profile learner, estimator,
and state machine in a pure-Python core that can be tested without Home
Assistant.** The Home Assistant custom component will be an adapter around that
core.

## Rationale

- Pure fixtures make the model easy to test and review.
- The HA layer can evolve without changing estimation logic.
- A small CLI/profile-summary artifact is the fastest inspectable proof of the
  central idea.

## Consequences

**Enables:**
- Unit tests that do not require a full Home Assistant runtime.
- Fixture libraries for Shimano and non-Shimano chargers.
- Potential reuse in other automation contexts later.

**Constrains:**
- HA-specific entities and services must not own core estimation behavior.
- The first slice should be a fixture analyzer, not a config flow.

**Open:**
- Should the pure core become a separate package if the HA integration matures?

## References

- `docs/specs/fixture-analyzer-anchor.md`
- `bdd/anchor/fixture-analyzer-anchor-bdd.md`
