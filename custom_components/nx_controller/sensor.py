from __future__ import annotations

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

from .const import DOMAIN


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
    device_entities = [
        NxControllerDeviceSensor(
            entry, coordinator, mac, coordinator.data.get("devices", {}).get(mac, {})
        )
        for mac in coordinator.data.get("devices", {})
    ]

    known_macs = set(mac for mac in coordinator.data.get("devices", {}))

    async def _async_handle_coordinator_update() -> None:
        new_devices = coordinator.data.get("devices", {})
        new_macs = set(new_devices) - known_macs
        if new_macs:
            entities = [
                NxControllerDeviceSensor(
                    entry,
                    coordinator,
                    mac,
                    new_devices.get(mac, {}),
                )
                for mac in new_macs
            ]
            known_macs.update(new_macs)
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
        mac_addresses = device_data.get("mac_addresses") or []
        primary_mac = device_data.get("primary_mac") or (
            mac_addresses[0] if mac_addresses else None
        )
        self._primary_mac = (primary_mac or "").lower()
        self._attr_unique_id = self._primary_mac
        self._attr_device_info = _device_info(entry)

    @property
    def name(self) -> str:
        device = self.coordinator.data.get("devices", {}).get(self._device_key, {})
        mac_addresses = device.get("mac_addresses") or [self._primary_mac]
        primary_mac = mac_addresses[0]
        host = device.get("host")
        ipv4_addresses = device.get("ipv4_addresses") or []
        ipv6_addresses = device.get("ipv6_addresses") or []
        dhcp_hosts = self.coordinator.data.get("dhcp", {}).get("hosts") or {}
        dhcp_ip_map = {
            info.get("ip"): info.get("name")
            for info in dhcp_hosts.values()
            if info.get("ip") and info.get("name")
        }

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
        attributes = {
            "interfaces": device.get("interfaces", []),
            "radios": device.get("radios", []),
            "ipv4_addresses": device.get("ipv4_addresses", []),
            "ipv6_addresses": device.get("ipv6_addresses", []),
            "hostname": device.get("name"),
            "connections": device.get("connections", []),
        }

        return attributes

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._entry.add_update_listener(self._async_handle_update)
        )

    async def _async_handle_update(self, entry: ConfigEntry) -> None:
        self._attr_device_info = _device_info(entry)
        self.async_write_ha_state()
