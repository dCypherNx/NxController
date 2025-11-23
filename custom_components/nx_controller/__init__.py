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
from .identity import (
    consolidate_devices,
    _find_primary_mac,
    _load_known_devices,
    _register_secondary_mac,
    _save_known_devices,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Nx Controller from a config entry."""

    host = entry.data[CONF_HOST]
    username = entry.data[CONF_SSH_USERNAME]
    password = entry.data[CONF_SSH_PASSWORD]
    is_dhcp_provider = entry.data.get(CONF_IS_DHCP_PROVIDER, False)

    known_devices = await _load_known_devices(hass, entry.entry_id)

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

        consolidated_devices, dirty = consolidate_devices(
            data.get("devices", {}), known_devices
        )
        data["devices"] = consolidated_devices
        data["pending_macs"] = known_devices.get("pending", [])

        if dirty:
            await _save_known_devices(hass, entry.entry_id, known_devices)

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
        "known_devices": known_devices,
    }

    async def _async_associate_mac(call) -> None:
        primary_mac = call.data.get("primary_mac")
        mac = call.data.get("mac")

        if not primary_mac or not mac:
            _LOGGER.warning("Missing primary_mac or mac in associate_mac call")
            return

        if not _find_primary_mac(primary_mac, known_devices):
            _register_secondary_mac(primary_mac, primary_mac, known_devices)

        if _register_secondary_mac(primary_mac, mac, known_devices):
            await _save_known_devices(hass, entry.entry_id, known_devices)
            await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, f"{entry.entry_id}_associate_mac", _async_associate_mac
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Nx Controller config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.services.async_remove(DOMAIN, f"{entry.entry_id}_associate_mac")
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
