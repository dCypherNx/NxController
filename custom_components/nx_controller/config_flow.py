from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    DEFAULT_SSH_COMMAND,
    DEFAULT_SSH_COMMANDS,
    OpenWrtAuthError,
    OpenWrtClient,
    OpenWrtConnectionError,
    SSHAccessPointClient,
    _normalize_host,
)
from .const import (
    CONF_UPDATE_INTERVAL,
    CONF_SOURCES,
    CONF_SOURCE_NAME,
    CONF_SOURCE_TYPE,
    CONF_PORT,
    CONF_SSH_COMMAND,
    CONF_SSH_COMMANDS,
    CONF_USE_SSL,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    SOURCE_TYPE_OPENWRT,
    SOURCE_TYPE_SSH,
)


_LOGGER = logging.getLogger(__name__)


class OpenWrtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Nx Controller config flow."""

    VERSION = 2

    def __init__(self) -> None:
        self._sources: list[dict[str, Any]] = []
        self._update_interval: int = int(DEFAULT_SCAN_INTERVAL.total_seconds())
        self._primary_host: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return OpenWrtOptionsFlow(config_entry)

    async def async_step_user(self, user_input: Mapping[str, Any] | None = None) -> FlowResult:
        return await self._process_source_step(
            step_id="user", include_update_interval=True, user_input=user_input
        )

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
        return await self._process_source_step(
            step_id="add_source", include_update_interval=False, user_input=user_input
        )

    def _create_entry(self) -> FlowResult:
        return self.async_create_entry(
            title=self._primary_host or "Nx Controller",
            data={CONF_SOURCES: self._sources},
            options={CONF_UPDATE_INTERVAL: self._update_interval},
        )

    async def _process_source_step(
        self,
        *,
        step_id: str,
        include_update_interval: bool,
        user_input: Mapping[str, Any] | None,
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            source_type = user_input.get(CONF_SOURCE_TYPE, SOURCE_TYPE_OPENWRT)
            cleaned_host = _normalize_host(user_input[CONF_HOST])

            _LOGGER.debug(
                "Config flow step %s: validating source type=%s host=%s name=%s",
                step_id,
                source_type,
                cleaned_host,
                user_input.get(CONF_SOURCE_NAME),
            )

            client = self._build_client(cleaned_host, source_type, user_input)

            try:
                await client.async_validate()
            except OpenWrtAuthError:
                _LOGGER.warning(
                    "Authentication failed during validation for host %s (%s)",
                    cleaned_host,
                    source_type,
                )
                errors["base"] = "invalid_auth"
            except OpenWrtConnectionError:
                _LOGGER.warning(
                    "Connection failed during validation for host %s (%s)",
                    cleaned_host,
                    source_type,
                )
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception(
                    "Unexpected error validating source %s (%s)",
                    cleaned_host,
                    source_type,
                )
                errors["base"] = "unknown"

            if not errors:
                await self._ensure_unique_primary(cleaned_host)

                source_name = user_input.get(CONF_SOURCE_NAME) or cleaned_host
                source = self._build_source_payload(
                    source_type, source_name, cleaned_host, user_input
                )

                if include_update_interval:
                    self._update_interval = user_input.get(
                        CONF_UPDATE_INTERVAL, self._default_update_interval
                    )

                self._sources.append(source)

                _LOGGER.debug(
                    "Config flow step %s: added source %s (%s); total sources=%d",
                    step_id,
                    source_name,
                    source_type,
                    len(self._sources),
                )

                return await self.async_step_add_source_prompt()

        return self.async_show_form(
            step_id=step_id,
            data_schema=self._build_source_schema(include_update_interval),
            errors=errors,
        )

    def _build_client(
        self,
        cleaned_host: str,
        source_type: str,
        user_input: Mapping[str, Any],
    ) -> OpenWrtClient | SSHAccessPointClient:
        if source_type == SOURCE_TYPE_OPENWRT:
            use_ssl = user_input.get(CONF_USE_SSL, True)
            verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

            return OpenWrtClient(
                host=cleaned_host,
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                use_ssl=use_ssl,
                verify_ssl=verify_ssl,
                session=async_get_clientsession(self.hass, verify_ssl=verify_ssl),
            )

        return SSHAccessPointClient(
            host=cleaned_host,
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
            port=user_input.get(CONF_PORT, 22),
            command=user_input.get(CONF_SSH_COMMAND, DEFAULT_SSH_COMMAND),
            commands=_parse_command_list(user_input.get(CONF_SSH_COMMANDS)),
        )

    def _build_source_payload(
        self,
        source_type: str,
        source_name: str,
        cleaned_host: str,
        user_input: Mapping[str, Any],
    ) -> dict[str, Any]:
        source: dict[str, Any] = {
            CONF_SOURCE_TYPE: source_type,
            CONF_SOURCE_NAME: source_name,
            CONF_HOST: cleaned_host,
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
            source[CONF_SSH_COMMANDS] = _parse_command_list(
                user_input.get(CONF_SSH_COMMANDS)
            )

        return source

    async def _ensure_unique_primary(self, cleaned_host: str) -> None:
        if self._primary_host is not None:
            return

        self._primary_host = cleaned_host
        await self.async_set_unique_id(self._primary_host)
        self._abort_if_unique_id_configured()

    @property
    def _default_update_interval(self) -> int:
        return int(DEFAULT_SCAN_INTERVAL.total_seconds())

    def _build_source_schema(self, include_update_interval: bool) -> vol.Schema:
        schema: dict[Any, Any] = {
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
            vol.Optional(CONF_SSH_COMMANDS, default="\n".join(DEFAULT_SSH_COMMANDS)):
                selector.TextSelector(
                    selector.TextSelectorConfig(
                        multiline=True, type=selector.TextSelectorType.TEXT
                    )
                ),
        }

        if include_update_interval:
            schema[
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=self._update_interval
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=10,
                    max=300,
                    step=5,
                    unit="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            )

        return vol.Schema(schema)


class OpenWrtOptionsFlow(config_entries.OptionsFlow):
    """Handle Nx Controller options."""

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


def _parse_command_list(raw_value: str | None) -> list[str]:
    """Parse user-provided commands separated by newlines/commas/semicolons."""

    if not raw_value:
        return []

    split_values = re.split(r"[\n;,]+", raw_value)
    return [command.strip() for command in split_values if command.strip()]
