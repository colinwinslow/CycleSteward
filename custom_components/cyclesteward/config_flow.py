"""Config flow for CycleSteward.

Minimal stub — the full setup-flow wizard (entity selection, SoC reporting
mode, temperature parameters, guardrail defaults) is implemented in the
setup-flow slice.  This stub creates a config entry so the integration can be
loaded for development and testing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("charger_label", default="charger"): str,
        vol.Required("battery_label", default="battery"): str,
        vol.Required("meter_id", default="meter"): str,
        vol.Optional("rated_capacity_wh"): vol.Coerce(float),
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
