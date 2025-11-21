from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    OpenWrtAuthError,
    OpenWrtClient,
    OpenWrtConnectionError,
    SSHAccessPointClient,
    DEFAULT_SSH_COMMAND,
)
from .const import (
    CONF_UPDATE_INTERVAL,
    CONF_SOURCES,
    CONF_SOURCE_NAME,
    CONF_SOURCE_TYPE,
    CONF_PORT,
    CONF_SSH_COMMAND,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SOURCE_TYPE_OPENWRT,
    SOURCE_TYPE_SSH,
)


class OpenWrtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenWrt."""

    VERSION = 1

    def __init__(self) -> None:
        self._sources: list[dict[str, Any]] = []
        self._update_interval: int = int(DEFAULT_SCAN_INTERVAL.total_seconds())
        self._primary_host: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OpenWrtOptionsFlow(config_entry)

    async def async_step_user(self, user_input: Mapping[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            source_type = user_input.get(CONF_SOURCE_TYPE, SOURCE_TYPE_OPENWRT)

            client: OpenWrtClient | SSHAccessPointClient
            if source_type == SOURCE_TYPE_OPENWRT:
                use_ssl = user_input.get(CONF_USE_SSL, True)
                verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

                client = OpenWrtClient(
                    host=user_input[CONF_HOST],
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    use_ssl=use_ssl,
                    verify_ssl=verify_ssl,
                    session=async_get_clientsession(
                        self.hass, verify_ssl=verify_ssl
                    ),
                )
            else:
                client = SSHAccessPointClient(
                    host=user_input[CONF_HOST],
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    port=user_input.get(CONF_PORT, 22),
                    command=user_input.get(CONF_SSH_COMMAND, DEFAULT_SSH_COMMAND),
                )

            try:
                await client.async_validate()
            except OpenWrtAuthError:
                errors["base"] = "invalid_auth"
            except OpenWrtConnectionError:
                errors["base"] = "cannot_connect"

            if not errors:
                if self._primary_host is None:
                    self._primary_host = user_input[CONF_HOST]
                    await self.async_set_unique_id(self._primary_host)
                    self._abort_if_unique_id_configured()

                source_name = user_input.get(CONF_SOURCE_NAME) or user_input[CONF_HOST]

                source: dict[str, Any] = {
                    CONF_SOURCE_TYPE: source_type,
                    CONF_SOURCE_NAME: source_name,
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }

                if source_type == SOURCE_TYPE_OPENWRT:
                    source[CONF_USE_SSL] = user_input.get(CONF_USE_SSL, True)
                    source[CONF_VERIFY_SSL] = user_input.get(CONF_VERIFY_SSL, True)
                else:
                    source[CONF_PORT] = user_input.get(CONF_PORT, 22)
                    source[CONF_SSH_COMMAND] = user_input.get(
                        CONF_SSH_COMMAND, DEFAULT_SSH_COMMAND
                    )

                self._sources.append(source)

                self._update_interval = user_input.get(
                    CONF_UPDATE_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
                )

                return await self.async_step_add_source_prompt()

        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_TYPE, default=SOURCE_TYPE_OPENWRT): vol.In(
                    [SOURCE_TYPE_OPENWRT, SOURCE_TYPE_SSH]
                ),
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_SOURCE_NAME): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_USE_SSL, default=True): bool,
                vol.Optional(CONF_VERIFY_SSL, default=True): bool,
                vol.Optional(CONF_PORT, default=22): int,
                vol.Optional(CONF_SSH_COMMAND, default=DEFAULT_SSH_COMMAND): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=int(DEFAULT_SCAN_INTERVAL.total_seconds())
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=300,
                        step=5,
                        unit="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_add_source_prompt(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            if user_input.get("add_more"):
                return await self.async_step_add_source()
            return self._create_entry()

        return self.async_show_form(
            step_id="add_source_prompt",
            data_schema=vol.Schema({vol.Required("add_more", default=False): bool}),
        )

    async def async_step_add_source(
        self, user_input: Mapping[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            source_type = user_input.get(CONF_SOURCE_TYPE, SOURCE_TYPE_OPENWRT)

            client: OpenWrtClient | SSHAccessPointClient
            if source_type == SOURCE_TYPE_OPENWRT:
                use_ssl = user_input.get(CONF_USE_SSL, True)
                verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

                client = OpenWrtClient(
                    host=user_input[CONF_HOST],
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    use_ssl=use_ssl,
                    verify_ssl=verify_ssl,
                    session=async_get_clientsession(
                        self.hass, verify_ssl=verify_ssl
                    ),
                )
            else:
                client = SSHAccessPointClient(
                    host=user_input[CONF_HOST],
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    port=user_input.get(CONF_PORT, 22),
                    command=user_input.get(CONF_SSH_COMMAND, DEFAULT_SSH_COMMAND),
                )

            try:
                await client.async_validate()
            except OpenWrtAuthError:
                errors["base"] = "invalid_auth"
            except OpenWrtConnectionError:
                errors["base"] = "cannot_connect"

            if not errors:
                source_name = user_input.get(CONF_SOURCE_NAME) or user_input[CONF_HOST]
                source: dict[str, Any] = {
                    CONF_SOURCE_TYPE: source_type,
                    CONF_SOURCE_NAME: source_name,
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }

                if source_type == SOURCE_TYPE_OPENWRT:
                    source[CONF_USE_SSL] = user_input.get(CONF_USE_SSL, True)
                    source[CONF_VERIFY_SSL] = user_input.get(CONF_VERIFY_SSL, True)
                else:
                    source[CONF_PORT] = user_input.get(CONF_PORT, 22)
                    source[CONF_SSH_COMMAND] = user_input.get(
                        CONF_SSH_COMMAND, DEFAULT_SSH_COMMAND
                    )

                self._sources.append(source)

                return await self.async_step_add_source_prompt()

        schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_TYPE, default=SOURCE_TYPE_OPENWRT): vol.In(
                    [SOURCE_TYPE_OPENWRT, SOURCE_TYPE_SSH]
                ),
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_SOURCE_NAME): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_USE_SSL, default=True): bool,
                vol.Optional(CONF_VERIFY_SSL, default=True): bool,
                vol.Optional(CONF_PORT, default=22): int,
                vol.Optional(CONF_SSH_COMMAND, default=DEFAULT_SSH_COMMAND): str,
            }
        )

        return self.async_show_form(
            step_id="add_source", data_schema=schema, errors=errors
        )

    def _create_entry(self) -> FlowResult:
        return self.async_create_entry(
            title=self._primary_host or "OpenWrt",
            data={CONF_SOURCES: self._sources},
            options={CONF_UPDATE_INTERVAL: self._update_interval},
        )


class OpenWrtOptionsFlow(config_entries.OptionsFlow):
    """Handle OpenWrt options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: Mapping[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_UPDATE_INTERVAL, int(DEFAULT_SCAN_INTERVAL.total_seconds())
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10,
                        max=300,
                        step=5,
                        unit="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                )
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
