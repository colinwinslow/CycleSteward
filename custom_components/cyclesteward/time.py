"""target_finish_time and morning_reset_time TimeEntities (ADR-0011, ADR-0012).

Stubs for the first adapter slice.  The full scheduling logic (derived
start-time algorithm from ADR-0012) is wired in the scheduling slice.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CyclestewardCoordinator

_DEFAULT_FINISH = time(7, 0)
_DEFAULT_MORNING_RESET = time(6, 0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CyclestewardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TargetFinishTimeEntity(coordinator, entry),
            MorningResetTimeEntity(coordinator, entry),
        ]
    )


class TargetFinishTimeEntity(TimeEntity):
    """User-set target finish time ("ready by X") — start time is derived (ADR-0012)."""

    _attr_has_entity_name = True
    _attr_name = "Target finish time"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_target_finish_time"
        # TODO(scheduling-slice): replace _value with a read from SessionConfig /
        # coordinator once target_finish_time is wired into coordinator.tick()
        # as computed_start_time (ADR-0012 D).
        self._value: time = entry.data.get("target_finish_time", _DEFAULT_FINISH)

    @property
    def native_value(self) -> time:
        return self._value

    async def async_set_value(self, value: time) -> None:
        self._value = value
        self.async_write_ha_state()


class MorningResetTimeEntity(TimeEntity):
    """Time at which modes reset to off daily (ADR-0009)."""

    _attr_has_entity_name = True
    _attr_name = "Morning reset time"
    _attr_icon = "mdi:clock-start"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_morning_reset_time"
        # TODO(scheduling-slice): round-trip through SessionConfig.morning_reset_time
        # once the coordinator exposes a mutable config handle.
        self._value: time = entry.data.get("morning_reset_time", _DEFAULT_MORNING_RESET)

    @property
    def native_value(self) -> time:
        return self._value

    async def async_set_value(self, value: time) -> None:
        self._value = value
        self.async_write_ha_state()
