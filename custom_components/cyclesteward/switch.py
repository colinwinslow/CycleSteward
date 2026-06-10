"""manual_override SwitchEntity — primary entity (ADR-0011)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CyclestewardCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CyclestewardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ManualOverrideSwitch(coordinator, entry)])


class ManualOverrideSwitch(SwitchEntity):
    """Switch that activates manual override, bypassing the schedule but not cutoff."""

    _attr_has_entity_name = True
    _attr_name = "Manual override"
    _attr_icon = "mdi:hand-back-right-outline"
    _attr_should_poll = False

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_manual_override"
        # TODO(scheduling-slice): replace with coordinator.manual_override_active once
        # SessionController exposes a readable override state.  _is_on is temporary
        # shadow state that violates ADR-0011's "no adapter-owned derived state" rule.
        self._is_on = False
        self._unsubscribe = coordinator.subscribe(self._on_coordinator_update)

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: object) -> None:
        self._is_on = True
        self._coordinator.manual_override_on()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        self._is_on = False
        self.async_write_ha_state()

    def _on_coordinator_update(self) -> None:
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._unsubscribe()
