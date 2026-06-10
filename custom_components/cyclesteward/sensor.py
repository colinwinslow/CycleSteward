"""Sensor entities for CycleSteward (ADR-0011).

Primary:
  SessionStateSensor   — session_state with session_reason attr (ADR-0012)
  SocEstimateSensor    — soc_estimate with uncertainty_pct / low_confidence
  FaultSensor          — fault code string; "ok" when no fault

Diagnostic:
  ActiveWhSensor       — idle-subtracted active Wh this session
  TargetWattageSensor  — CC-phase cutoff wattage (unavailable until calibrated)
  RelayCyclesSensor    — relay transitions this session
  SessionStartSensor   — timestamp when current session began
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CyclestewardCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CyclestewardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SessionStateSensor(coordinator, entry),
            SocEstimateSensor(coordinator, entry),
            FaultSensor(coordinator, entry),
            ActiveWhSensor(coordinator, entry),
            TargetWattageSensor(coordinator, entry),
            RelayCyclesSensor(coordinator, entry),
            SessionStartSensor(coordinator, entry),
        ]
    )


class _CoordinatorSensor(SensorEntity):
    """Base class: subscribes to coordinator and pushes HA state updates."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._unsubscribe = coordinator.subscribe(self._on_coordinator_update)

    def _on_coordinator_update(self) -> None:
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._unsubscribe()


# ── Primary sensors ───────────────────────────────────────────────────────────


class SessionStateSensor(_CoordinatorSensor):
    """Current session state string; carries session_reason attribute (ADR-0012)."""

    _attr_name = "Session state"
    _attr_icon = "mdi:state-machine"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_session_state"

    @property
    def native_value(self) -> str:
        return self._coordinator.session_state.value

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        return {"session_reason": self._coordinator.session_reason}


class SocEstimateSensor(_CoordinatorSensor):
    """Estimated SoC with uncertainty metadata (ADR-0002, ADR-0004)."""

    _attr_name = "SoC estimate"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:battery-50"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_soc_estimate"

    @property
    def native_value(self) -> Optional[float]:
        est = self._coordinator.soc_estimate
        return est.estimated_soc_pct if est is not None else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        est = self._coordinator.soc_estimate
        if est is None:
            # Sentinel values before first estimate: maximally uncertain so automations
            # always receive machine-readable numerics (ADR-0004, ADR-0011 consequences).
            return {"uncertainty_pct": 100.0, "low_confidence": True, "method": "wattage_anchor", "note": "no estimate yet"}
        return {
            "uncertainty_pct": est.uncertainty_pct,
            "low_confidence": est.low_confidence,
            "method": "wattage_anchor",
            "note": est.note,
        }


class FaultSensor(_CoordinatorSensor):
    """Active guardrail fault code; "ok" when no fault (ADR-0011)."""

    _attr_name = "Fault"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_fault"

    @property
    def native_value(self) -> str:
        fault = self._coordinator.active_fault
        return fault.value if fault is not None else "ok"


# ── Diagnostic sensors ────────────────────────────────────────────────────────


class ActiveWhSensor(_CoordinatorSensor):
    """Idle-subtracted active Wh accumulated this session."""

    _attr_name = "Active Wh"
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_active_wh"

    @property
    def native_value(self) -> float:
        return round(self._coordinator.active_wh, 2)


class TargetWattageSensor(_CoordinatorSensor):
    """CC-phase wattage cutoff for current target SoC; unavailable until calibrated."""

    _attr_name = "Target wattage"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:flash"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_target_wattage"

    @property
    def native_value(self) -> Optional[float]:
        w = self._coordinator.target_wattage
        return round(w, 1) if w is not None else None

    @property
    def available(self) -> bool:
        return self._coordinator.target_wattage is not None


class RelayCyclesSensor(_CoordinatorSensor):
    """Total relay transitions this session (relay chatter diagnostic)."""

    _attr_name = "Relay cycles"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:swap-horizontal"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_relay_cycles"

    @property
    def native_value(self) -> int:
        return self._coordinator.relay_cycle_count


class SessionStartSensor(_CoordinatorSensor):
    """Timestamp when the current charge session began; unavailable outside CHARGING."""

    _attr_name = "Session start"
    _attr_device_class = "timestamp"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_session_start"

    @property
    def native_value(self) -> Optional[datetime]:
        return self._coordinator.session_start

    @property
    def available(self) -> bool:
        return self._coordinator.session_start is not None
