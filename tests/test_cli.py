"""CLI anchor artifact: produce the JSON on disk, fail visibly on bad input."""

from __future__ import annotations

import json

from cyclesteward.cli import main

FIXTURE = "fixtures/synthetic-low-to-full.csv"


def test_analyze_fixture_writes_json(tmp_path, fixtures_dir):
    out = tmp_path / "profile-summary.json"
    code = main(
        [
            "analyze-fixture",
            "--input",
            str(fixtures_dir / "synthetic-low-to-full.csv"),
            "--idle-watts",
            "1.8",
            "--output",
            str(out),
        ]
    )
    assert code == 0
    assert out.exists()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["profile_id"] == "fixture:synthetic-low-to-full"
    assert data["anchors"]["watts_at_low"] == 69.0
    assert data["warnings"] == []


def test_malformed_input_exits_nonzero_and_writes_nothing(tmp_path, fixtures_dir, capsys):
    out = tmp_path / "should-not-exist.json"
    code = main(
        [
            "analyze-fixture",
            "--input",
            str(fixtures_dir / "malformed-missing-power.csv"),
            "--output",
            str(out),
        ]
    )
    assert code == 2
    assert not out.exists()
    assert "power_w" in capsys.readouterr().err


def test_stdout_mode_emits_json(fixtures_dir, capsys):
    code = main(
        [
            "analyze-fixture",
            "--input",
            str(fixtures_dir / "synthetic-low-to-full.csv"),
            "--idle-watts",
            "1.8",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["anchors"]["watts_at_transition"] == 84.0
