from __future__ import annotations

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_USERNAME

from .api import NxSSHClient, NxSSHError
from .const import CONF_SSH_PASSWORD, CONF_SSH_USERNAME, DOMAIN


class NxControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Nx Controller config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            alias = str(user_input[CONF_NAME]).strip()
            host = str(user_input[CONF_HOST]).strip()
            username = str(user_input[CONF_USERNAME]).strip()
            password = str(user_input[CONF_PASSWORD])
            client = NxSSHClient(host, username, password)

            try:
                await client.fetch_interface_devices()
            except NxSSHError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=alias,
                    data={
                        CONF_NAME: alias,
                        CONF_HOST: host,
                        CONF_SSH_USERNAME: username,
                        CONF_SSH_PASSWORD: password,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): cv.string,
                    vol.Required(CONF_HOST): cv.string,
                    vol.Required(CONF_USERNAME): cv.string,
                    vol.Required(CONF_PASSWORD): cv.string,
                }
            ),
            errors=errors,
        )
