# Implementation plan: Fixture analyzer anchor artifact

## Packet

Implement the first pure-core artifact: read a charge-session CSV fixture and
write a deterministic profile-summary JSON.

## Why this packet first

It satisfies the agentic workflow kit's anchor-artifact rule. It proves the core
estimation idea in a small, reviewable way before Home Assistant config flows,
entities, storage, or async behavior are introduced.

## Proposed modules

```text
src/cyclesteward/
  fixtures.py       # CSV parsing and validation
  energy.py         # idle subtraction and Wh integration
  landmarks.py      # simple peak/taper/completion detection
  profile.py        # profile-summary dataclasses and JSON serialization
  cli.py            # optional command-line anchor artifact
```

## Suggested CLI

```bash
python -m cyclesteward.cli analyze-fixture \
  --input fixtures/synthetic-low-to-full.csv \
  --idle-watts 1.8 \
  --output /tmp/profile-summary.json
```

## Done means

- Unit tests cover parsing, active Wh integration, landmark extraction, and
  malformed input.
- `bdd/anchor/fixture-analyzer-anchor-evidence.md` contains raw command output
  and the generated JSON read back from disk.
- `STATUS.md` is updated during `/closeout` with the next bounded packet.
