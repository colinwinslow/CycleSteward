"""acknowledge_fault ButtonEntity — recovery entity (ADR-0011)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities([AcknowledgeFaultButton(coordinator, entry)])


class AcknowledgeFaultButton(ButtonEntity):
    """Clears a non-terminal fault and returns to IDLE (ADR-0011).

    Does nothing when no fault is active.  FREEZE_LOCKOUT never produces a
    FAULTED state so this button is never reached for temperature lock-outs.
    """

    _attr_has_entity_name = True
    _attr_name = "Acknowledge fault"
    _attr_icon = "mdi:bell-check-outline"

    def __init__(
        self, coordinator: CyclestewardCoordinator, entry: ConfigEntry
    ) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_acknowledge_fault"

    async def async_press(self) -> None:
        self._coordinator.acknowledge_fault()
