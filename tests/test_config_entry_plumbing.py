"""Tests for the config-entry-plumbing slice (review finding F1).

Scenarios A-G from bdd/ha-adapter/config-entry-plumbing-bdd.md.

Home Assistant and voluptuous are stubbed session-wide by conftest (see
tests/ha_stubs), so the real config_flow / time / services / __init__ modules
import and run as pure Python.  These tests exercise the actual wiring, not
mocks of it: a real HASensorWatcher and CyclestewardCoordinator are driven
through async_setup_entry against a mock hass.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, time, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import ha_stubs

ha_stubs.install()

from homeassistant.util import dt as dt_util  # noqa: E402  (stub)

from cyclesteward.calibration import (  # noqa: E402
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    WattageAnchor,
)
from cyclesteward.guardrails import GuardrailsConfig  # noqa: E402
from cyclesteward.session_control import (  # noqa: E402
    ChargeMode,
    SessionState,
)

from custom_components.cyclesteward import DOMAIN, async_setup_entry  # noqa: E402
from custom_components.cyclesteward import config_flow  # noqa: E402
from custom_components.cyclesteward.coordinator import (  # noqa: E402
    CyclestewardCoordinator,
)
from custom_components.cyclesteward.schedule import next_occurrence  # noqa: E402
from custom_components.cyclesteward.time import (  # noqa: E402
    MorningResetTimeEntity,
    TargetFinishTimeEntity,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ANCHOR_PATH = REPO_ROOT / "bdd" / "ha-adapter" / "config-entry-plumbing-trace.json"
SERVICES_YAML = (
    REPO_ROOT / "custom_components" / "cyclesteward" / "services.yaml"
)


def run(coro):
    return asyncio.run(coro)


# ── fixtures / helpers ────────────────────────────────────────────────────────


def _calibrated_profile() -> CalibrationProfile:
    p = CalibrationProfile(
        charger_label="c", battery_label="b", meter_id="m"
    )
    p.state = ProfileState.CALIBRATED
    p.watts_at_low = WattageAnchor(watts=65.0, assumed_soc_label="display_empty")
    p.watts_at_transition = WattageAnchor(
        watts=130.0, assumed_soc_label="cc_cv_transition"
    )
    p.taper_floor_w = 15.0
    p.active_full_wh = 400.0
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
    return p


class _FakeServices:
    """Records registered service handlers and can invoke them."""

    def __init__(self) -> None:
        self.handlers: dict = {}

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self.handlers

    def async_register(self, domain, service, handler, schema=None) -> None:
        self.handlers[(domain, service)] = handler

    def async_remove(self, domain, service) -> None:
        self.handlers.pop((domain, service), None)

    async def async_call(self, domain, service, data) -> None:
        await self.handlers[(domain, service)](SimpleNamespace(data=data))


def _make_hass(plug_state: str = "off") -> SimpleNamespace:
    plug = SimpleNamespace(state=plug_state)
    return SimpleNamespace(
        data={},
        config_entries=SimpleNamespace(
            async_forward_entry_setups=AsyncMock(return_value=None),
            async_unload_platforms=AsyncMock(return_value=True),
        ),
        services=_FakeServices(),
        states=SimpleNamespace(get=lambda entity_id: plug),
        bus=SimpleNamespace(async_fire=MagicMock()),
    )


def _entry(entry_id: str, data: dict) -> SimpleNamespace:
    return SimpleNamespace(entry_id=entry_id, data=data)


def _set_now(dt: datetime) -> None:
    dt_util.set_now(dt)


# ══ Scenario A — config flow collects entity IDs; entry data round-trips ═══════


class TestScenarioA:
    def test_schema_collects_entity_ids(self):
        import voluptuous as vol

        schema = config_flow.STEP_USER_DATA_SCHEMA.schema
        required = {
            str(k) for k in schema if isinstance(k, vol.Required)
        }
        optional = {
            str(k) for k in schema if isinstance(k, vol.Optional)
        }
        assert "power_entity_id" in required
        assert "plug_entity_id" in required
        assert "temp_entity_id" in optional
        assert "target_soc_dots" in optional
        assert "margin_s" in optional

    def test_entry_data_round_trips(self):
        flow = config_flow.CyclestewardConfigFlow()
        user_input = {
            "charger_label": "shimano",
            "battery_label": "btr-e8035",
            "meter_id": "aqara-1",
            "power_entity_id": "sensor.bike_plug_power",
            "plug_entity_id": "switch.bike_plug",
            "temp_entity_id": "sensor.garage_temp",
            "target_soc_dots": 4,
            "margin_s": 1200,
        }
        result = run(flow.async_step_user(user_input))
        assert result["type"] == "create_entry"
        assert result["data"]["power_entity_id"] == "sensor.bike_plug_power"
        assert result["data"]["plug_entity_id"] == "switch.bike_plug"
        assert result["data"] == user_input

    def test_no_input_shows_form_with_schema(self):
        flow = config_flow.CyclestewardConfigFlow()
        result = run(flow.async_step_user(None))
        assert result["type"] == "form"
        assert result["data_schema"] is config_flow.STEP_USER_DATA_SCHEMA


# ══ Scenario B — watcher starts from a real entry (anchor artifact) ════════════


class TestScenarioB:
    def _run_anchor_setup(self):
        anchor = json.loads(ANCHOR_PATH.read_text())
        _set_now(datetime.fromisoformat(anchor["now"]))
        data = dict(anchor["entry"]["data"])
        # Schedule times arrive as datetime.time at runtime (HA time entities);
        # the fixture stores them as ISO strings.
        data["target_finish_time"] = time.fromisoformat(data["target_finish_time"])
        data["morning_reset_time"] = time.fromisoformat(data["morning_reset_time"])
        hass = _make_hass()
        entry = _entry(anchor["entry"]["entry_id"], data)
        result = run(async_setup_entry(hass, entry))
        return anchor, hass, entry, result

    def test_watcher_started_with_margin_and_next_occurrence(self):
        anchor, hass, entry, result = self._run_anchor_setup()
        assert result is True

        watcher = hass.data[DOMAIN][f"{entry.entry_id}.watcher"]
        # async_start registered exactly power + temp + keepalive listeners.
        assert len(watcher._unsubs) == anchor["expected"]["listeners_registered"]
        # margin_s threaded from the entry.
        assert watcher._margin_s == pytest.approx(anchor["expected"]["margin_s"])
        # target finish became the tz-aware next occurrence (07:30 already past
        # 08:00 now → tomorrow), and the pessimistic start time was computed.
        expected_finish = datetime.fromisoformat(
            anchor["expected"]["target_finish_next_occurrence"]
        )
        expected_start = datetime.fromisoformat(
            anchor["expected"]["computed_start_time"]
        )
        assert watcher._target_finish_time == expected_finish
        assert watcher._target_finish_time.tzinfo is not None
        assert watcher.computed_start_time == expected_start
        assert watcher.computed_start_time < expected_finish

    def test_morning_reset_round_tripped_into_config(self):
        anchor, hass, entry, result = self._run_anchor_setup()
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator.morning_reset_time == time.fromisoformat(
            anchor["expected"]["morning_reset_time"]
        )

    def test_no_watcher_when_entity_ids_absent(self):
        hass = _make_hass()
        entry = _entry("bare", {"charger_label": "c", "battery_label": "b",
                                "meter_id": "m"})
        result = run(async_setup_entry(hass, entry))
        assert result is True
        assert f"{entry.entry_id}.watcher" not in hass.data[DOMAIN]


# ══ Scenario C — target-finish time drives the schedule (next-occurrence) ══════


class TestScenarioC:
    def _started_watcher(self, hass, coordinator, entry_id):
        from custom_components.cyclesteward.watcher import HASensorWatcher

        watcher = HASensorWatcher(
            hass, coordinator, "sensor.p", "switch.s"
        )
        hass.data.setdefault(DOMAIN, {})[f"{entry_id}.watcher"] = watcher
        return watcher

    def test_set_value_pushes_next_occurrence_to_watcher(self):
        _set_now(datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc))
        hass = _make_hass()
        coordinator = CyclestewardCoordinator(_calibrated_profile())
        hass.data.setdefault(DOMAIN, {})["e1"] = coordinator
        watcher = self._started_watcher(hass, coordinator, "e1")

        entity = TargetFinishTimeEntity(hass, coordinator, _entry("e1", {}))
        # 09:30 is still ahead of 08:00 now → today.
        run(entity.async_set_value(time(9, 30)))

        assert watcher._target_finish_time == datetime(
            2026, 6, 16, 9, 30, tzinfo=timezone.utc
        )
        assert watcher.computed_start_time is not None

    def test_past_time_of_day_rolls_to_tomorrow(self):
        _set_now(datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc))
        hass = _make_hass()
        coordinator = CyclestewardCoordinator(_calibrated_profile())
        hass.data.setdefault(DOMAIN, {})["e1"] = coordinator
        watcher = self._started_watcher(hass, coordinator, "e1")

        entity = TargetFinishTimeEntity(hass, coordinator, _entry("e1", {}))
        run(entity.async_set_value(time(6, 0)))  # 06:00 already past → tomorrow

        assert watcher._target_finish_time == datetime(
            2026, 6, 17, 6, 0, tzinfo=timezone.utc
        )

    def test_no_watcher_is_noop_beyond_storing_value(self):
        _set_now(datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc))
        hass = _make_hass()
        coordinator = CyclestewardCoordinator(_calibrated_profile())
        hass.data.setdefault(DOMAIN, {})["e1"] = coordinator
        # No watcher registered.
        entity = TargetFinishTimeEntity(hass, coordinator, _entry("e1", {}))
        run(entity.async_set_value(time(9, 30)))  # must not raise
        assert entity.native_value == time(9, 30)


# ══ Scenario D — morning-reset time round-trips into SessionConfig ═════════════


class TestScenarioD:
    def test_set_value_round_trips_into_config(self):
        coordinator = CyclestewardCoordinator(_calibrated_profile())
        hass = _make_hass()
        hass.data.setdefault(DOMAIN, {})["e1"] = coordinator
        entity = MorningResetTimeEntity(hass, coordinator, _entry("e1", {}))

        before = coordinator.morning_reset_time
        run(entity.async_set_value(time(5, 30)))
        after = coordinator.morning_reset_time

        assert before == time(6, 0)  # SessionConfig default
        assert after == time(5, 30)

    def test_controller_arms_against_new_reset_on_next_tick(self):
        # New reset time takes effect on the next tick's arming check.
        coordinator = CyclestewardCoordinator(_calibrated_profile())
        hass = _make_hass()
        hass.data.setdefault(DOMAIN, {})["e1"] = coordinator
        entity = MorningResetTimeEntity(hass, coordinator, _entry("e1", {}))
        run(entity.async_set_value(time(5, 30)))

        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # Tick after the new reset boundary; controller does not crash and the
        # config value is the one we set.
        t0 = datetime(2026, 6, 16, 5, 45, tzinfo=timezone.utc)
        coordinator.tick(80.0, None, t0, plug_is_on=False)
        assert coordinator.morning_reset_time == time(5, 30)


# ══ Scenario E — services registered and reach the coordinator ════════════════


class TestScenarioE:
    def _setup(self, profile=None, guardrails_config=None):
        hass = _make_hass()
        coordinator = CyclestewardCoordinator(
            profile or _calibrated_profile(),
            guardrails_config=guardrails_config,
        )
        hass.data.setdefault(DOMAIN, {})["e1"] = coordinator
        from custom_components.cyclesteward.services import (
            async_register_services,
        )

        async_register_services(hass)
        return hass, coordinator

    def test_set_mode_service_reaches_coordinator(self):
        hass, coordinator = self._setup()
        assert coordinator.charge_mode == ChargeMode.OFF
        run(hass.services.async_call(
            DOMAIN, "set_mode",
            {"entry_id": "e1", "mode": "charge_to_target"},
        ))
        assert coordinator.charge_mode == ChargeMode.CHARGE_TO_TARGET

    def test_manual_override_service_transitions_to_charging(self):
        hass, coordinator = self._setup()
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        run(hass.services.async_call(
            DOMAIN, "manual_override",
            {"entry_id": "e1", "enabled": True},
        ))
        assert coordinator.session_state == SessionState.CHARGING

    def test_acknowledge_fault_service_clears_fault(self):
        # Force a MAX_RUNTIME fault, then acknowledge via the service.
        hass, coordinator = self._setup(
            guardrails_config=GuardrailsConfig(max_runtime_seconds=10.0)
        )
        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        t0 = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)
        coordinator.tick(80.0, None, t0, plug_is_on=False)  # → CHARGING
        late = datetime(2026, 6, 16, 8, 5, tzinfo=timezone.utc)  # > 10 s runtime
        coordinator.tick(80.0, None, late, plug_is_on=True)
        assert coordinator.session_state == SessionState.FAULTED

        run(hass.services.async_call(
            DOMAIN, "acknowledge_fault", {"entry_id": "e1"},
        ))
        assert coordinator.session_state != SessionState.FAULTED

    def test_unknown_entry_id_raises(self):
        hass, _ = self._setup()
        with pytest.raises(ValueError):
            run(hass.services.async_call(
                DOMAIN, "set_mode",
                {"entry_id": "does-not-exist", "mode": "off"},
            ))

    def test_registration_is_idempotent(self):
        hass, _ = self._setup()
        from custom_components.cyclesteward.services import (
            async_register_services,
        )

        before = dict(hass.services.handlers)
        async_register_services(hass)  # second call: no duplicate / no error
        assert hass.services.handlers.keys() == before.keys()


# ══ Scenario F — services.yaml declares only services with a backing path ══════


def _services_yaml_top_level_keys(text: str) -> set:
    """Top-level service keys = lines starting at column 0 with 'name:' form."""
    return {
        m.group(1)
        for line in text.splitlines()
        if (m := re.match(r"^([a-z_]+):\s*$", line))
    }


class TestScenarioF:
    def test_only_kept_services_declared(self):
        keys = _services_yaml_top_level_keys(SERVICES_YAML.read_text())
        assert keys == {"set_mode", "manual_override", "acknowledge_fault"}

    def test_trimmed_services_absent(self):
        text = SERVICES_YAML.read_text()
        keys = _services_yaml_top_level_keys(text)
        assert "start_calibration_session" not in keys
        assert "import_history" not in keys

    def test_declared_services_all_register(self):
        # Every declared service has a registration in services.py.
        from custom_components.cyclesteward.services import (
            async_register_services,
        )

        hass = _make_hass()
        coordinator = CyclestewardCoordinator(_calibrated_profile())
        hass.data.setdefault(DOMAIN, {})["e1"] = coordinator
        async_register_services(hass)
        registered = {svc for (_dom, svc) in hass.services.handlers}
        declared = _services_yaml_top_level_keys(SERVICES_YAML.read_text())
        assert declared == registered


# ══ Scenario G — timezone discipline: no naive datetimes in scheduling ═════════


class TestScenarioG:
    def test_next_occurrence_is_timezone_aware(self):
        now = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)
        result = next_occurrence(time(9, 30), now)
        assert result.tzinfo is not None
        assert result.tzinfo == now.tzinfo

    def test_future_time_today(self):
        now = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)
        assert next_occurrence(time(9, 30), now) == datetime(
            2026, 6, 16, 9, 30, tzinfo=timezone.utc
        )

    def test_past_time_rolls_to_tomorrow(self):
        now = datetime(2026, 6, 16, 8, 0, tzinfo=timezone.utc)
        assert next_occurrence(time(7, 0), now) == datetime(
            2026, 6, 17, 7, 0, tzinfo=timezone.utc
        )

    def test_equal_to_now_rolls_to_tomorrow(self):
        now = datetime(2026, 6, 16, 8, 0, 0, tzinfo=timezone.utc)
        # 08:00:00 == now → "already past" → tomorrow (no zero-length window).
        assert next_occurrence(time(8, 0), now) == datetime(
            2026, 6, 17, 8, 0, tzinfo=timezone.utc
        )

    def test_sub_second_now_does_not_block_same_day(self):
        now = datetime(2026, 6, 16, 8, 0, 0, 500000, tzinfo=timezone.utc)
        # 08:00:00.0 < 08:00:00.5 now → already past → tomorrow.
        assert next_occurrence(time(8, 0), now) == datetime(
            2026, 6, 17, 8, 0, tzinfo=timezone.utc
        )
