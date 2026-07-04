"""CycleSteward Home Assistant integration.

Wraps the pure CycleSteward core (src/cyclesteward) with HA config-entry
lifecycle, entity platforms, and services.  All estimation logic lives in the
core; this layer owns only HA plumbing.  See ADR-0006.
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from cyclesteward.calibration import CalibrationProfile

from .battery_registry import BatteryIdentity, BatteryRegistry, derive_battery_id
from .const import (
    DEFAULT_MARGIN_S,
    DEFAULT_MORNING_RESET_HOUR,
    DEFAULT_MORNING_RESET_MINUTE,
    DEFAULT_TARGET_FINISH_HOUR,
    DEFAULT_TARGET_FINISH_MINUTE,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import CyclestewardCoordinator
from .profile_store import ProfileStore
from .schedule import next_occurrence
from .services import async_register_services, async_unregister_services
from .watcher import HASensorWatcher

_WATCHER_KEY = "watcher"
_REGISTRY_KEY = "registry"

_DEFAULT_TARGET_FINISH = time(
    DEFAULT_TARGET_FINISH_HOUR, DEFAULT_TARGET_FINISH_MINUTE
)
_DEFAULT_MORNING_RESET = time(
    DEFAULT_MORNING_RESET_HOUR, DEFAULT_MORNING_RESET_MINUTE
)


async def _async_get_registry(hass: "HomeAssistant") -> BatteryRegistry:
    """Return the shared battery registry, loading it on first use (ADR-0014)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    registry: BatteryRegistry | None = domain_data.get(_REGISTRY_KEY)
    if registry is None:
        registry = BatteryRegistry(hass)
        await registry.async_load()
        domain_data[_REGISTRY_KEY] = registry
    return registry


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Set up CycleSteward from a config entry."""
    registry = await _async_get_registry(hass)

    store = ProfileStore(hass, entry.entry_id)
    await store.async_load()

    # Reconcile (spec D3): every stored profile's identity must exist in the
    # registry, built from that profile's own persisted labels.  The entry's
    # coarse target dots apply only to the battery this entry configured.
    entry_battery_label = entry.data.get("battery_label")
    entry_battery_id = (
        derive_battery_id(entry_battery_label) if entry_battery_label else None
    )
    for battery_id in store.battery_ids:
        stored = store.get_profile(battery_id)
        await registry.async_ensure(
            BatteryIdentity(
                battery_id=battery_id,
                charger_label=stored.charger_label,
                battery_label=stored.battery_label,
                rated_capacity_wh=stored.rated_capacity_wh,
                target_soc_dots=(
                    entry.data.get("target_soc_dots")
                    if battery_id == entry_battery_id
                    else None
                ),
            )
        )

    if not store.battery_ids:
        # Fresh install: build the profile from entry data as before.  ensure
        # (not register) so the same battery arriving from a second meter
        # joins its existing identity instead of forking a suffixed copy.
        profile = CalibrationProfile(
            charger_label=entry.data.get("charger_label", "charger"),
            battery_label=entry.data.get("battery_label", "battery"),
            meter_id=entry.data.get("meter_id", "meter"),
            rated_capacity_wh=entry.data.get("rated_capacity_wh"),
        )
        battery_id = await registry.async_ensure(
            BatteryIdentity(
                battery_id=derive_battery_id(profile.battery_label),
                charger_label=profile.charger_label,
                battery_label=profile.battery_label,
                rated_capacity_wh=profile.rated_capacity_wh,
                target_soc_dots=entry.data.get("target_soc_dots"),
            )
        )
        await store.async_save_profile(battery_id, profile)
        await store.async_set_active(battery_id)
    elif (
        store.active_battery_id is None
        or store.get_profile(store.active_battery_id) is None
    ):
        # v2 payload with no active selection, or one naming a missing
        # profile (defensive): pick deterministically rather than handing the
        # coordinator None.
        await store.async_set_active(store.battery_ids[0])

    profile = store.get_profile(store.active_battery_id)

    coordinator = CyclestewardCoordinator(profile)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Apply the configured morning-reset time so the schedule is live without a
    # manual edit (spec §2).
    coordinator.set_morning_reset_time(
        entry.data.get("morning_reset_time", _DEFAULT_MORNING_RESET)
    )

    async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    power_entity_id = entry.data.get("power_entity_id", "")
    plug_entity_id = entry.data.get("plug_entity_id", "")
    temp_entity_id = entry.data.get("temp_entity_id")

    if power_entity_id and plug_entity_id:
        from homeassistant.util import dt as dt_util

        watcher = HASensorWatcher(
            hass,
            coordinator,
            power_entity_id=power_entity_id,
            plug_entity_id=plug_entity_id,
            temp_entity_id=temp_entity_id,
            profile_store=store,
            margin_s=float(entry.data.get("margin_s", DEFAULT_MARGIN_S)),
        )
        # Apply the configured target finish time once so the derived start time
        # is live without a manual edit (spec §2).
        target_finish_tod = entry.data.get(
            "target_finish_time", _DEFAULT_TARGET_FINISH
        )
        watcher.set_target_finish_time(
            next_occurrence(target_finish_tod, dt_util.now())
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

    # Drop domain-level services when the last entry is gone (only coordinator
    # entries remain in hass.data[DOMAIN]; watcher keys contain a dot, and the
    # shared battery registry is not an entry).
    remaining = [
        key
        for key in hass.data.get(DOMAIN, {})
        if "." not in key and key != _REGISTRY_KEY
    ]
    if not remaining:
        async_unregister_services(hass)

    return unload_ok
