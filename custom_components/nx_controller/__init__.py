from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    OpenWrtAuthError,
    OpenWrtClient,
    OpenWrtError,
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
    DATA_CLIENTS,
    DATA_COORDINATOR,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SOURCE_TYPE_OPENWRT,
    SOURCE_TYPE_SSH,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the Nx Controller integration from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    sources: list[dict[str, str]] = entry.data.get(CONF_SOURCES, [])
    if not sources:
        sources = [
            {
                CONF_SOURCE_TYPE: SOURCE_TYPE_OPENWRT,
                CONF_SOURCE_NAME: entry.data.get(CONF_HOST, "Nx Controller"),
                CONF_HOST: entry.data[CONF_HOST],
                CONF_USERNAME: entry.data[CONF_USERNAME],
                CONF_PASSWORD: entry.data[CONF_PASSWORD],
                CONF_USE_SSL: entry.data.get(CONF_USE_SSL, True),
                CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL, True),
            }
        ]

    client_sources: list[tuple[dict[str, str], OpenWrtClient]] = []
    for source in sources:
        source_type = source.get(CONF_SOURCE_TYPE, SOURCE_TYPE_OPENWRT)
        if source_type == SOURCE_TYPE_OPENWRT:
            use_ssl: bool = source.get(CONF_USE_SSL, True)
            verify_ssl: bool = source.get(CONF_VERIFY_SSL, True)
            session = async_get_clientsession(hass, verify_ssl=verify_ssl)
            client_sources.append(
                (
                    source,
                    OpenWrtClient(
                        host=source[CONF_HOST],
                        username=source[CONF_USERNAME],
                        password=source[CONF_PASSWORD],
                        use_ssl=use_ssl,
                        verify_ssl=verify_ssl,
                        session=session,
                    ),
                )
            )
        elif source_type == SOURCE_TYPE_SSH:
            client_sources.append(
                (
                    source,
                    SSHAccessPointClient(
                        host=source[CONF_HOST],
                        username=source[CONF_USERNAME],
                        password=source[CONF_PASSWORD],
                        port=source.get(CONF_PORT, 22),
                        commands=source.get(CONF_SSH_COMMANDS),
                        command=source.get(CONF_SSH_COMMAND) or None,
                    ),
                )
            )

    update_interval = timedelta(
        seconds=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds())
    )

    async def _async_update_data():
        try:
            device_map: dict[str, dict] = {}
            for source, client in client_sources:
                try:
                    devices = await client.async_get_clients()
                except OpenWrtAuthError as err:
                    _LOGGER.error("OpenWrt authentication failed: %s", err)
                    raise UpdateFailed("authentication_failed") from err
                except OpenWrtError as err:
                    _LOGGER.error("OpenWrt update failed: %s", err)
                    raise UpdateFailed("update_failed") from err

                for device in devices:
                    mac = device.get("mac")
                    if not mac:
                        continue
                    mac = mac.lower()
                    merged = device_map.setdefault(
                        mac,
                        {
                            "mac": mac,
                            "hostname": device.get("hostname"),
                            "ip_address": device.get("ip_address"),
                            "interface": device.get("interface"),
                            "connected": device.get("connected"),
                            "attributes": {},
                            "sources": [],
                        },
                    )

                    merged["sources"].append(
                        source.get(CONF_SOURCE_NAME, "Nx Controller")
                    )
                    if hostname := device.get("hostname"):
                        merged["hostname"] = hostname
                    if ip_address := device.get("ip_address"):
                        merged["ip_address"] = ip_address
                    if interface := device.get("interface"):
                        merged["interface"] = interface
                    if "connected" in device:
                        merged["connected"] = device.get("connected") or merged.get(
                            "connected"
                        )
                    merged["attributes"].update(device.get("attributes", {}))

            return list(device_map.values())
        except OpenWrtAuthError as err:
            raise UpdateFailed("authentication_failed") from err
        except OpenWrtError as err:
            raise UpdateFailed("update_failed") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Nx Controller devices",
        update_method=_async_update_data,
        update_interval=update_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENTS: [client for _, client in client_sources],
        DATA_COORDINATOR: coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entry versions."""

    version = entry.version

    if version > 1:
        return True

    data: dict[str, Any] = {**entry.data}

    if version == 1:
        normalized_sources: list[dict[str, Any]] = []
        if sources := data.get(CONF_SOURCES):
            for source in sources:
                normalized_sources.append(_normalize_source(source))
        else:
            normalized_sources.append(
                _normalize_source(
                    {
                        CONF_SOURCE_TYPE: SOURCE_TYPE_OPENWRT,
                        CONF_SOURCE_NAME: data.get(CONF_SOURCE_NAME)
                        or data.get(CONF_HOST, "Nx Controller"),
                        CONF_HOST: data.get(CONF_HOST, ""),
                        CONF_USERNAME: data.get(CONF_USERNAME, ""),
                        CONF_PASSWORD: data.get(CONF_PASSWORD, ""),
                        CONF_USE_SSL: data.get(CONF_USE_SSL, True),
                        CONF_VERIFY_SSL: data.get(CONF_VERIFY_SSL, True),
                    }
                )
            )

        data[CONF_SOURCES] = normalized_sources

        hass.config_entries.async_update_entry(
            entry,
            data=data,
            unique_id=_normalize_host(entry.unique_id) if entry.unique_id else None,
        )
        entry.version = 2

    return True


def _normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    """Normalize host-related fields for a source definition."""

    cleaned_source = {**source}
    if host := source.get(CONF_HOST):
        cleaned_source[CONF_HOST] = _normalize_host(host)
    return cleaned_source


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Nx Controller config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator: DataUpdateCoordinator = entry_data[DATA_COORDINATOR]
        coordinator.async_cancel()

    return unload_ok
