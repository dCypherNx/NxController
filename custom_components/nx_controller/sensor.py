from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry

from .api import _normalize_mac, _resolve_hostname
from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)


def _mac_parts(mac: str | None) -> tuple[str | None, str | None]:
    """Return normalized MAC and mac_id (lowercase, no colons)."""

    normalized = _normalize_mac(mac)
    if not normalized:
        return None, None

    return normalized, normalized.replace(":", "").lower()


def _device_info(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "manufacturer": "Nx Controller",
        "model": "Nx Controller",
        "name": entry.title,
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Nx Controller sensor entity from a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    host = data["host"]
    coordinator = data["coordinator"]

    router_sensor = NxControllerRouterSensor(entry, host, coordinator)
    device_entities: list[NxControllerDeviceSensor] = []
    known_device_keys: set[str] = set()

    for device_key, device_data in (coordinator.data.get("devices") or {}).items():
        sensor = _build_device_sensor(entry, coordinator, device_key, device_data)
        if sensor:
            device_entities.append(sensor)
            known_device_keys.add(device_key)

    async def _async_handle_coordinator_update() -> None:
        new_devices = coordinator.data.get("devices", {})
        new_device_keys = set(new_devices) - known_device_keys
        if new_device_keys:
            entities: list[NxControllerDeviceSensor] = []

            for device_key in new_device_keys:
                sensor = _build_device_sensor(
                    entry, coordinator, device_key, new_devices.get(device_key, {})
                )
                if sensor:
                    known_device_keys.add(device_key)
                    entities.append(sensor)

            if entities:
                async_add_entities(entities)

    coordinator.async_add_listener(_async_handle_coordinator_update)

    async_add_entities([router_sensor, *device_entities])


class NxControllerRouterSensor(SensorEntity):
    """Representation of the configured router or access point."""

    _attr_icon = "mdi:router-network"
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "router_ip"

    def __init__(
        self, entry: ConfigEntry, host: str, coordinator: DataUpdateCoordinator
    ) -> None:
        self._entry = entry
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_ip"
        self._attr_name = "IP Address"
        self._attr_native_value = host
        self._attr_device_info = _device_info(entry)

    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._entry.add_update_listener(self._async_handle_update)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pending_macs = (self._coordinator.data or {}).get("pending_macs") or []
        return {"pending_macs": pending_macs} if pending_macs else {}

    async def _async_handle_update(self, entry: ConfigEntry) -> None:
        host = entry.data[CONF_HOST]
        self.hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})[
            "host"
        ] = host
        self._attr_native_value = host
        self._attr_device_info = _device_info(entry)
        self.async_write_ha_state()


class NxControllerDeviceSensor(CoordinatorEntity, SensorEntity):
    """Representation of a connected device discovered via SSH."""

    _attr_icon = "mdi:lan-connect"
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "connected_device"

    def __init__(
        self,
        entry: ConfigEntry,
        coordinator: DataUpdateCoordinator,
        device_key: str,
        device_data: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_key = device_key
        normalized_mac, mac_id, primary_mac = self._extract_mac_identifiers(
            device_key, device_data
        )

        if not normalized_mac or not mac_id:
            raise ValueError(f"Device {device_key} is missing a valid MAC address")

        self._normalized_mac = normalized_mac
        self._mac_id = mac_id
        self._primary_mac = primary_mac or self._normalized_mac
        self._attr_unique_id = f"er605_{self._mac_id}"
        self._attr_suggested_object_id = self._attr_unique_id
        self._attr_device_info = _device_info(entry)

    @property
    def name(self) -> str:
        device = self.coordinator.data.get("devices", {}).get(self._device_key, {})
        mac_addresses = device.get("mac_addresses") or [self._primary_mac]
        primary_mac = mac_addresses[0]
        host = device.get("host")
        ipv4_addresses = device.get("ipv4_addresses") or []
        ipv6_addresses = device.get("ipv6_addresses") or []
        hostname_sources = self.coordinator.data.get("hostname_sources") or {}
        dhcp_hosts = self.coordinator.data.get("dhcp", {}).get("hosts") or {}
        dhcp_ip_map = {
            info.get("ip"): info.get("name")
            for info in dhcp_hosts.values()
            if info.get("ip") and info.get("name")
        }

        resolved_hostname: str | None = None
        for mac in mac_addresses:
            normalized_mac = _normalize_mac(mac)
            if not normalized_mac:
                continue
            resolved_hostname = _resolve_hostname(
                hostname_sources.get(normalized_mac)
            )
            if resolved_hostname:
                break

        if resolved_hostname:
            return resolved_hostname

        dhcp_name: str | None = None
        if dhcp_hosts:
            for mac in mac_addresses:
                host_info = dhcp_hosts.get(mac.lower())
                if host_info and host_info.get("name"):
                    dhcp_name = host_info["name"]
                    break

        if not dhcp_name and dhcp_ip_map:
            for ip in ipv4_addresses:
                name = dhcp_ip_map.get(ip)
                if name:
                    dhcp_name = name
                    break

        if dhcp_name:
            return dhcp_name

        if device.get("name"):
            return device["name"]

        if primary_mac:
            return primary_mac

        if host:
            return host

        if ipv4_addresses:
            return ipv4_addresses[0]

        if ipv6_addresses:
            return ipv6_addresses[0]

        return self._primary_mac

    @property
    def native_value(self):
        device = self.coordinator.data.get("devices", {}).get(self._device_key, {})
        return device.get("state")

    @property
    def extra_state_attributes(self):
        device = self.coordinator.data.get("devices", {}).get(self._device_key, {})
        ipv4_addresses = device.get("ipv4_addresses", [])
        ipv6_addresses = device.get("ipv6_addresses", [])
        hostname_sources = self.coordinator.data.get("hostname_sources") or {}
        hostname = None
        mac_candidates = device.get("mac_addresses") or [self._primary_mac]
        for mac in mac_candidates:
            normalized_mac = _normalize_mac(mac)
            if not normalized_mac:
                continue
            hostname = _resolve_hostname(hostname_sources.get(normalized_mac))
            if hostname:
                break

        if not hostname:
            hostname = self._fallback_hostname(device)

        return {
            "interfaces": device.get("interfaces", []),
            "radios": device.get("radios", []),
            "ipv4_addresses": ipv4_addresses,
            "ipv6_addresses": ipv6_addresses,
            "mac": self._normalized_mac,
            "hostname": hostname,
        }

    def _fallback_hostname(self, device: dict[str, Any]) -> str | None:
        host = device.get("host")
        name = device.get("name")
        ipv4_addresses = device.get("ipv4_addresses", [])
        ipv6_addresses = device.get("ipv6_addresses", [])

        if name:
            return name

        if host:
            return host

        if ipv4_addresses:
            return ipv4_addresses[0]

        if ipv6_addresses:
            return ipv6_addresses[0]

        return None

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._entry.add_update_listener(self._async_handle_update)
        )

    async def _async_handle_update(self, entry: ConfigEntry) -> None:
        self._attr_device_info = _device_info(entry)
        self.async_write_ha_state()

    @staticmethod
    def _extract_mac_identifiers(
        device_key: str, device_data: dict[str, Any]
    ) -> tuple[str | None, str | None, str | None]:
        mac_addresses = device_data.get("mac_addresses") or []
        primary_mac = device_data.get("primary_mac") or (
            mac_addresses[0] if mac_addresses else None
        )
        candidates = [primary_mac, *mac_addresses, device_key]

        for candidate in candidates:
            normalized, mac_id = _mac_parts(candidate)
            if normalized and mac_id:
                return normalized, mac_id, candidate

        return None, None, primary_mac or device_key


def _build_device_sensor(
    entry: ConfigEntry,
    coordinator: DataUpdateCoordinator,
    device_key: str,
    device_data: dict[str, Any],
) -> NxControllerDeviceSensor | None:
    try:
        return NxControllerDeviceSensor(entry, coordinator, device_key, device_data)
    except ValueError as err:
        _LOGGER.debug("Skipping device %s: %s", device_key, err)
        return None
