"""Command-line anchor artifact.

    python -m cyclesteward.cli analyze-fixture \\
        --input fixtures/synthetic-low-to-full.csv \\
        --idle-watts 1.8 \\
        --output /tmp/profile-summary.json

Reads a charge-session CSV (a fixture, or Home Assistant history exported into
the same shape) and writes a deterministic profile-summary JSON.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .errors import FixtureError
from .profile import analyze
from .samples import parse_csv


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cyclesteward", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    analyze_cmd = sub.add_parser(
        "analyze-fixture",
        help="Analyze a charge-session CSV into a profile-summary JSON.",
    )
    analyze_cmd.add_argument("--input", required=True, help="Path to the charge-session CSV.")
    analyze_cmd.add_argument(
        "--idle-watts",
        type=float,
        default=None,
        help="Measured charger standby watts. If omitted, estimated as the lowest reading.",
    )
    analyze_cmd.add_argument(
        "--output",
        default=None,
        help="Path to write the profile-summary JSON. If omitted, writes to stdout.",
    )
    analyze_cmd.add_argument(
        "--profile-id",
        default=None,
        help="Profile id for the summary. Defaults to 'fixture:<input-stem>'.",
    )
    return parser


def _run_analyze(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    try:
        parsed = parse_csv(input_path)
    except FixtureError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    profile_id = args.profile_id or f"fixture:{input_path.stem}"
    summary = analyze(
        parsed.samples,
        profile_id=profile_id,
        idle_power_w=args.idle_watts,
        input_warnings=parsed.warnings,
    )
    payload = summary.to_json()

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(payload, encoding="utf-8")
        print(f"wrote {output_path}")
    else:
        sys.stdout.write(payload)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "analyze-fixture":
        return _run_analyze(args)
    parser.error(f"unknown command: {args.command}")
    return 2  # unreachable; parser.error exits


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
