"""Tests for HA adapter slice 3: taper-completion calibration ingestion.

Scenarios A–F from bdd/ha-adapter/ha-calibration-ingestion-bdd.md.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from cyclesteward.calibration import (
    CalibrationProfile,
    ProfileState,
    SocAssumptions,
    WattageAnchor,
)
from cyclesteward.session_control import ChargeMode, SessionConfig, SessionState, TemperatureConfig

from custom_components.cyclesteward.coordinator import CyclestewardCoordinator

# ── helpers ───────────────────────────────────────────────────────────────────

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def t(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _calibrated_profile(
    watts_at_low: float = 70.0,
    watts_at_transition: float = 130.0,
    taper_floor_w: float = 15.0,
    active_full_wh: float = 400.0,
    reference_temp_c: Optional[float] = None,
) -> CalibrationProfile:
    p = CalibrationProfile(
        charger_label="test-charger",
        battery_label="test-battery",
        meter_id="test-meter",
    )
    p.state = ProfileState.CALIBRATED
    p.watts_at_low = WattageAnchor(watts=watts_at_low, assumed_soc_label="display_empty")
    p.watts_at_transition = WattageAnchor(
        watts=watts_at_transition, assumed_soc_label="cc_cv_transition"
    )
    p.taper_floor_w = taper_floor_w
    p.active_full_wh = active_full_wh
    p.idle_power_w = 2.0
    p.assumptions = SocAssumptions(soc_at_low_pct=0.0, soc_at_transition_pct=80.0)
    p.reference_temp_c = reference_temp_c
    return p


def _make_hass(plug_state: str = "off") -> SimpleNamespace:
    plug_mock = SimpleNamespace(state=plug_state)
    return SimpleNamespace(
        states=SimpleNamespace(get=lambda entity_id: plug_mock),
        services=SimpleNamespace(async_call=AsyncMock()),
        bus=SimpleNamespace(async_fire=MagicMock()),
    )


def _make_profile_store_mock() -> MagicMock:
    store = MagicMock()
    store.async_save = AsyncMock()
    return store


def _make_watcher(profile=None, plug_state="off", profile_store=None, temp_coeff=0.0):
    from custom_components.cyclesteward.watcher import HASensorWatcher

    if profile is None:
        profile = _calibrated_profile()
    temp_config = TemperatureConfig(temp_coeff_w_per_c=temp_coeff, baseline_temp_c=20.0)
    coordinator = CyclestewardCoordinator(profile, temp_config=temp_config)
    hass = _make_hass(plug_state=plug_state)
    watcher = HASensorWatcher(
        hass=hass,
        coordinator=coordinator,
        power_entity_id="sensor.plug_power",
        plug_entity_id="switch.plug",
        profile_store=profile_store,
    )
    return watcher, coordinator, hass


def _near_empty_to_taper_trace(
    n_cc: int = 10,
    cc_start_w: float = 95.0,
    cc_end_w: float = 70.0,
    n_cv: int = 5,
    cv_w: float = 40.0,
    taper_w: float = 10.0,
    n_taper: int = 3,
    start_time: datetime = T0,
    interval_s: int = 360,
) -> List[Tuple[datetime, float]]:
    """Build a synthetic CC→CV→taper trace."""
    trace = []
    now = start_time
    for i in range(n_cc):
        frac = i / max(n_cc - 1, 1)
        w = cc_start_w + frac * (cc_end_w - cc_start_w)
        trace.append((now, w))
        now += timedelta(seconds=interval_s)
    for _ in range(n_cv):
        trace.append((now, cv_w))
        now += timedelta(seconds=interval_s)
    for _ in range(n_taper):
        trace.append((now, taper_w))
        now += timedelta(seconds=interval_s)
    return trace


def run(coro):
    return asyncio.run(coro)


# ── Scenario A: taper-floor completion → ingest and save ─────────────────────


class TestScenarioA:
    """Taper-floor DONE_LATCHED_OFF in CHARGE_TO_FULL → ingest_full_session + save."""

    def _drive_to_taper_completion(self, coordinator, watcher):
        """Drive coordinator from IDLE through CHARGING to DONE_LATCHED_OFF via taper."""
        coordinator.set_mode(ChargeMode.CHARGE_TO_FULL)
        # CC phase: above idle, below transition
        for i, w in enumerate([95.0, 90.0, 85.0, 80.0, 75.0, 70.0]):
            run(watcher._do_tick(w, t(i * 60)))
        assert coordinator.session_state == SessionState.CHARGING
        # CV / taper phase: below taper_floor_w (15 W) for taper_below_floor_seconds
        # SessionConfig default taper_below_floor_seconds=300 → use 1-second config
        # (set via _make_watcher's coordinator)

    def test_ingest_full_session_called_on_taper_completion(self):
        # watts_at_low=90 W so the CC-start detected from the trace (~95 W) is
        # within the 15% proximity threshold → qualifies as full ingestion.
        profile = _calibrated_profile(watts_at_low=90.0, taper_floor_w=30.0)
        config = SessionConfig(taper_below_floor_seconds=1)
        store_mock = _make_profile_store_mock()
        temp_config = TemperatureConfig()

        from custom_components.cyclesteward.watcher import HASensorWatcher

        coordinator = CyclestewardCoordinator(profile, config=config, temp_config=temp_config)
        hass = _make_hass()
        watcher = HASensorWatcher(
            hass, coordinator, "sensor.plug_power", "switch.plug",
            profile_store=store_mock,
        )

        coordinator.set_mode(ChargeMode.CHARGE_TO_FULL)
        # CC phase
        for i, w in enumerate([95.0, 90.0, 85.0, 80.0, 75.0]):
            run(watcher._do_tick(w, t(i * 120)))
        assert coordinator.session_state == SessionState.CHARGING

        # Taper phase: below taper_floor_w=30 W for >1 s
        run(watcher._do_tick(20.0, t(700)))
        run(watcher._do_tick(18.0, t(702)))  # 2 s dwell → fires taper cutoff
        run(watcher._do_tick(15.0, t(704)))

        assert coordinator.session_state == SessionState.DONE_LATCHED_OFF
        # Store must have been called once with the updated profile
        store_mock.async_save.assert_called_once()
        saved_profile = store_mock.async_save.call_args[0][0]
        assert len(saved_profile.full_observations) == 1

    def test_elapsed_seconds_recorded(self):
        # Use uncalibrated profile so any taper-floor completion qualifies as full
        # (first-calibration path; no proximity check needed).
        profile = CalibrationProfile(
            charger_label="test-charger", battery_label="test-battery", meter_id="test-meter"
        )
        profile.taper_floor_w = 30.0
        config = SessionConfig(taper_below_floor_seconds=1)
        store_mock = _make_profile_store_mock()

        from custom_components.cyclesteward.watcher import HASensorWatcher

        coordinator = CyclestewardCoordinator(profile, config=config)
        hass = _make_hass()
        watcher = HASensorWatcher(
            hass, coordinator, "sensor.plug_power", "switch.plug",
            profile_store=store_mock,
        )

        coordinator.set_mode(ChargeMode.CHARGE_TO_FULL)
        # Enough CC samples to avoid CALIBRATION_DISTRUST
        for i, w in enumerate([90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 78.0]):
            run(watcher._do_tick(w, t(i * 300)))
        run(watcher._do_tick(20.0, t(2500)))
        run(watcher._do_tick(18.0, t(2502)))  # 2 s dwell → taper fires

        assert coordinator.session_state == SessionState.DONE_LATCHED_OFF
        store_mock.async_save.assert_called_once()
        saved = store_mock.async_save.call_args[0][0]
        assert len(saved.elapsed_seconds) >= 1
        assert saved.elapsed_seconds[0] > 0


# ── Scenario B: CHARGE_TO_TARGET → NOT ingested ───────────────────────────────


class TestScenarioB:
    """CHARGE_TO_TARGET session ends at target wattage → no ingest, no save."""

    def test_no_ingest_on_charge_to_target_completion(self):
        profile = _calibrated_profile(
            watts_at_low=65.0, watts_at_transition=130.0, taper_floor_w=15.0
        )
        store_mock = _make_profile_store_mock()

        from custom_components.cyclesteward.watcher import HASensorWatcher

        coordinator = CyclestewardCoordinator(profile)
        hass = _make_hass()
        watcher = HASensorWatcher(
            hass, coordinator, "sensor.plug_power", "switch.plug",
            profile_store=store_mock,
        )

        coordinator.set_mode(ChargeMode.CHARGE_TO_TARGET)
        # CC phase: below target (target = watts_at_transition = 130 W at 80% SoC)
        run(watcher._do_tick(80.0, t(0)))
        assert coordinator.session_state == SessionState.CHARGING
        # Tick at 35 s to clear min_dwell, then hit target
        run(watcher._do_tick(130.0, t(35)))

        assert coordinator.session_state == SessionState.DONE_LATCHED_OFF
        # Reason should mention target threshold, not taper floor
        assert "taper floor" not in coordinator.session_reason
        store_mock.async_save.assert_not_called()
        assert len(profile.full_observations) == 0
        assert len(profile.partial_observations) == 0


# ── Scenario C: CHARGE_TO_FULL + guardrail fault → NOT ingested ───────────────


class TestScenarioC:
    """CHARGE_TO_FULL with max-runtime guardrail fault → no ingest, no save."""

    def test_no_ingest_on_guardrail_fault(self):
        from cyclesteward.guardrails import GuardrailsConfig

        profile = _calibrated_profile(taper_floor_w=15.0)
        store_mock = _make_profile_store_mock()
        config = SessionConfig(taper_below_floor_seconds=300)
        guardrails = GuardrailsConfig(max_runtime_seconds=5)  # trips almost immediately

        from custom_components.cyclesteward.watcher import HASensorWatcher

        coordinator = CyclestewardCoordinator(profile, config=config, guardrails_config=guardrails)
        hass = _make_hass()
        watcher = HASensorWatcher(
            hass, coordinator, "sensor.plug_power", "switch.plug",
            profile_store=store_mock,
        )

        coordinator.set_mode(ChargeMode.CHARGE_TO_FULL)
        run(watcher._do_tick(80.0, t(0)))
        assert coordinator.session_state == SessionState.CHARGING
        # Advance past the 5-second max_runtime
        run(watcher._do_tick(80.0, t(6)))

        # Should have faulted (DONE_LATCHED_OFF with guardrail reason or FAULTED)
        assert coordinator.session_state in (SessionState.DONE_LATCHED_OFF, SessionState.FAULTED)
        # "taper floor" must NOT be in the reason — ingestion trigger must not have fired
        assert "taper floor" not in coordinator.session_reason
        store_mock.async_save.assert_not_called()


# ── Scenario D: anchor artifact + profile round-trip ─────────────────────────


class TestScenarioD:
    """Ingested profile shows elapsed_seconds; round-trips through to_json/from_json.
    Writes the anchor artifact to bdd/ha-adapter/ha-calibration-ingestion-trace.json.
    """

    def test_elapsed_seconds_and_round_trip(self, tmp_path):
        from custom_components.cyclesteward.coordinator import CyclestewardCoordinator

        profile = CalibrationProfile(
            charger_label="test-charger",
            battery_label="test-battery",
            meter_id="test-meter",
        )
        # Start uncalibrated so first ingestion sets all anchors
        profile_before_json = profile.to_dict()

        coordinator = CyclestewardCoordinator(profile)
        trace = _near_empty_to_taper_trace(
            n_cc=10,
            cc_start_w=95.0,
            cc_end_w=72.0,
            n_cv=5,
            cv_w=40.0,
            taper_w=10.0,
            n_taper=3,
            start_time=T0,
            interval_s=360,  # 6-min intervals → ~108-min total
        )

        updated = coordinator.ingest_from_trace(trace)

        assert len(updated.elapsed_seconds) == 1
        elapsed = updated.elapsed_seconds[0]
        assert elapsed == pytest.approx((len(trace) - 1) * 360, abs=1)

        # Round-trip
        restored = CalibrationProfile.from_json(updated.to_json())
        assert len(restored.elapsed_seconds) == 1
        assert restored.elapsed_seconds[0] == pytest.approx(elapsed)

        # Write anchor artifact
        artifact_path = (
            __file__.replace("tests/test_ha_calibration_ingestion.py", "")
            + "bdd/ha-adapter/ha-calibration-ingestion-trace.json"
        )
        artifact = {
            "description": (
                "Anchor artifact for HA calibration ingestion slice 3. "
                "profile_before = fresh uncalibrated profile; "
                "raw_trace = synthetic CC->CV->taper readings; "
                "profile_after = result of ingest_from_trace()."
            ),
            "profile_before": profile_before_json,
            "raw_trace": [
                [ts.isoformat(), round(w, 3)] for ts, w in trace
            ],
            "profile_after": updated.to_dict(),
        }
        import os
        os.makedirs(os.path.dirname(artifact_path), exist_ok=True)
        with open(artifact_path, "w") as f:
            json.dump(artifact, f, indent=2)
            f.write("\n")

    def test_estimated_duration_s_pessimistic_when_no_observations(self):
        profile = CalibrationProfile(
            charger_label="c", battery_label="b", meter_id="m"
        )
        mean, unc = profile.estimated_duration_s()
        assert mean == pytest.approx(4 * 3600)
        assert unc == pytest.approx(0.2 * 4 * 3600)

    def test_estimated_duration_s_from_single_observation(self):
        profile = CalibrationProfile(
            charger_label="c", battery_label="b", meter_id="m"
        )
        coordinator = CyclestewardCoordinator(profile)
        trace = _near_empty_to_taper_trace(n_cc=5, interval_s=600)
        coordinator.ingest_from_trace(trace)
        mean, unc = profile.estimated_duration_s()
        assert mean > 0
        assert unc == pytest.approx(0.2 * mean, rel=1e-3)

    def test_estimated_duration_excludes_untrusted_observations(self):
        """Untrusted (interrupted/distrusted) sessions must not pollute the
        duration estimate that drives probe timing (review finding F6)."""
        from datetime import datetime, timezone

        from cyclesteward.calibration import FullObservation

        profile = CalibrationProfile(
            charger_label="c", battery_label="b", meter_id="m"
        )
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        profile.full_observations.append(
            FullObservation(
                timestamp=ts, active_wh=400.0, watts_at_low=65.0,
                watts_at_transition=130.0, trusted=True, elapsed_seconds=3600.0,
            )
        )
        profile.full_observations.append(
            FullObservation(
                timestamp=ts, active_wh=120.0, watts_at_low=65.0,
                watts_at_transition=130.0, trusted=False, elapsed_seconds=90000.0,
            )
        )
        assert profile.elapsed_seconds == [3600.0]
        mean, unc = profile.estimated_duration_s()
        assert mean == pytest.approx(3600.0)

    def test_estimated_duration_s_stddev_with_three_observations(self):
        """With ≥3 observations, uncertainty uses stddev, not fixed 20%."""
        profile = CalibrationProfile(
            charger_label="c", battery_label="b", meter_id="m"
        )
        coordinator = CyclestewardCoordinator(profile)
        # Three traces of different lengths: 10, 15, 20 intervals
        for n in (10, 15, 20):
            trace = _near_empty_to_taper_trace(n_cc=n, interval_s=360)
            coordinator.ingest_from_trace(trace)
        mean, unc = profile.estimated_duration_s()
        durations = profile.elapsed_seconds
        assert len(durations) == 3
        expected_mean = sum(durations) / 3
        import math
        expected_std = math.sqrt(sum((d - expected_mean) ** 2 for d in durations) / 3)
        assert mean == pytest.approx(expected_mean, rel=1e-6)
        assert unc == pytest.approx(expected_std, rel=1e-6)


# ── Scenario E: temperature correction promotes warm-start session to full ────


class TestScenarioE:
    """Cold-calibrated anchor + warm session: temp correction rescues it as full."""

    def test_temp_correction_promotes_warm_session_to_full(self):
        # Profile calibrated at 8°C: watts_at_low = 65.0 W
        # Session starts at 75 W.
        # Raw proximity: |75-65|/65 = 15.4% → EXCEEDS 15% default → would be partial
        # Corrected: 75 + 0.3*(8-25) = 69.9 W → 7.5% → within threshold → full
        # The test explicitly checks BOTH paths to prove correction is load-bearing.
        profile_raw = _calibrated_profile(
            watts_at_low=65.0, watts_at_transition=130.0, taper_floor_w=15.0,
            reference_temp_c=8.0,
        )
        profile_corrected = _calibrated_profile(
            watts_at_low=65.0, watts_at_transition=130.0, taper_floor_w=15.0,
            reference_temp_c=8.0,
        )
        temp_config = TemperatureConfig(temp_coeff_w_per_c=0.3, baseline_temp_c=20.0)
        trace = _near_empty_to_taper_trace(
            cc_start_w=75.0, cc_end_w=75.0, n_cc=5, cv_w=40.0, taper_w=10.0
        )

        # Without temperature correction: raw 75 W vs 65 W anchor = 15.4% → partial
        coord_raw = CyclestewardCoordinator(profile_raw, temp_config=temp_config)
        coord_raw.ingest_from_trace(trace, session_temp_c=None)
        assert len(profile_raw.full_observations) == 0, (
            "without temp correction, 75 W / 65 W anchor (15.4%) should be partial"
        )
        assert len(profile_raw.partial_observations) == 1

        # With temperature correction: corrected 69.9 W vs 65 W = 7.5% → full
        coord_corrected = CyclestewardCoordinator(profile_corrected, temp_config=temp_config)
        coord_corrected.ingest_from_trace(trace, session_temp_c=25.0)
        assert len(profile_corrected.full_observations) == 1, (
            "with temp correction, 69.9 W / 65 W anchor (7.5%) should qualify as full"
        )
        assert len(profile_corrected.partial_observations) == 0

    def test_no_temp_reading_uses_raw_comparison(self):
        """Without temp reading, raw wattage is compared. May demote valid session."""
        profile = _calibrated_profile(
            watts_at_low=65.0,
            reference_temp_c=8.0,
        )
        temp_config = TemperatureConfig(temp_coeff_w_per_c=0.3, baseline_temp_c=20.0)
        coordinator = CyclestewardCoordinator(profile, temp_config=temp_config)

        # Same 73 W start, but no temp reading → raw: |73-65|/65 = 12.3% > 10% default
        # With our 15% tolerance it's actually within range — test the boundary case
        # at 85 W which is 30% above anchor → definitely demoted
        trace = _near_empty_to_taper_trace(cc_start_w=85.0, cc_end_w=85.0, n_cc=5, cv_w=40.0, taper_w=10.0)
        updated = coordinator.ingest_from_trace(trace, session_temp_c=None)

        # 85 W is 30% above 65 W anchor even without correction → partial
        assert len(updated.partial_observations) == 1
        assert len(updated.full_observations) == 0

    def test_reference_temp_updated_on_trusted_full_ingestion(self):
        """After a trusted full ingestion, reference_temp_c is stored on the profile."""
        # Uncalibrated profile: first ingestion always goes to ingest_full_session
        # (first-calibration path) and if trusted, sets reference_temp_c.
        profile = CalibrationProfile(
            charger_label="c", battery_label="b", meter_id="m"
        )
        coordinator = CyclestewardCoordinator(
            profile,
            temp_config=TemperatureConfig(temp_coeff_w_per_c=0.3, baseline_temp_c=20.0),
        )
        # Use a longer trace (20 CC points) to avoid CALIBRATION_DISTRUST
        trace = _near_empty_to_taper_trace(
            cc_start_w=72.0, cc_end_w=70.0, n_cc=20,
            cv_w=35.0, n_cv=8, taper_w=10.0, n_taper=5,
            interval_s=300,
        )
        coordinator.ingest_from_trace(trace, session_temp_c=22.0)
        assert profile.full_observations, "ingest should have produced a full observation"
        assert profile.full_observations[-1].trusted, (
            "observation should be trusted; if not, the trace may be too short or distrust-flagged"
        )
        assert profile.reference_temp_c == pytest.approx(22.0)


# ── Scenario F: genuine mid-charge → partial, anchors protected ───────────────


class TestScenarioF:
    """Session starts at 110 W against 70 W anchor (same temp) → partial, not full."""

    def test_mid_charge_session_demoted_to_partial(self):
        profile = _calibrated_profile(
            watts_at_low=70.0,
            watts_at_transition=130.0,
            taper_floor_w=15.0,
            active_full_wh=400.0,
            reference_temp_c=20.0,
        )
        temp_config = TemperatureConfig(temp_coeff_w_per_c=0.3, baseline_temp_c=20.0)
        coordinator = CyclestewardCoordinator(profile, temp_config=temp_config)

        # Trace starting at 110 W — clearly mid-charge, 57% above anchor
        trace = _near_empty_to_taper_trace(
            cc_start_w=110.0, cc_end_w=105.0, n_cc=5,
            cv_w=60.0, taper_w=10.0
        )
        updated = coordinator.ingest_from_trace(trace, session_temp_c=20.0)

        # Should be partial, not full
        assert len(updated.full_observations) == 0
        assert len(updated.partial_observations) == 1

    def test_watts_at_low_anchor_unchanged_after_mid_charge(self):
        profile = _calibrated_profile(watts_at_low=70.0, reference_temp_c=20.0)
        coordinator = CyclestewardCoordinator(profile)

        trace = _near_empty_to_taper_trace(cc_start_w=110.0, cc_end_w=108.0, n_cc=5, cv_w=60.0, taper_w=10.0)
        coordinator.ingest_from_trace(trace, session_temp_c=20.0)

        assert profile.watts_at_low.watts == pytest.approx(70.0)

    def test_active_full_wh_unchanged_after_mid_charge(self):
        profile = _calibrated_profile(watts_at_low=70.0, active_full_wh=400.0, reference_temp_c=20.0)
        coordinator = CyclestewardCoordinator(profile)

        trace = _near_empty_to_taper_trace(cc_start_w=110.0, cc_end_w=108.0, n_cc=5, cv_w=60.0, taper_w=10.0)
        coordinator.ingest_from_trace(trace, session_temp_c=20.0)

        assert profile.active_full_wh == pytest.approx(400.0)

    def test_save_still_called_for_mid_charge_partial(self):
        """ProfileStore.save is called even for partial ingestion."""
        profile = _calibrated_profile(
            watts_at_low=70.0, taper_floor_w=30.0, reference_temp_c=20.0
        )
        store_mock = _make_profile_store_mock()
        config = SessionConfig(taper_below_floor_seconds=1)

        from custom_components.cyclesteward.watcher import HASensorWatcher

        coordinator = CyclestewardCoordinator(profile, config=config)
        hass = _make_hass()
        watcher = HASensorWatcher(
            hass, coordinator, "sensor.plug_power", "switch.plug",
            profile_store=store_mock,
        )

        coordinator.set_mode(ChargeMode.CHARGE_TO_FULL)
        # Drive with a high starting wattage (mid-charge)
        for i, w in enumerate([110.0, 108.0, 105.0]):
            run(watcher._do_tick(w, t(i * 120)))
        # Taper: below 30 W for >1 s
        run(watcher._do_tick(20.0, t(400)))
        run(watcher._do_tick(18.0, t(402)))

        assert coordinator.session_state == SessionState.DONE_LATCHED_OFF, (
            "coordinator should reach DONE_LATCHED_OFF after taper; check taper_floor_w "
            "and taper_below_floor_seconds configuration"
        )
        # Even mid-charge partial → save called
        store_mock.async_save.assert_called_once()
        saved = store_mock.async_save.call_args[0][0]
        assert len(saved.full_observations) == 0
        assert len(saved.partial_observations) == 1


# ── ingest_from_trace unit tests ──────────────────────────────────────────────


class TestIngestFromTrace:
    def test_empty_trace_returns_profile_unchanged(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        result = coordinator.ingest_from_trace([])
        assert result is profile
        assert len(profile.full_observations) == 0

    def test_first_calibration_no_anchor_always_full(self):
        """Uncalibrated profile has no watts_at_low → first session goes to full."""
        profile = CalibrationProfile(
            charger_label="c", battery_label="b", meter_id="m"
        )
        coordinator = CyclestewardCoordinator(profile)
        trace = _near_empty_to_taper_trace()
        result = coordinator.ingest_from_trace(trace)
        assert len(result.full_observations) == 1

    def test_near_anchor_start_ingest_full(self):
        profile = _calibrated_profile(watts_at_low=70.0, reference_temp_c=20.0)
        coordinator = CyclestewardCoordinator(profile)
        # Start at 72 W — within 15% of 70 W anchor
        trace = _near_empty_to_taper_trace(cc_start_w=72.0, cc_end_w=70.0)
        coordinator.ingest_from_trace(trace, session_temp_c=20.0)
        assert len(profile.full_observations) == 1
        assert len(profile.partial_observations) == 0

    def test_far_from_anchor_start_ingest_partial(self):
        profile = _calibrated_profile(watts_at_low=70.0, reference_temp_c=20.0)
        coordinator = CyclestewardCoordinator(profile)
        # Start at 110 W — ~57% above anchor
        trace = _near_empty_to_taper_trace(cc_start_w=110.0, cc_end_w=108.0)
        coordinator.ingest_from_trace(trace, session_temp_c=20.0)
        assert len(profile.full_observations) == 0
        assert len(profile.partial_observations) == 1

    def test_profile_property_returns_current_profile(self):
        profile = _calibrated_profile()
        coordinator = CyclestewardCoordinator(profile)
        assert coordinator.profile is profile
