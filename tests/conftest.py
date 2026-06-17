"""Shared test fixtures: paths to the charge-session CSV library.

Also installs lightweight Home Assistant + voluptuous stubs (see ha_stubs) at
collection time so the adapter modules that import HA framework symbols
(config_flow, time, services) load offline.  Modules that defer HA imports are
unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ha_stubs

ha_stubs.install()

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def clean_fixture() -> Path:
    return FIXTURES_DIR / "synthetic-low-to-full.csv"


@pytest.fixture
def inrush_fixture() -> Path:
    return FIXTURES_DIR / "synthetic-inrush-settling.csv"


@pytest.fixture
def mid_taper_cutoff_fixture() -> Path:
    return FIXTURES_DIR / "synthetic-mid-taper-cutoff.csv"
