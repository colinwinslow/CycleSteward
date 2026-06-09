from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_seed_contains_workflow_contract_and_first_bdd() -> None:
    required_paths = [
        "CLAUDE.md",
        "STATUS.md",
        ".claude/commands/startup.md",
        "docs/decisions/0001-smart-plug-wrapper.md",
        "docs/specs/fixture-analyzer-anchor.md",
        "bdd/anchor/fixture-analyzer-anchor-bdd.md",
    ]
    missing = [path for path in required_paths if not (ROOT / path).exists()]
    assert missing == []


def test_agent_contract_names_load_bearing_invariants() -> None:
    contract = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for invariant in [
        "Wrapper, not charger",
        "Estimates, not BMS truth",
        "Active wall energy is the primary progress metric",
        "Core model before HA plumbing",
    ]:
        assert invariant in contract
