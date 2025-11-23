from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    coordinator = data["coordinator"]

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

    async_add_entities(device_entities)


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
        self._mac_object_id = self._normalized_mac.lower().replace(":", "_")
        self._primary_mac = primary_mac or self._normalized_mac
        self._attr_unique_id = f"er605_{self._mac_object_id}"
        self._attr_suggested_object_id = f"er605_{self._mac_object_id}"
        self._attr_device_info = _device_info(entry)

    @property
    def name(self) -> str:
        return self._resolved_hostname() or self._normalized_mac

    @property
    def native_value(self):
        device = self.coordinator.data.get("devices", {}).get(self._device_key, {})
        return device.get("state")

    @property
    def extra_state_attributes(self):
        device = self.coordinator.data.get("devices", {}).get(self._device_key, {})
        ipv4_addresses = device.get("ipv4_addresses", [])
        ipv6_addresses = device.get("ipv6_addresses", [])
        hostname = self._resolved_hostname()

        return {
            "interfaces": device.get("interfaces", []),
            "radios": device.get("radios", []),
            "ipv4_addresses": ipv4_addresses,
            "ipv6_addresses": ipv6_addresses,
            "mac": self._normalized_mac,
            "hostname": hostname,
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._entry.add_update_listener(self._async_handle_update)
        )

    async def _async_handle_update(self, entry: ConfigEntry) -> None:
        self._attr_device_info = _device_info(entry)
        self.async_write_ha_state()

    def _resolved_hostname(self) -> str | None:
        device = self.coordinator.data.get("devices", {}).get(self._device_key, {})
        hostname_sources = self.coordinator.data.get("hostname_sources") or {}
        mac_candidates = device.get("mac_addresses") or [self._primary_mac]

        for mac in mac_candidates:
            normalized_mac = _normalize_mac(mac)
            if not normalized_mac:
                continue

            hostname = _resolve_hostname(hostname_sources.get(normalized_mac))
            if hostname:
                return hostname

        return None

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
