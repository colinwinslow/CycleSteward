# Real-HA smoke test: load the integration in genuine Home Assistant — BDD

## Status

Draft. Paired with [docs/specs/real-ha-smoke-test.md](../../docs/specs/real-ha-smoke-test.md).

## Why this BDD exists

Every prior test runs against offline stubs (`tests/ha_stubs.py`). This pins down
that **real** Home Assistant can load the CycleSteward integration, run its
config flow, register its entities, and unload cleanly — the one surface no mock
can vouch for.

All scenarios run under `.venv-ha` (Python 3.14, `homeassistant==2026.6.3`,
`pytest-homeassistant-custom-component==0.13.339`) via
`.venv-ha/bin/python -m pytest tests_ha/ -v`.

## Scenarios

### Scenario A — manifest/loader validation: real HA accepts the integration

**Given** a real `hass` instance with custom integrations enabled
**When** HA's real loader resolves `custom_components/cyclesteward` (via
`async_get_integration`)
**Then** it loads without raising, the manifest reports `domain == "cyclesteward"`
and `config_flow is True`, and the declared platforms are importable —
demonstrating the manifest passes HA's own validation (the local stand-in for
`hassfest`, which runs canonically in CI).

### Scenario B — happy path (anchor): config flow creates an entry

**Given** a real `hass` instance with the integration available
**When** the user-initiated config flow runs to completion with valid
`power_entity_id` + `plug_entity_id` (and defaults for the optional fields)
**Then** the flow result is `CREATE_ENTRY`, a `ConfigEntry` for domain
`cyclesteward` exists in `hass.config_entries`, and its `data` round-trips the
submitted entity IDs.

### Scenario C — entities register across all platforms

**Given** a config entry set up against real HA (`async_setup_entry` succeeded)
**When** setup completes and the entity registry / `hass.states` are inspected
**Then** the entry reaches state `LOADED`, and entities materialize for each
declared platform — the `charge_mode` select, the `session_state` / `soc_estimate`
/ `fault` sensors, the `manual_override` switch, the `acknowledge_fault` button,
and the `target_finish_time` / `morning_reset_time` time entities (per ADR-0011).

### Scenario D — clean unload: tearing down the entry releases everything

**Given** a loaded config entry
**When** `hass.config_entries.async_unload(entry_id)` runs
**Then** it returns `True`, the entry state becomes `NOT_LOADED`, the watcher is
stopped, and registered services are removed on the last unload — no exceptions
during teardown.

## Evidence

The implementing slice produces `bdd/ha-adapter/real-ha-smoke-test-evidence.md`
containing raw `pytest -v` output (not "✓ passed" summaries) for scenarios A–D
run against real HA `2026.6.3`, plus the HA version banner and a note recording
the offline suite still green under `.venv`. The `.github/workflows/ci.yml`
contents (hassfest action + `tests_ha` job) are quoted as the CI half of the
proof.
