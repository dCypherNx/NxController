from __future__ import annotations

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant import config_entries
from homeassistant.const import CONF_HOST

from .const import DOMAIN


class NxControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Nx Controller config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=host, data={CONF_HOST: host})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): cv.string}),
        )
