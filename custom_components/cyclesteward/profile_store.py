"""HA-storage wrapper for CalibrationProfile persistence.

Wraps ``homeassistant.helpers.storage.Store`` so the pure-Python calibration
model can be saved and loaded across HA restarts without the coordinator or
session controller knowing about HA storage.  All HA imports are deferred to
method call time so the module can be imported in tests via sys.modules mocking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from cyclesteward.calibration import CalibrationProfile

STORAGE_VERSION = 1
_STORAGE_KEY_PREFIX = "cyclesteward"


class ProfileStore:
    """Load and save a CalibrationProfile via HA storage.

    Storage key: ``cyclesteward.<entry_id>``.
    Data format: ``CalibrationProfile.to_dict()`` / ``from_dict()``.
    """

    def __init__(self, hass: "HomeAssistant", entry_id: str) -> None:
        from homeassistant.helpers.storage import Store

        self._store: Store = Store(
            hass, STORAGE_VERSION, f"{_STORAGE_KEY_PREFIX}.{entry_id}"
        )

    async def async_load(self) -> Optional[CalibrationProfile]:
        """Return the persisted profile, or None if no data is found."""
        data = await self._store.async_load()
        if data is None:
            return None
        return CalibrationProfile.from_dict(data)

    async def async_save(self, profile: CalibrationProfile) -> None:
        """Persist the profile to HA storage."""
        await self._store.async_save(profile.to_dict())
