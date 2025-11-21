from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN


def _device_info(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "manufacturer": "Nx Controller",
        "model": "POC",
        "name": entry.title,
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Nx Controller sensor entity from a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    host = data["host"]
    coordinator = data["coordinator"]

    router_sensor = NxControllerRouterSensor(entry, host)
    device_entities = [
        NxControllerDeviceSensor(entry, coordinator, mac)
        for mac in coordinator.data.get("devices", {})
    ]

    known_macs = set(mac for mac in coordinator.data.get("devices", {}))

    async def _async_handle_coordinator_update() -> None:
        new_devices = coordinator.data.get("devices", {})
        new_macs = set(new_devices) - known_macs
        if new_macs:
            entities = [NxControllerDeviceSensor(entry, coordinator, mac) for mac in new_macs]
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

    def __init__(self, entry: ConfigEntry, host: str) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ip"
        self._attr_name = "IP Address"
        self._attr_native_value = host
        self._attr_device_info = _device_info(entry)

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

    def __init__(self, entry: ConfigEntry, coordinator, mac: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._mac = mac
        self._attr_unique_id = f"{entry.entry_id}_{mac}"
        self._attr_name = mac
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self):
        device = self.coordinator.data.get("devices", {}).get(self._mac, {})
        return device.get("state")

    @property
    def extra_state_attributes(self):
        device = self.coordinator.data.get("devices", {}).get(self._mac, {})
        return {
            "interface": device.get("interface"),
            "ip_address": device.get("ip"),
            "mac_address": self._mac,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._entry.add_update_listener(self._async_handle_update)
        )

    async def _async_handle_update(self, entry: ConfigEntry) -> None:
        self._attr_device_info = _device_info(entry)
        self.async_write_ha_state()
