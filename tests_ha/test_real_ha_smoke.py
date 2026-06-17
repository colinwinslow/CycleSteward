"""Real-HA smoke test (packet 4): the integration loads in genuine Home Assistant.

Proves what the offline stub suite cannot: that real HA's loader accepts the
manifest, the config flow creates an entry, every declared platform registers
entities, and the entry unloads cleanly.  See:
  - docs/specs/real-ha-smoke-test.md
  - bdd/ha-adapter/real-ha-smoke-test-bdd.md  (scenarios A–D)

Run under .venv-ha (Python 3.14 + Home Assistant):
    .venv-ha/bin/python -m pytest tests_ha/ -v
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cyclesteward.const import DOMAIN, PLATFORMS

# Minimal valid config-entry data: the two required operational entity IDs plus
# the profile-identity defaults the flow/setup expect.
ENTRY_DATA = {
    "charger_label": "charger",
    "battery_label": "battery",
    "meter_id": "meter",
    "power_entity_id": "sensor.test_power",
    "plug_entity_id": "switch.test_plug",
}

EXPECTED_SERVICES = ("set_mode", "manual_override", "acknowledge_fault")


def _seed_source_states(hass: HomeAssistant) -> None:
    """Provide the watcher's source entities so a tick has something to read."""
    hass.states.async_set("sensor.test_power", "0.0")
    hass.states.async_set("switch.test_plug", "off")


# ── Scenario A — manifest/loader validation ──────────────────────────────────


async def test_a_real_loader_validates_manifest(hass: HomeAssistant) -> None:
    """Real HA resolves the integration and its manifest passes loader checks."""
    integration = await async_get_integration(hass, DOMAIN)

    assert integration.domain == "cyclesteward"
    assert integration.config_flow is True
    # Every declared platform module must import under real HA (the local
    # stand-in for hassfest, which runs canonically in CI).
    for platform in PLATFORMS:
        component = await integration.async_get_platform(platform)
        assert hasattr(component, "async_setup_entry")


# ── Scenario B — happy path (anchor): config flow creates an entry ────────────


async def test_b_config_flow_creates_entry(hass: HomeAssistant) -> None:
    """A user-initiated config flow completes with a CREATE_ENTRY result."""
    _seed_source_states(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(ENTRY_DATA)
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["power_entity_id"] == "sensor.test_power"
    assert result["data"]["plug_entity_id"] == "switch.test_plug"

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].data["power_entity_id"] == "sensor.test_power"


# ── Scenario C — entities register across all platforms ──────────────────────


async def test_c_entities_register_across_platforms(hass: HomeAssistant) -> None:
    """Setting up an entry materializes entities for every declared platform."""
    _seed_source_states(hass)

    entry = MockConfigEntry(domain=DOMAIN, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED

    # Each declared platform must produce at least one entity in the registry.
    ent_reg = er.async_get(hass)
    registered = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    platforms_seen = {e.domain for e in registered}
    assert set(PLATFORMS) <= platforms_seen, (
        f"missing platforms: {set(PLATFORMS) - platforms_seen}"
    )

    # The ADR-0011 primary surface is present in live state.
    state_domains = {eid.split(".")[0] for eid in hass.states.async_entity_ids()}
    assert {"select", "sensor", "switch", "button", "time"} <= state_domains

    # Services registered as part of setup.
    for service in EXPECTED_SERVICES:
        assert hass.services.has_service(DOMAIN, service)


# ── Scenario D — clean unload ────────────────────────────────────────────────


async def test_d_clean_unload_releases_everything(hass: HomeAssistant) -> None:
    """Unloading the (only) entry returns True and removes services."""
    _seed_source_states(hass)

    entry = MockConfigEntry(domain=DOMAIN, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    # The watcher is registered under "<entry_id>.watcher" during setup; its
    # presence here lets us prove it is released on unload (BDD "Then": watcher
    # stopped). __init__.async_unload_entry pops this key and calls async_stop().
    watcher_key = f"{entry.entry_id}.watcher"
    assert watcher_key in hass.data[DOMAIN]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    # Watcher released (popped + async_stop ran) and coordinator dropped.
    assert watcher_key not in hass.data[DOMAIN]
    assert entry.entry_id not in hass.data[DOMAIN]
    # Last entry gone → domain-level services removed.
    for service in EXPECTED_SERVICES:
        assert not hass.services.has_service(DOMAIN, service)
