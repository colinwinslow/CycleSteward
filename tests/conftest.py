"""Shared test fixtures: paths to the charge-session CSV library."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def clean_fixture() -> Path:
    return FIXTURES_DIR / "synthetic-low-to-full.csv"
