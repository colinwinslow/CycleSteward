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
from .profile_store import ProfileStore
from .watcher import HASensorWatcher

_WATCHER_KEY = "watcher"


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Set up CycleSteward from a config entry."""
    store = ProfileStore(hass, entry.entry_id)
    profile = await store.async_load()

    if profile is None:
        profile = CalibrationProfile(
            charger_label=entry.data.get("charger_label", "charger"),
            battery_label=entry.data.get("battery_label", "battery"),
            meter_id=entry.data.get("meter_id", "meter"),
            rated_capacity_wh=entry.data.get("rated_capacity_wh"),
        )

    coordinator = CyclestewardCoordinator(profile)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    power_entity_id = entry.data.get("power_entity_id", "")
    plug_entity_id = entry.data.get("plug_entity_id", "")
    temp_entity_id = entry.data.get("temp_entity_id")

    if power_entity_id and plug_entity_id:
        watcher = HASensorWatcher(
            hass,
            coordinator,
            power_entity_id=power_entity_id,
            plug_entity_id=plug_entity_id,
            temp_entity_id=temp_entity_id,
            profile_store=store,
        )
        await watcher.async_start()
        hass.data[DOMAIN][f"{entry.entry_id}.{_WATCHER_KEY}"] = watcher

    return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Unload a config entry."""
    watcher_key = f"{entry.entry_id}.{_WATCHER_KEY}"
    watcher: HASensorWatcher | None = hass.data[DOMAIN].pop(watcher_key, None)
    if watcher is not None:
        await watcher.async_stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
