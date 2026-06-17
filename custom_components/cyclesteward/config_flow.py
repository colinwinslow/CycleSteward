"""Config flow for CycleSteward.

Collects the profile-identity fields plus the operational inputs the watcher
needs to actually run: the power sensor, the controlled plug switch, and an
optional temperature sensor, plus a coarse target SoC and the scheduling margin.
Without the entity IDs, ``async_setup_entry`` never starts the watcher and the
integration is inert (review finding F1; see docs/specs/config-entry-plumbing.md).

The larger setup-flow wizard (SoC reporting mode, temperature parameters,
guardrail defaults, options flow) is queued packet #7 and not built here.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DEFAULT_MARGIN_S, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        # Profile identity (ADR-0007: a profile belongs to one
        # charger+battery+meter configuration).
        vol.Required("charger_label", default="charger"): str,
        vol.Required("battery_label", default="battery"): str,
        vol.Required("meter_id", default="meter"): str,
        vol.Optional("rated_capacity_wh"): vol.Coerce(float),
        # Operational inputs (F1): the watcher's power source and controlled relay.
        vol.Required("power_entity_id"): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="power")
        ),
        vol.Required("plug_entity_id"): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="switch")
        ),
        vol.Optional("temp_entity_id"): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="sensor", device_class="temperature"
            )
        ),
        # Coarse target SoC (invariant 6 / ADR-0004: stored as 0-5 dots, not a
        # silently-precise percentage).
        vol.Optional("target_soc_dots"): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=5, step=1, mode=selector.NumberSelectorMode.SLIDER
            )
        ),
        # Scheduling safety margin (ADR-0012 C); defaults to the watcher's own.
        vol.Optional(
            "margin_s", default=int(DEFAULT_MARGIN_S)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=7200, step=60, mode=selector.NumberSelectorMode.BOX
            )
        ),
    }
)


class CyclestewardConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for CycleSteward."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["charger_label"], data=user_input
            )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA
        )
