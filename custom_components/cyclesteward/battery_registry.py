"""Domain-level battery-identity registry (ADR-0014).

A ``BatteryIdentity`` names one charger+battery pair and carries only the
facts that are true regardless of which meter it charges through: labels,
rated capacity, coarse target dots.  Learned profiles stay per
(identity, config entry) in ``ProfileStore`` — wattage anchors never cross
meters (invariant 3).

The registry is shared across all config entries via one domain-level HA
``Store`` (spec D1).  All HA imports are deferred so the module loads under
the offline test stubs.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

STORAGE_VERSION = 1
STORAGE_KEY = "cyclesteward.registry"


def derive_battery_id(battery_label: str) -> str:
    """Deterministic id from the user-facing label (spec D2).

    Determinism makes v1 migration idempotent and converges two entries that
    persisted the same label onto one identity — the same physical battery
    seen from two meters.
    """
    from homeassistant.util import slugify

    return slugify(battery_label)


@dataclass
class BatteryIdentity:
    """Meter-independent facts about one charger+battery pair."""

    battery_id: str  # slug key, stable across renames
    charger_label: str
    battery_label: str
    rated_capacity_wh: Optional[float] = None
    target_soc_dots: Optional[int] = None  # coarse (invariant 6)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "battery_id": self.battery_id,
            "charger_label": self.charger_label,
            "battery_label": self.battery_label,
            "rated_capacity_wh": self.rated_capacity_wh,
            "target_soc_dots": self.target_soc_dots,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BatteryIdentity:
        return cls(
            battery_id=d["battery_id"],
            charger_label=d["charger_label"],
            battery_label=d["battery_label"],
            rated_capacity_wh=d.get("rated_capacity_wh"),
            target_soc_dots=d.get("target_soc_dots"),
        )


class BatteryRegistry:
    """Load, query, and persist battery identities via HA storage.

    Storage key: ``cyclesteward.registry`` (one per HA instance, spec D1).
    Payload: ``{"identities": {battery_id: identity_dict}}``.
    """

    def __init__(self, hass: "HomeAssistant") -> None:
        from homeassistant.helpers.storage import Store

        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._identities: Dict[str, BatteryIdentity] = {}

    async def async_load(self) -> None:
        """Populate the in-memory index from storage (empty if none saved)."""
        data = await self._store.async_load()
        self._identities = (
            {}
            if data is None
            else {
                battery_id: BatteryIdentity.from_dict(d)
                for battery_id, d in data.get("identities", {}).items()
            }
        )

    @property
    def identities(self) -> Dict[str, BatteryIdentity]:
        return dict(self._identities)

    def get(self, battery_id: str) -> Optional[BatteryIdentity]:
        return self._identities.get(battery_id)

    async def async_register(self, identity: BatteryIdentity) -> str:
        """Add a NEW identity; a taken id gets a ``-2``/``-3`` suffix (D2).

        The dash suffix cannot collide with a natural slug (slugify never
        emits dashes).  Returns the final battery_id.
        """
        final_id = identity.battery_id
        n = 1
        while final_id in self._identities:
            n += 1
            final_id = f"{identity.battery_id}-{n}"
        if final_id != identity.battery_id:
            identity = replace(identity, battery_id=final_id)
        self._identities[final_id] = identity
        await self._async_save()
        return final_id

    async def async_ensure(self, identity: BatteryIdentity) -> str:
        """Register iff the id is absent; an existing identity wins (D3).

        This is the reconciliation/setup path: the same battery arriving from
        a second meter must join the existing identity, not fork a suffixed
        copy.
        """
        if identity.battery_id in self._identities:
            return identity.battery_id
        self._identities[identity.battery_id] = identity
        await self._async_save()
        return identity.battery_id

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "identities": {
                    battery_id: identity.to_dict()
                    for battery_id, identity in self._identities.items()
                }
            }
        )
