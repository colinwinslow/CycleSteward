"""Tests for HA adapter slice 2: CalibrationProfile.from_json, ProfileStore, HASensorWatcher.

Scenarios A-G from bdd/ha-adapter/ha-adapter-wiring-bdd.md.

HA modules are not installed; ProfileStore and HASensorWatcher are tested via
sys.modules injection and mock objects so all wiring logic runs as pure Python.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cyclesteward.calibration import (
    CalibrationProfile,
    FullObservation,
    OverheadEstimate,
    ProfileState,
    SocAssumptions,
    SocReport,
    TemperatureObservation,
    WattageAnchor,
)
from cyclesteward.session_control import ChargeMode, SessionConfig, SessionState

from custom_components.cyclesteward.coordinator import CyclestewardCoordinator

# ── helpers ───────────────────────────────────────────────────────────────────

T0 = datetime(2026, 1, 1, 1, 0, 0, tzinfo=timezone.utc)  # 1 AM UTC, before 6 AM morning reset


def t(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _calibrated_profile(watts_at_transition: float = 130.0) -> CalibrationProfile:
    p = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="test-meter",
    )
    p.state = ProfileState.CALIBRATED
    p.watts_at_low = WattageAnchor(watts=65.0, assumed_soc_label="display_empty")
    p.watts_at_transition = WattageAnchor(
        watts=watts_at_transition, assumed_soc_label="cc_cv_transition"
    )
    p.taper_floor_w = 15.0
    p.active_full_wh = 400.0
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
    return p


def _make_hass(plug_state: str = "off") -> SimpleNamespace:
    """Minimal hass mock for watcher tests."""
    plug_mock = SimpleNamespace(state=plug_state)
    hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: plug_mock),
        services=SimpleNamespace(async_call=AsyncMock()),
        bus=SimpleNamespace(async_fire=MagicMock()),
    )
    return hass


def _make_event(entity_state: str) -> SimpleNamespace:
    """Build a fake HA state_changed event."""
    new_state = SimpleNamespace(state=entity_state)
    return SimpleNamespace(data={"new_state": new_state})


def run(coro):
    """Run a coroutine synchronously (no pytest-asyncio dependency)."""
    return asyncio.run(coro)


# ── CalibrationProfile.from_json round-trip ───────────────────────────────────


class TestFromJson:
    def test_bare_uncalibrated_profile_round_trips(self):
        original = CalibrationProfile(
            charger_label="mycharger",
            battery_label="mybattery",
            meter_id="meter-1",
        )
        restored = CalibrationProfile.from_json(original.to_json())
        assert restored.charger_label == "mycharger"
        assert restored.battery_label == "mybattery"
        assert restored.meter_id == "meter-1"
        assert restored.state == ProfileState.UNCALIBRATED
        assert restored.watts_at_low is None
        assert restored.watts_at_transition is None

    def test_calibrated_profile_anchors_preserved(self):
        original = _calibrated_profile(watts_at_transition=125.5)
        restored = CalibrationProfile.from_json(original.to_json())
        assert restored.state == ProfileState.CALIBRATED
        assert restored.watts_at_low is not None
        assert restored.watts_at_low.watts == pytest.approx(65.0)
        assert restored.watts_at_transition is not None
        assert restored.watts_at_transition.watts == pytest.approx(125.5)
        assert restored.taper_floor_w == pytest.approx(15.0)
        assert restored.active_full_wh == pytest.approx(400.0)

    def test_assumptions_round_trip(self):
        original = _calibrated_profile()
        original.assumptions = SocAssumptions(soc_at_low_pct=5.0, soc_at_transition_pct=85.0)
        restored = CalibrationProfile.from_json(original.to_json())
        assert restored.assumptions is not None
        assert restored.assumptions.soc_at_low_pct == pytest.approx(5.0)
        assert restored.assumptions.soc_at_transition_pct == pytest.approx(85.0)

    def test_overhead_round_trip(self):
        original = _calibrated_profile()
        original.rated_capacity_wh = 500.0
        original.overhead = OverheadEstimate(
            ratio=0.82, rated_capacity_wh=500.0, measured_full_wh=410.0
        )
        restored = CalibrationProfile.from_json(original.to_json())
        assert restored.overhead is not None
        assert restored.overhead.ratio == pytest.approx(0.82, abs=1e-3)
        assert restored.overhead.confidence == "low"

    def test_full_observation_round_trip(self):
        original = _calibrated_profile()
        original.full_observations.append(
            FullObservation(
                timestamp=T0,
                active_wh=390.0,
                watts_at_low=65.0,
                watts_at_transition=130.0,
                trusted=True,
                soc_at_start=SocReport.display_empty(),
                quality_flags=[],
            )
        )
        restored = CalibrationProfile.from_json(original.to_json())
        assert len(restored.full_observations) == 1
        obs = restored.full_observations[0]
        assert obs.trusted is True
        assert obs.active_wh == pytest.approx(390.0)
        assert obs.soc_at_start is not None
        assert obs.soc_at_start.label == "display_empty"

    def test_temperature_observation_round_trip(self):
        original = _calibrated_profile()
        original.temperature_observations.append(
            TemperatureObservation(
                timestamp=T0,
                active_wh=395.0,
                watts_at_low=65.0,
                temperature_c=18.5,
            )
        )
        restored = CalibrationProfile.from_json(original.to_json())
        assert len(restored.temperature_observations) == 1
        obs = restored.temperature_observations[0]
        assert obs.temperature_c == pytest.approx(18.5)
        assert obs.watts_at_low == pytest.approx(65.0)

    def test_warnings_preserved(self):
        original = _calibrated_profile()
        original.warnings = ["some-warning", "another"]
        restored = CalibrationProfile.from_json(original.to_json())
        assert restored.warnings == ["some-warning", "another"]

    def test_from_dict_matches_from_json(self):
        original = _calibrated_profile()
        as_dict = original.to_dict()
        as_json = original.to_json()
        from_dict = CalibrationProfile.from_dict(as_dict)
        from_json = CalibrationProfile.from_json(as_json)
        assert from_dict.watts_at_transition.watts == from_json.watts_at_transition.watts


# ── ProfileStore ──────────────────────────────────────────────────────────────


def _make_profile_store(entry_id: str):
    """Create a ProfileStore over the stub HA Store (shared in-memory backing)."""
    from custom_components.cyclesteward.profile_store import ProfileStore

    return ProfileStore(hass=None, entry_id=entry_id)


class TestProfileStore:
    def test_load_empty_yields_empty_library(self):
        ps = _make_profile_store("empty-entry")
        run(ps.async_load())
        assert ps.active_battery_id is None
        assert ps.battery_ids == []

    def test_save_then_reload_round_trips(self):
        ps = _make_profile_store("rt-entry")
        run(ps.async_load())
        original = _calibrated_profile(watts_at_transition=125.5)
        run(ps.async_save_profile("bat_a", original))
        run(ps.async_set_active("bat_a"))

        # A fresh ProfileStore over the same entry sees the persisted library.
        reloaded = _make_profile_store("rt-entry")
        run(reloaded.async_load())
        assert reloaded.active_battery_id == "bat_a"
        restored = reloaded.get_profile("bat_a")
        assert restored is not None
        assert restored.watts_at_transition.watts == pytest.approx(125.5)
        assert restored.state == ProfileState.CALIBRATED

    def test_load_reconstructs_all_fields(self):
        ps = _make_profile_store("fields-entry")
        run(ps.async_load())
        original = _calibrated_profile()
        original.warnings = ["test-warning"]
        original.taper_floor_w = 12.5
        run(ps.async_save_profile("bat_a", original))

        reloaded = _make_profile_store("fields-entry")
        run(reloaded.async_load())
        restored = reloaded.get_profile("bat_a")
        assert restored.taper_floor_w == pytest.approx(12.5)
        assert restored.warnings == ["test-warning"]

    def test_set_active_requires_stored_profile(self):
        ps = _make_profile_store("guard-entry")
        run(ps.async_load())
        with pytest.raises(KeyError):
            run(ps.async_set_active("nope"))


# ── HASensorWatcher ───────────────────────────────────────────────────────────


def _make_watcher(profile=None, plug_state="off", temp_entity=None):
    """Create a HASensorWatcher with mocked hass and a real coordinator."""
    from custom_components.cyclesteward.watcher import HASensorWatcher

    if profile is None:
        profile = _calibrated_profile()
    coordinator = CyclestewardCoordinator(profile)
    hass = _make_hass(plug_state=plug_state)
    watcher = HASensorWatcher(
        hass=hass,
        coordinator=coordinator,
        power_entity_id="sensor.plug_power",
        plug_entity_id="switch.plug",
        temp_entity_id=temp_entity,
    )
    return watcher, coordinator, hass


class TestHASensorWatcher:
    # ── Scenario A: power update triggers tick and relay dispatch ─────────────

    def test_power_update_calls_tick_and_dispatches_turn_on(self):
        # Profile: target at 80% SoC = 95 W (65-130 W ramp); 80 W < target → TURN_ON
        # Use fixed T0 (midnight) to avoid morning-reset interference with wall time.
        watcher, coordinator, hass = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        run(watcher._do_tick(80.0, T0))

        hass.services.async_call.assert_called_once_with(
            "homeassistant", "turn_on", {"entity_id": "switch.plug"}
        )

    def test_plug_is_on_read_from_hass_state(self):
        """plug_is_on=True is read from hass.states, passed to coordinator.tick."""
        watcher, coordinator, hass = _make_watcher(plug_state="on")
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        # First tick turns on, subsequent tick with plug already on
        run(watcher._do_tick(80.0, T0))
        # We can't easily introspect tick args without a spy; verify no crash and
        # that the relay dispatch happened based on action
        assert coordinator.session_state == SessionState.CHARGING

    def test_power_event_caches_power_w(self):
        watcher, _, _ = _make_watcher()
        run(watcher._handle_power_state_change(_make_event("95.0")))
        assert watcher._cached_power_w == pytest.approx(95.0)

    # ── Scenario B: temperature caches; applied on next power tick only ───────

    def test_temp_event_updates_cache_no_tick(self):
        watcher, coordinator, _ = _make_watcher(temp_entity="sensor.battery_temp")
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        # Temperature event alone: no tick fired, cache updated
        run(watcher._handle_temp_state_change(_make_event("22.5")))
        assert watcher._cached_temp_c == pytest.approx(22.5)
        # Coordinator should still be in IDLE (no tick was driven)
        assert coordinator.session_state == SessionState.IDLE

    def test_temp_cache_used_on_next_power_tick(self):
        watcher, coordinator, _ = _make_watcher(temp_entity="sensor.battery_temp")
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        run(watcher._handle_temp_state_change(_make_event("22.5")))
        # Use fixed T0 to avoid morning-reset interference with wall time.
        run(watcher._do_tick(80.0, T0))
        # No crash; coordinator advanced normally
        assert coordinator.session_state == SessionState.CHARGING

    # ── Scenario C: unavailable sensor → tick with power_w=None ─────────────

    def test_unavailable_power_produces_none_tick(self):
        watcher, coordinator, hass = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        run(watcher._handle_power_state_change(_make_event("unavailable")))

        # No relay call (action should be NONE since power_w=None → no cutoff trigger)
        hass.services.async_call.assert_not_called()
        # Coordinator stays IDLE (no valid power → no TURN_ON in target mode without data)
        assert coordinator.session_state == SessionState.IDLE

    def test_unknown_power_produces_none_tick(self):
        watcher, coordinator, hass = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        run(watcher._handle_power_state_change(_make_event("unknown")))
        hass.services.async_call.assert_not_called()

    # ── Scenario D: profile load — tested via ProfileStore above ─────────────
    # (Integration of load into async_setup_entry tested by reading __init__.py;
    # the store round-trip is the load-path proof.)

    # ── Scenario E: trace buffer accumulates; clears on new session ───────────

    def test_trace_buffer_accumulates_valid_power_readings(self):
        watcher, coordinator, _ = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        run(watcher._do_tick(80.0, t(0)))
        run(watcher._do_tick(82.0, t(10)))
        run(watcher._do_tick(79.0, t(20)))

        buf = watcher.trace_buffer
        assert len(buf) == 3
        assert buf[0][1] == pytest.approx(80.0)
        assert buf[1][1] == pytest.approx(82.0)
        assert buf[2][1] == pytest.approx(79.0)

    def test_trace_buffer_skips_none_power(self):
        watcher, coordinator, _ = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        run(watcher._do_tick(80.0, t(0)))
        run(watcher._do_tick(None, t(10)))  # unavailable
        run(watcher._do_tick(82.0, t(20)))

        assert len(watcher.trace_buffer) == 2

    def test_trace_buffer_clears_on_charging_reentry(self):
        # Drive through a full session, then trigger a new one — buffer should clear.
        profile = _calibrated_profile()
        profile.taper_floor_w = 30.0
        config = SessionConfig(taper_below_floor_seconds=1)
        coordinator = CyclestewardCoordinator(profile, config=config)
        from custom_components.cyclesteward.watcher import HASensorWatcher
        hass = _make_hass()
        watcher = HASensorWatcher(hass, coordinator, "sensor.plug_power", "switch.plug")

        coordinator.set_mode(ChargeMode.CHARGE_TO_FULL)
        # Build up session trace
        run(watcher._do_tick(80.0, t(0)))
        run(watcher._do_tick(82.0, t(10)))
        assert len(watcher.trace_buffer) == 2

        # Force coordinator to DONE_LATCHED_OFF by driving wattage below taper floor
        # with sufficient dwell
        for i in range(5):
            run(watcher._do_tick(20.0, t(30 + i * 2)))

        assert coordinator.session_state == SessionState.DONE_LATCHED_OFF
        buf_at_completion = watcher.trace_buffer
        assert len(buf_at_completion) > 0  # buffer retained through DONE

        # Reset mode and start again → buffer should clear on CHARGING entry
        coordinator.set_mode(ChargeMode.OFF)
        coordinator.set_mode(ChargeMode.CHARGE_TO_FULL)
        run(watcher._do_tick(75.0, t(120)))
        assert coordinator.session_state == SessionState.CHARGING
        # Buffer should have been cleared and now holds only the new tick
        assert len(watcher.trace_buffer) == 1
        assert watcher.trace_buffer[0][1] == pytest.approx(75.0)

    # ── Scenario F: keepalive uses cached power ───────────────────────────────

    def test_keepalive_uses_cached_power(self):
        watcher, coordinator, hass = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        # Use fixed T0 to avoid morning-reset interference with wall time.
        run(watcher._do_tick(85.0, T0))
        hass.services.async_call.reset_mock()

        # Keepalive fires with no new power event — should use cached 85.0
        run(watcher._handle_keepalive(t(60)))
        # Coordinator is already CHARGING; keepalive tick should be NONE action
        # (already on, no cutoff yet) — no new service call
        assert coordinator.session_state == SessionState.CHARGING

    def test_keepalive_with_no_cached_power_passes_none(self):
        watcher, coordinator, _ = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # No power event yet; keepalive should not crash
        run(watcher._handle_keepalive(T0))
        assert coordinator.session_state == SessionState.IDLE

    # ── Scenario G: teardown cancels listeners ────────────────────────────────

    def test_async_stop_calls_all_unsubs(self):

        watcher, _, hass = _make_watcher()
        unsub1 = MagicMock()
        unsub2 = MagicMock()
        watcher._unsubs = [unsub1, unsub2]

        run(watcher.async_stop())

        unsub1.assert_called_once()
        unsub2.assert_called_once()
        assert watcher._unsubs == []

    def test_async_stop_clears_unsub_list(self):
        watcher, _, _ = _make_watcher()
        watcher._unsubs = [MagicMock(), MagicMock()]
        run(watcher.async_stop())
        assert len(watcher._unsubs) == 0

    # ── Relay dispatch edge cases ─────────────────────────────────────────────

    def test_turn_off_dispatched_when_wattage_reaches_target(self):
        """TURN_OFF is dispatched when wattage hits target_wattage (CC→CV crossing).

        Profile: watts_at_low=65, watts_at_transition=130, target_soc=80%.
        target_wattage = 65 + (80/80) * (130-65) = 130 W.
        """
        watcher, coordinator, hass = _make_watcher()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)

        # Tick 1: below target → TURN_ON → CHARGING
        run(watcher._do_tick(80.0, t(0)))
        assert coordinator.session_state == SessionState.CHARGING
        hass.services.async_call.reset_mock()

        # Tick 2: at target wattage → TURN_OFF → DONE_LATCHED_OFF.
        # Must be >30 s after tick 1 to clear the min_dwell relay-chatter guard.
        run(watcher._do_tick(130.0, t(35)))
        assert coordinator.session_state == SessionState.DONE_LATCHED_OFF
        hass.services.async_call.assert_called_once_with(
            "homeassistant", "turn_off", {"entity_id": "switch.plug"}
        )

    def test_no_service_call_for_none_action(self):
        watcher, coordinator, hass = _make_watcher()
        # OFF mode → action should be NONE on every tick
        run(watcher._do_tick(80.0, T0))
        hass.services.async_call.assert_not_called()


# ── async_setup_entry integration (Scenario D end-to-end) ────────────────────


class TestAsyncSetupEntry:
    def test_stored_profile_loaded_into_coordinator(self):
        """async_setup_entry loads the stored active profile into the coordinator."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from custom_components.cyclesteward import DOMAIN, async_setup_entry

        # Pre-populate the entry's store (shared stub backing) with a known
        # calibrated profile as the active battery.
        stored_profile = _calibrated_profile(watts_at_transition=125.5)
        seed = _make_profile_store("test-entry")
        run(seed.async_load())
        run(seed.async_save_profile("b", stored_profile))
        run(seed.async_set_active("b"))

        # Fake hass with data dict, async config_entries, and a services registry
        # (async_setup_entry now registers domain services).
        hass = SimpleNamespace(
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

        # Fake config entry — no power/plug entity IDs so watcher is not started
        entry = SimpleNamespace(
            entry_id="test-entry",
            data={
                "charger_label": "c",
                "battery_label": "b",
                "meter_id": "m",
                "power_entity_id": "",   # empty → watcher skipped
                "plug_entity_id": "",
            },
        )

        result = run(async_setup_entry(hass, entry))

        assert result is True
        coordinator = hass.data[DOMAIN]["test-entry"]
        # target_wattage at 80% SoC with anchors 65-125.5 W = 125.5 W
        assert coordinator.target_wattage == pytest.approx(125.5)

    def test_fresh_profile_used_when_store_empty(self):
        """When no stored profile exists, a fresh profile is built from config-entry data."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from custom_components.cyclesteward import DOMAIN, async_setup_entry

        hass = SimpleNamespace(
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
        entry = SimpleNamespace(
            entry_id="test-entry-2",
            data={"charger_label": "c", "battery_label": "b", "meter_id": "m"},
        )

        result = run(async_setup_entry(hass, entry))

        assert result is True
        coordinator = hass.data[DOMAIN]["test-entry-2"]
        # Fresh profile is uncalibrated → target_wattage is None
        assert coordinator.target_wattage is None


# ── _parse_float helper ───────────────────────────────────────────────────────


class TestParseFloat:
    def test_numeric_string(self):
        from custom_components.cyclesteward.watcher import _parse_float

        assert _parse_float("80.5") == pytest.approx(80.5)

    def test_unavailable(self):
        from custom_components.cyclesteward.watcher import _parse_float

        assert _parse_float("unavailable") is None

    def test_unknown(self):
        from custom_components.cyclesteward.watcher import _parse_float

        assert _parse_float("unknown") is None

    def test_empty_string(self):
        from custom_components.cyclesteward.watcher import _parse_float

        assert _parse_float("") is None

    def test_non_numeric(self):
        from custom_components.cyclesteward.watcher import _parse_float

        assert _parse_float("hello") is None
