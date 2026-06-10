"""charge_mode SelectEntity — primary entity (ADR-0011)."""

from __future__ import annotations

from typing import Optional

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from cyclesteward.session_control import ChargeMode

from .const import DOMAIN
from .coordinator import CyclestewardCoordinator

OPTIONS = [m.value for m in ChargeMode]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CyclestewardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ChargeModeSelect(coordinator, entry)])


class ChargeModeSelect(SelectEntity):
    """Select entity mirroring ChargeMode; writes call coordinator.set_mode()."""

    _attr_has_entity_name = True
    _attr_name = "Charge mode"
    _attr_options = OPTIONS
    _attr_icon = "mdi:battery-charging-outline"
    _attr_should_poll = False

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_charge_mode"
        self._unsubscribe = coordinator.subscribe(self._on_coordinator_update)

    @property
    def current_option(self) -> Optional[str]:
        return self._coordinator.charge_mode.value

    async def async_select_option(self, option: str) -> None:
        """Write path: mode select → coordinator.set_mode() (ADR-0011)."""
        self._coordinator.set_mode(ChargeMode(option))
        self.async_write_ha_state()

    def _on_coordinator_update(self) -> None:
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._unsubscribe()
