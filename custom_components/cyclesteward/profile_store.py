"""HA-storage wrapper for the per-entry profile library (ADR-0014 slice 1).

v1 stored a single bare ``CalibrationProfile`` dict.  v2 stores a library
keyed by battery_id plus which one is active:

    {"active_battery_id": "<id or null>", "profiles": {"<id>": {...}}}

Migration is pure data-shape (spec D3): the old payload is wrapped under the
id slugified from its own persisted ``battery_label``; registry
reconciliation happens at setup, not here.  All HA imports are deferred to
call time so the module can be imported in tests via sys.modules mocking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from cyclesteward.calibration import CalibrationProfile

STORAGE_VERSION = 2
_STORAGE_KEY_PREFIX = "cyclesteward"


def migrate_v1_payload(old_data: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap a v1 bare-profile payload as a v2 library.

    The inner profile dict is the v1 payload itself, untouched — anchors,
    observations, and temperature data survive byte-identical (proof
    requirement 3 of the spec).
    """
    from .battery_registry import derive_battery_id

    battery_id = derive_battery_id(old_data["battery_label"])
    return {"active_battery_id": battery_id, "profiles": {battery_id: old_data}}


def _make_store(hass: "HomeAssistant", entry_id: str):
    from homeassistant.helpers.storage import Store

    class _ProfileLibraryStore(Store):
        async def _async_migrate_func(
            self,
            old_major_version: int,
            old_minor_version: int,
            old_data: Dict[str, Any],
        ) -> Dict[str, Any]:
            if old_major_version == 1:
                return migrate_v1_payload(old_data)
            return old_data

    return _ProfileLibraryStore(
        hass, STORAGE_VERSION, f"{_STORAGE_KEY_PREFIX}.{entry_id}"
    )


class ProfileStore:
    """Load and save the entry's CalibrationProfile library via HA storage.

    Storage key: ``cyclesteward.<entry_id>``.  One profile per battery_id;
    ``active_battery_id`` names the one the coordinator runs against.
    """

    def __init__(self, hass: "HomeAssistant", entry_id: str) -> None:
        self._store = _make_store(hass, entry_id)
        self._active_battery_id: Optional[str] = None
        self._profiles: Dict[str, CalibrationProfile] = {}

    async def async_load(self) -> None:
        """Load (migrating v1 data in the process) into the in-memory library."""
        data = await self._store.async_load()
        if data is None:
            self._active_battery_id = None
            self._profiles = {}
            return
        self._active_battery_id = data.get("active_battery_id")
        self._profiles = {
            battery_id: CalibrationProfile.from_dict(profile_dict)
            for battery_id, profile_dict in data.get("profiles", {}).items()
        }

    @property
    def active_battery_id(self) -> Optional[str]:
        return self._active_battery_id

    @property
    def battery_ids(self) -> List[str]:
        return sorted(self._profiles)

    def get_profile(self, battery_id: str) -> Optional[CalibrationProfile]:
        return self._profiles.get(battery_id)

    async def async_set_active(self, battery_id: str) -> None:
        """Persist which battery the coordinator runs against."""
        if battery_id not in self._profiles:
            raise KeyError(
                f"no profile stored for battery_id {battery_id!r}; "
                "save a profile before activating it"
            )
        self._active_battery_id = battery_id
        await self._async_save()

    async def async_save_profile(
        self, battery_id: str, profile: CalibrationProfile
    ) -> None:
        """Persist one battery's profile (adds it to the library if new)."""
        self._profiles[battery_id] = profile
        await self._async_save()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "active_battery_id": self._active_battery_id,
                "profiles": {
                    battery_id: profile.to_dict()
                    for battery_id, profile in self._profiles.items()
                },
            }
        )
