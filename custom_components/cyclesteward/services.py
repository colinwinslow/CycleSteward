"""Service registration for CycleSteward.

Registers the three services that have a working coordinator path —
``set_mode``, ``manual_override``, ``acknowledge_fault`` — at the domain level
(once across all entries).  ``start_calibration_session`` and ``import_history``
are intentionally absent until their feature slices land (spec D2); they are not
declared in ``services.yaml`` either, so no declared-but-dead service ships.

All Home Assistant imports are deferred to call time so this module imports in
tests without a HA runtime.  Handlers resolve ``entry_id`` → coordinator via
``hass.data[DOMAIN]`` (spec D1) and call the matching coordinator method; the
coordinator is the single write path shared with the entities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cyclesteward.session_control import ChargeMode

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, ServiceCall

SERVICE_SET_MODE = "set_mode"
SERVICE_MANUAL_OVERRIDE = "manual_override"
SERVICE_ACKNOWLEDGE_FAULT = "acknowledge_fault"


def _resolve_coordinator(hass: "HomeAssistant", entry_id: str):
    """Look up the coordinator for ``entry_id`` or raise if unknown."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    if coordinator is None:
        raise ValueError(f"No CycleSteward config entry with id {entry_id!r}")
    return coordinator


def async_register_services(hass: "HomeAssistant") -> None:
    """Register CycleSteward services once at the domain level.

    Idempotent: a second call (from another entry's setup) is a no-op.
    """
    import voluptuous as vol

    if hass.services.has_service(DOMAIN, SERVICE_SET_MODE):
        return

    set_mode_schema = vol.Schema(
        {
            vol.Required("entry_id"): str,
            vol.Required("mode"): vol.In([m.value for m in ChargeMode]),
        }
    )
    manual_override_schema = vol.Schema(
        {
            vol.Required("entry_id"): str,
            vol.Required("enabled"): bool,
        }
    )
    acknowledge_fault_schema = vol.Schema({vol.Required("entry_id"): str})

    async def _handle_set_mode(call: "ServiceCall") -> None:
        coordinator = _resolve_coordinator(hass, call.data["entry_id"])
        coordinator.set_mode(ChargeMode(call.data["mode"]))

    async def _handle_manual_override(call: "ServiceCall") -> None:
        coordinator = _resolve_coordinator(hass, call.data["entry_id"])
        # On-path mirrors the manual_override switch: enable transitions to
        # CHARGING (cutoff still applies).  The disable path is a no-op at the
        # coordinator level today — override semantics are owned by queued
        # packet #6 (F8); this slice only ships what already works.
        if call.data["enabled"]:
            coordinator.manual_override_on()

    async def _handle_acknowledge_fault(call: "ServiceCall") -> None:
        coordinator = _resolve_coordinator(hass, call.data["entry_id"])
        coordinator.acknowledge_fault()

    hass.services.async_register(
        DOMAIN, SERVICE_SET_MODE, _handle_set_mode, schema=set_mode_schema
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MANUAL_OVERRIDE,
        _handle_manual_override,
        schema=manual_override_schema,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACKNOWLEDGE_FAULT,
        _handle_acknowledge_fault,
        schema=acknowledge_fault_schema,
    )


def async_unregister_services(hass: "HomeAssistant") -> None:
    """Remove the registered services if no config entries remain."""
    for service in (
        SERVICE_SET_MODE,
        SERVICE_MANUAL_OVERRIDE,
        SERVICE_ACKNOWLEDGE_FAULT,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
