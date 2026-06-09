---
id: 0004
title: Coarse SoC input and uncertainty
status: accepted
date: 2026-06-08
supersedes: []
superseded-by: null
tags: [soc, uncertainty, ux]
---

# ADR-0004: Coarse SoC input and uncertainty

## Context

The motivating bike does not report a precise percentage to the user; it shows
0-5 dots. It may show zero dots when assist stops while still retaining enough
energy for lights and electronic shifting. Other bikes may report exact
percentages, coarse bars, named states, app-derived percentages, or no SoC at
all.

## Decision

**CycleSteward will let users specify the form and coarseness of their SoC input
and will store those reports as uncertain intervals or named anchors rather than
precise truth.** Supported input types should include percentage with resolution,
N-of-M segments/dots, explicit range, named anchors such as `display_empty` and
`full`, and unknown.

## Rationale

- A 0-5 dot display is too coarse to be treated as precise 0%, 20%, 40%, etc.
- Preserving uncertainty lets the estimator be honest and conservative.
- Named anchors match real e-bike behavior better than pretending the display
  maps linearly to electrochemical SoC.

## Consequences

**Enables:**
- Calibration from coarse real-world bike displays.
- Profiles that distinguish display-empty, assist-cutoff-empty, and true pack
  empty.
- Better UX for bikes with no percentage readout.

**Constrains:**
- Session-start inference may have wide uncertainty when the user enters only a
  dot count.
- BDDs and tests must verify uncertainty ranges, not exact percentages, for
  coarse reports.

**Open:**
- Should the default N-of-M segment model use equal-width intervals, user-tuned
  intervals, or learned intervals?
- How should the UI explain uncertainty without overwhelming users?

## References

- ADR-0002: Active wall energy learned profiles
- ADR-0007: Calibration lifecycle and full-charge maintenance
