# CycleSteward HA seed repository

CycleSteward is a working-name seed for a Home Assistant custom integration that
turns a compatible e-bike charger plugged into a metered smart plug into a
learned smart-charger wrapper.

The initial motivating setup is an Xtracycle Swoop ASM with a Shimano e-bike
battery/charger and an Aqara Zigbee metering smart plug. The design intentionally
keeps that as a reference case, not a hard-coded dependency. The integration
should be general enough to learn the wall-power signature of any charger/battery
combination with a repeatable CC/CV-like charge curve.

## What this repo contains now

This is a design seed, not a production Home Assistant integration yet. It
contains:

- the agentic workflow kit protocols as Claude Code slash commands in
  `.claude/commands/` and review subagents in `.claude/agents/`
- a filled `CLAUDE.md`, `STATUS.md`, and `HANDOFF.md`
- initial ADRs in `docs/decisions/`
- draft specs in `docs/specs/`
- paired BDD contracts in `bdd/`
- research notes for fast chargers, naming, and open design questions
- a tiny Python package/test scaffold so the agent has a real repo shape to extend

## First implementation slice

Start with `/startup`. The next bounded packet in `STATUS.md` is the fixture
analyzer anchor artifact: a small pure-Python CLI or module that reads a session
CSV fixture and writes a learned profile summary JSON. That proves the core
modeling idea before any Home Assistant plumbing is built.

## Working-name candidates

The current repo name uses `CycleSteward`. Other candidates are recorded in
`docs/research/naming.md`.
