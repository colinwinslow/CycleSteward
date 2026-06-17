"""target_finish_time and morning_reset_time TimeEntities (ADR-0011, ADR-0012).

Setting either entity now changes behavior:

- ``TargetFinishTimeEntity`` converts the time-of-day to the next occurrence as a
  timezone-aware datetime (``homeassistant.util.dt`` is the tz authority) and
  calls ``watcher.set_target_finish_time()``, which recomputes the pessimistic
  start time and resets per-cycle probe/overrun state.
- ``MorningResetTimeEntity`` round-trips the time-of-day into
  ``SessionConfig.morning_reset_time`` via ``coordinator.set_morning_reset_time()``.

The watcher and coordinator are reached lazily via ``hass.data[DOMAIN]`` keyed by
``entry_id`` (spec D1) because the watcher is created after platform setup.  The
initial schedule is applied once in ``__init__.async_setup_entry`` so a fresh
install is live without a manual edit.
"""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_MORNING_RESET_HOUR,
    DEFAULT_MORNING_RESET_MINUTE,
    DEFAULT_TARGET_FINISH_HOUR,
    DEFAULT_TARGET_FINISH_MINUTE,
    DOMAIN,
)
from .coordinator import CyclestewardCoordinator
from .schedule import next_occurrence

_DEFAULT_FINISH = time(DEFAULT_TARGET_FINISH_HOUR, DEFAULT_TARGET_FINISH_MINUTE)
_DEFAULT_MORNING_RESET = time(
    DEFAULT_MORNING_RESET_HOUR, DEFAULT_MORNING_RESET_MINUTE
)
_WATCHER_KEY = "watcher"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CyclestewardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            TargetFinishTimeEntity(hass, coordinator, entry),
            MorningResetTimeEntity(hass, coordinator, entry),
        ]
    )


class TargetFinishTimeEntity(TimeEntity):
    """User-set target finish time ("ready by X") — start time is derived (ADR-0012)."""

    _attr_has_entity_name = True
    _attr_name = "Target finish time"
    _attr_icon = "mdi:clock-check-outline"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: CyclestewardCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_target_finish_time"
        self._value: time = entry.data.get("target_finish_time", _DEFAULT_FINISH)

    @property
    def native_value(self) -> time:
        return self._value

    async def async_set_value(self, value: time) -> None:
        self._value = value
        watcher = self._hass.data.get(DOMAIN, {}).get(
            f"{self._entry_id}.{_WATCHER_KEY}"
        )
        if watcher is not None:
            watcher.set_target_finish_time(next_occurrence(value, dt_util.now()))
        self.async_write_ha_state()


class MorningResetTimeEntity(TimeEntity):
    """Time at which modes reset to off daily (ADR-0009)."""

    _attr_has_entity_name = True
    _attr_name = "Morning reset time"
    _attr_icon = "mdi:clock-start"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: CyclestewardCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{entry.entry_id}_morning_reset_time"
        self._value: time = entry.data.get(
            "morning_reset_time", _DEFAULT_MORNING_RESET
        )

    @property
    def native_value(self) -> time:
        return self._value

    async def async_set_value(self, value: time) -> None:
        self._value = value
        self._coordinator.set_morning_reset_time(value)
        self.async_write_ha_state()
