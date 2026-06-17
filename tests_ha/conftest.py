"""Real-Home-Assistant test harness (packet 4 — real-ha-smoke-test).

UNLIKE tests/conftest.py, this tree does NOT install ha_stubs.  These tests run
against genuine Home Assistant via pytest-homeassistant-custom-component, under a
Python 3.14 environment (.venv-ha) with homeassistant + the pytest-hacc plugin.

This directory is deliberately excluded from the default pytest run
(testpaths = ["tests"] in pyproject.toml); invoke it explicitly:

    .venv-ha/bin/python -m pytest tests_ha/ -v

See docs/specs/real-ha-smoke-test.md.
"""

from __future__ import annotations

import pytest

# Load the pytest-homeassistant-custom-component plugin (provides the `hass`
# fixture, MockConfigEntry, socket blocking, etc.).
pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA's real loader discover custom_components/cyclesteward in every test.

    pytest-hacc disables custom-integration loading by default; this autouse
    fixture re-enables it so async_get_integration / async_setup resolve the real
    integration from the repo-root custom_components directory.
    """
    yield
