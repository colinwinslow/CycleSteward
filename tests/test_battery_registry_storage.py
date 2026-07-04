"""Tests for ADR-0014 slice 1: battery registry + profile-library storage.

Spec: docs/specs/battery-registry-storage.md
BDD:  bdd/ha-adapter/battery-registry-storage-bdd.md (scenarios A-E)

HA is not installed; the modules under test defer HA imports and run against
the session-wide stubs (tests/ha_stubs.py), whose Store now mirrors the real
version-aware migration contract and shares an in-memory backing across
instances (reset per test by the conftest autouse fixture).
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import ha_stubs
from cyclesteward.calibration import (
    CalibrationProfile,
    FullObservation,
    ProfileState,
    SocAssumptions,
    TemperatureObservation,
    WattageAnchor,
)

from custom_components.cyclesteward.battery_registry import (
    BatteryIdentity,
    BatteryRegistry,
    derive_battery_id,
)
from custom_components.cyclesteward.profile_store import (
    STORAGE_VERSION,
    ProfileStore,
    migrate_v1_payload,
)


def run(coro):
    """Run a coroutine synchronously (no pytest-asyncio dependency)."""
    return asyncio.run(coro)


def _calibrated_v1_payload(battery_label: str = "Swoop battery") -> dict:
    """A realistic v1 store payload: calibrated anchors + observations."""
    p = CalibrationProfile(
        charger_label="Shimano EC-E6000",
        battery_label=battery_label,
        meter_id="aqara-plug-1",
        rated_capacity_wh=504.0,
    )
    p.state = ProfileState.CALIBRATED
    p.idle_power_w = 2.1
    p.watts_at_low = WattageAnchor(watts=69.7, assumed_soc_label="display-empty")
    p.watts_at_transition = WattageAnchor(watts=127.4, assumed_soc_label="cc-cv-peak")
    p.taper_floor_w = 11.3
    p.active_full_wh = 412.6
    p.assumptions = SocAssumptions(soc_at_low_pct=5.0, soc_at_transition_pct=95.0)
    p.reference_temp_c = 19.5
    ts = datetime(2026, 6, 30, 21, 40, tzinfo=timezone.utc)
    p.full_observations = [
        FullObservation(
            timestamp=ts,
            active_wh=412.6,
            watts_at_low=69.7,
            watts_at_transition=127.4,
            trusted=True,
            elapsed_seconds=14520.0,
        )
    ]
    p.temperature_observations = [
        TemperatureObservation(
            timestamp=ts, active_wh=412.6, watts_at_low=69.7, temperature_c=19.5
        )
    ]
    p.warnings = ["seeded-for-migration-test"]
    return p.to_dict()


def _make_hass():
    """Fake hass sufficient for async_setup_entry without watcher start."""
    return SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(return_value=None)
        ),
        services=SimpleNamespace(
            has_service=MagicMock(return_value=False),
            async_register=MagicMock(),
            async_remove=MagicMock(),
        ),
    )


def _entry(entry_id: str, data: dict) -> SimpleNamespace:
    return SimpleNamespace(entry_id=entry_id, data=data)


def _setup(hass, entry_id: str, data: dict):
    from custom_components.cyclesteward import async_setup_entry

    entry = _entry(entry_id, data)
    assert run(async_setup_entry(hass, entry)) is True
    return entry


_BARE_ENTRY_DATA = {
    "charger_label": "Shimano EC-E6000",
    "battery_label": "Swoop battery",
    "meter_id": "aqara-plug-1",
    "rated_capacity_wh": 504.0,
    "target_soc_dots": 4,
    # no power/plug entity ids → watcher not started (not under test here)
}


# ── migrate_v1_payload (pure) ────────────────────────────────────────────────


class TestMigrateV1Payload:
    def test_wraps_under_slug_of_battery_label(self):
        v1 = _calibrated_v1_payload()
        v2 = migrate_v1_payload(v1)
        assert v2["active_battery_id"] == "swoop_battery"
        assert list(v2["profiles"]) == ["swoop_battery"]

    def test_inner_profile_dict_is_untouched(self):
        v1 = _calibrated_v1_payload()
        reference = copy.deepcopy(v1)
        v2 = migrate_v1_payload(v1)
        # Not merely equal: the migration must not rewrite any nested field.
        assert v2["profiles"]["swoop_battery"] == reference
        assert v2["profiles"]["swoop_battery"] is v1

    def test_deterministic(self):
        v1 = _calibrated_v1_payload()
        assert migrate_v1_payload(v1) == migrate_v1_payload(copy.deepcopy(v1))


# ── BatteryRegistry ──────────────────────────────────────────────────────────


class TestBatteryRegistry:
    def _registry(self) -> BatteryRegistry:
        registry = BatteryRegistry(hass=None)
        run(registry.async_load())
        return registry

    def _identity(self, label="Swoop battery", **kwargs) -> BatteryIdentity:
        return BatteryIdentity(
            battery_id=derive_battery_id(label),
            charger_label="Shimano EC-E6000",
            battery_label=label,
            **kwargs,
        )

    def test_load_empty(self):
        registry = self._registry()
        assert registry.identities == {}

    def test_register_and_round_trip(self):
        registry = self._registry()
        final_id = run(
            registry.async_register(self._identity(rated_capacity_wh=504.0))
        )
        assert final_id == "swoop_battery"

        # A fresh registry instance sees the persisted identity (shared backing).
        reloaded = self._registry()
        identity = reloaded.get("swoop_battery")
        assert identity is not None
        assert identity.battery_label == "Swoop battery"
        assert identity.rated_capacity_wh == pytest.approx(504.0)

    def test_register_collision_appends_dash_suffix(self):
        registry = self._registry()
        run(registry.async_register(self._identity()))
        second = run(registry.async_register(self._identity()))
        third = run(registry.async_register(self._identity()))
        # D2: dash suffix cannot collide with a natural slug (slugify never
        # emits dashes).
        assert second == "swoop_battery-2"
        assert third == "swoop_battery-3"
        assert registry.get("swoop_battery-2").battery_id == "swoop_battery-2"

    def test_ensure_is_idempotent_and_existing_wins(self):
        registry = self._registry()
        run(registry.async_register(self._identity(rated_capacity_wh=504.0)))
        returned = run(
            registry.async_ensure(self._identity(rated_capacity_wh=999.0))
        )
        assert returned == "swoop_battery"
        # The pre-existing identity's facts are not overwritten.
        assert registry.get("swoop_battery").rated_capacity_wh == pytest.approx(504.0)


# ── ProfileStore v2 + migration ──────────────────────────────────────────────


class TestProfileStoreMigration:
    def test_scenario_b_v1_payload_wrapped_never_discarded(self):
        v1 = _calibrated_v1_payload()
        reference = copy.deepcopy(v1)
        ha_stubs.seed_storage("cyclesteward.entry-m1", 1, v1)

        store = ProfileStore(hass=None, entry_id="entry-m1")
        run(store.async_load())

        assert store.active_battery_id == "swoop_battery"
        assert store.battery_ids == ["swoop_battery"]
        profile = store.get_profile("swoop_battery")
        assert profile.state == ProfileState.CALIBRATED
        assert profile.watts_at_transition.watts == pytest.approx(127.4)
        assert len(profile.full_observations) == 1
        assert len(profile.temperature_observations) == 1
        # Round-tripping the loaded profile reproduces the v1 dict exactly —
        # nothing was dropped or renormalized on the way through migration.
        assert profile.to_dict() == reference

    def test_scenario_e_v2_payload_not_rewrapped(self):
        v1 = _calibrated_v1_payload()
        v2 = migrate_v1_payload(v1)
        reference = copy.deepcopy(v2)
        ha_stubs.seed_storage("cyclesteward.entry-e", STORAGE_VERSION, v2)

        store = ProfileStore(hass=None, entry_id="entry-e")
        run(store.async_load())
        assert store.active_battery_id == "swoop_battery"
        assert store.battery_ids == ["swoop_battery"]
        # Raw persisted payload untouched: no double nesting.
        assert ha_stubs.storage_payload("cyclesteward.entry-e") == reference

    def test_scenario_d_library_round_trip(self):
        store = ProfileStore(hass=None, entry_id="entry-d")
        run(store.async_load())
        first = CalibrationProfile.from_dict(_calibrated_v1_payload())
        second = CalibrationProfile(
            charger_label="Bosch 4A", battery_label="Cargo battery", meter_id="m2"
        )
        run(store.async_save_profile("swoop_battery", first))
        run(store.async_save_profile("cargo_battery", second))
        run(store.async_set_active("cargo_battery"))

        reloaded = ProfileStore(hass=None, entry_id="entry-d")
        run(reloaded.async_load())
        assert reloaded.active_battery_id == "cargo_battery"
        assert reloaded.battery_ids == ["cargo_battery", "swoop_battery"]
        assert reloaded.get_profile("swoop_battery").state == ProfileState.CALIBRATED
        assert reloaded.get_profile("cargo_battery").state == ProfileState.UNCALIBRATED


# ── async_setup_entry wiring (scenarios A, B-reconciliation, C) ─────────────


class TestSetupWiring:
    def test_scenario_a_fresh_install(self):
        from custom_components.cyclesteward import DOMAIN

        hass = _make_hass()
        _setup(hass, "entry-a", dict(_BARE_ENTRY_DATA))

        # v2 library persisted with the entry's battery active.
        payload = ha_stubs.storage_payload("cyclesteward.entry-a")
        assert payload["active_battery_id"] == "swoop_battery"
        assert list(payload["profiles"]) == ["swoop_battery"]

        # Registry holds the matching identity, coarse dots included.
        registry = hass.data[DOMAIN]["registry"]
        identity = registry.get("swoop_battery")
        assert identity.charger_label == "Shimano EC-E6000"
        assert identity.rated_capacity_wh == pytest.approx(504.0)
        assert identity.target_soc_dots == 4

        # Coordinator runs against that profile, exactly as a single-profile
        # install does today (fresh → uncalibrated → no target wattage).
        coordinator = hass.data[DOMAIN]["entry-a"]
        assert coordinator.target_wattage is None

    def test_scenario_b_reconciliation_builds_identity_from_stored_labels(self):
        from custom_components.cyclesteward import DOMAIN

        v1 = _calibrated_v1_payload()
        ha_stubs.seed_storage("cyclesteward.entry-b", 1, v1)
        hass = _make_hass()
        _setup(hass, "entry-b", dict(_BARE_ENTRY_DATA))

        registry = hass.data[DOMAIN]["registry"]
        identity = registry.get("swoop_battery")
        assert identity is not None
        assert identity.battery_label == "Swoop battery"
        assert identity.rated_capacity_wh == pytest.approx(504.0)

        # The migrated calibrated profile drives the coordinator.
        coordinator = hass.data[DOMAIN]["entry-b"]
        assert coordinator.target_wattage is not None

    def test_dangling_active_id_falls_back_deterministically(self):
        """A payload whose active_battery_id names a missing profile must not
        hand the coordinator None (arch-review recommendation)."""
        from custom_components.cyclesteward import DOMAIN

        v2 = migrate_v1_payload(_calibrated_v1_payload())
        v2["active_battery_id"] = "ghost_battery"
        ha_stubs.seed_storage("cyclesteward.entry-dangle", STORAGE_VERSION, v2)

        hass = _make_hass()
        _setup(hass, "entry-dangle", dict(_BARE_ENTRY_DATA))

        payload = ha_stubs.storage_payload("cyclesteward.entry-dangle")
        assert payload["active_battery_id"] == "swoop_battery"
        # The calibrated profile (not None, not a fresh one) drives the
        # coordinator.
        coordinator = hass.data[DOMAIN]["entry-dangle"]
        assert coordinator.target_wattage is not None

    def test_scenario_c_two_meters_one_identity_two_profiles(self):
        from custom_components.cyclesteward import DOMAIN

        # Meter 1: calibrated history for the Swoop battery.
        v1 = _calibrated_v1_payload()
        ha_stubs.seed_storage("cyclesteward.entry-m1", 1, v1)
        hass = _make_hass()
        _setup(hass, "entry-m1", dict(_BARE_ENTRY_DATA))
        # Persist the migrated library so the on-disk payload is inspectable.
        store_m1 = ProfileStore(hass=None, entry_id="entry-m1")
        run(store_m1.async_load())
        run(
            store_m1.async_save_profile(
                "swoop_battery", store_m1.get_profile("swoop_battery")
            )
        )
        m1_before = copy.deepcopy(
            ha_stubs.storage_payload("cyclesteward.entry-m1")
        )

        # Meter 2: same battery label, fresh entry.
        m2_data = dict(_BARE_ENTRY_DATA, meter_id="aqara-plug-2")
        _setup(hass, "entry-m2", m2_data)

        registry = hass.data[DOMAIN]["registry"]
        # One identity — no swoop_battery-2 fork.
        assert set(registry.identities) == {"swoop_battery"}

        # M2 stores its own fresh, uncalibrated profile under the shared id.
        m2_payload = ha_stubs.storage_payload("cyclesteward.entry-m2")
        assert m2_payload["active_battery_id"] == "swoop_battery"
        m2_profile = m2_payload["profiles"]["swoop_battery"]
        assert m2_profile["state"] == "uncalibrated"
        assert m2_profile["watts_at_low"] is None

        # M1's calibrated anchors are untouched by M2's setup.
        assert (
            ha_stubs.storage_payload("cyclesteward.entry-m1") == m1_before
        )
        coordinator_m2 = hass.data[DOMAIN]["entry-m2"]
        assert coordinator_m2.target_wattage is None


# ── Anchor trace generation (spec "Anchor artifact") ─────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]
BDD_DIR = REPO_ROOT / "bdd" / "ha-adapter"


def test_generate_battery_registry_storage_trace():
    """Produce + verify the anchor trace JSON.

    Three legs (raw persisted payloads, not summaries):
      1. migration — a real v1 payload and migrate_v1_payload's output for it.
      2. reconciliation — the registry payload after setup over that store.
      3. two_meter — registry + both entries' payloads after a second entry
         stores a fresh profile under the same battery_id.
    """
    # ── Leg 1: pure migration ────────────────────────────────────────────────
    v1 = _calibrated_v1_payload()
    v1_ref = copy.deepcopy(v1)
    v2 = migrate_v1_payload(v1)
    migration_leg = {
        "v1_payload": v1_ref,
        "v2_payload": copy.deepcopy(v2),
        "inner_profile_byte_identical_to_v1": (
            v2["profiles"]["swoop_battery"] == v1_ref
        ),
    }

    # ── Leg 2: reconciliation over a seeded v1 store ─────────────────────────
    ha_stubs.reset_storage()
    ha_stubs.seed_storage("cyclesteward.entry-m1", 1, _calibrated_v1_payload())
    hass = _make_hass()
    _setup(hass, "entry-m1", dict(_BARE_ENTRY_DATA))
    reconciliation_leg = {
        "registry_payload": copy.deepcopy(
            ha_stubs.storage_payload("cyclesteward.registry")
        ),
    }

    # ── Leg 3: second meter, same battery ────────────────────────────────────
    store_m1 = ProfileStore(hass=None, entry_id="entry-m1")
    run(store_m1.async_load())
    run(
        store_m1.async_save_profile(
            "swoop_battery", store_m1.get_profile("swoop_battery")
        )
    )
    m1_before = copy.deepcopy(ha_stubs.storage_payload("cyclesteward.entry-m1"))

    _setup(hass, "entry-m2", dict(_BARE_ENTRY_DATA, meter_id="aqara-plug-2"))
    m1_after = ha_stubs.storage_payload("cyclesteward.entry-m1")
    registry_payload = ha_stubs.storage_payload("cyclesteward.registry")
    two_meter_leg = {
        "registry_payload": copy.deepcopy(registry_payload),
        "entry_m1_payload": copy.deepcopy(m1_after),
        "entry_m2_payload": copy.deepcopy(
            ha_stubs.storage_payload("cyclesteward.entry-m2")
        ),
        "m1_payload_unchanged_by_m2_setup": m1_after == m1_before,
        "registry_identity_count": len(registry_payload["identities"]),
    }

    trace = {
        "generated": "2026-07-04",
        "spec": "docs/specs/battery-registry-storage.md",
        "adr": "docs/decisions/0014-multi-battery-profile-registry.md",
        "legs": {
            "migration": migration_leg,
            "reconciliation": reconciliation_leg,
            "two_meter": two_meter_leg,
        },
    }

    out = BDD_DIR / "battery-registry-storage-trace.json"
    out.write_text(json.dumps(trace, indent=2) + "\n")

    # ── Verify the artifact on disk ──────────────────────────────────────────
    data = json.loads(out.read_text())

    migration = data["legs"]["migration"]
    assert migration["inner_profile_byte_identical_to_v1"] is True
    assert migration["v2_payload"]["active_battery_id"] == "swoop_battery"
    wrapped = migration["v2_payload"]["profiles"]["swoop_battery"]
    assert wrapped == migration["v1_payload"]
    assert wrapped["watts_at_transition"]["watts"] == pytest.approx(127.4)
    assert wrapped["full_observations"][0]["elapsed_seconds"] == pytest.approx(
        14520.0
    )

    identities = data["legs"]["reconciliation"]["registry_payload"]["identities"]
    assert list(identities) == ["swoop_battery"]
    assert identities["swoop_battery"]["battery_label"] == "Swoop battery"
    assert identities["swoop_battery"]["target_soc_dots"] == 4

    two_meter = data["legs"]["two_meter"]
    assert two_meter["registry_identity_count"] == 1
    assert two_meter["m1_payload_unchanged_by_m2_setup"] is True
    m2_profile = two_meter["entry_m2_payload"]["profiles"]["swoop_battery"]
    assert m2_profile["state"] == "uncalibrated"
    assert m2_profile["watts_at_low"] is None
    m1_profile = two_meter["entry_m1_payload"]["profiles"]["swoop_battery"]
    assert m1_profile["watts_at_transition"]["watts"] == pytest.approx(127.4)
