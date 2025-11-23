"""Config flow for NxController."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ALIAS,
    CONF_HOST,
    CONF_IS_DHCP_SERVER,
    DEFAULT_PORT,
    DOMAIN,
)
from .ssh_client import NxSSHClient, NxSSHError


class NxControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NxController."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        errors = {}
        if user_input is not None:
            alias = user_input[CONF_ALIAS]
            existing = {
                entry.data.get(CONF_ALIAS)
                for entry in self._async_current_entries()
            }
            if alias in existing:
                errors["base"] = "alias_exists"
            else:
                try:
                    client = NxSSHClient(
                        user_input[CONF_HOST],
                        user_input.get(CONF_PORT, DEFAULT_PORT),
                        user_input[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                    )
                    await client.async_run_command("echo NxController")
                except NxSSHError:
                    errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(title=alias, data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ALIAS): str,
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_IS_DHCP_SERVER, default=True): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @callback
    def async_get_options_flow(self):
        return NxControllerOptionsFlowHandler()


class NxControllerOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow placeholder (not used)."""

    def __init__(self) -> None:
        super().__init__()

    async def async_step_init(self, user_input=None):
        return self.async_create_entry(title="", data={})
