"""CycleSteward Home Assistant integration.

Wraps the pure CycleSteward core (src/cyclesteward) with HA config-entry
lifecycle, entity platforms, and services.  All estimation logic lives in the
core; this layer owns only HA plumbing.  See ADR-0006.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from cyclesteward.calibration import CalibrationProfile

from .const import DOMAIN, PLATFORMS
from .coordinator import CyclestewardCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CycleSteward from a config entry."""
    from homeassistant.config_entries import ConfigEntry as _CE  # noqa: F401

    profile = CalibrationProfile(
        charger_label=entry.data.get("charger_label", "charger"),
        battery_label=entry.data.get("battery_label", "battery"),
        meter_id=entry.data.get("meter_id", "meter"),
        rated_capacity_wh=entry.data.get("rated_capacity_wh"),
    )
    coordinator = CyclestewardCoordinator(profile)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
