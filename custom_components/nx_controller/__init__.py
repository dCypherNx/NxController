from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NxSSHClient, NxSSHError, apply_dhcp_fallbacks
from .const import (
    CONF_IS_DHCP_PROVIDER,
    CONF_SSH_PASSWORD,
    CONF_SSH_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nx Controller from a config entry."""

    host = entry.data[CONF_HOST]
    username = entry.data[CONF_SSH_USERNAME]
    password = entry.data[CONF_SSH_PASSWORD]
    is_dhcp_provider = entry.data.get(CONF_IS_DHCP_PROVIDER, False)

    client = NxSSHClient(host, username, password)

    async def _async_update_data():
        try:
            data = await client.fetch_interface_devices(collect_dhcp=is_dhcp_provider)
        except NxSSHError as err:
            raise UpdateFailed(f"Failed to refresh Nx Controller data: {err}") from err

        if not is_dhcp_provider:
            provider_data = _find_dhcp_data(hass, entry.entry_id)
            if provider_data:
                data["dhcp"] = provider_data
                apply_dhcp_fallbacks(data.get("devices", {}), provider_data)

        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Nx Controller data",
        update_method=_async_update_data,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "host": host,
        "coordinator": coordinator,
        "is_dhcp_provider": is_dhcp_provider,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Nx Controller config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok


def _find_dhcp_data(hass: HomeAssistant, current_entry_id: str) -> dict | None:
    """Return DHCP data from the entry flagged as provider."""

    for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
        if entry_id == current_entry_id:
            continue

        if not entry_data.get("is_dhcp_provider"):
            continue

        coordinator = entry_data.get("coordinator")
        if coordinator and coordinator.data:
            return coordinator.data.get("dhcp")

    return None
