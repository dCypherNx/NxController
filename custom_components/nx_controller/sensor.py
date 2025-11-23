"""Sensor platform for NxController."""
from __future__ import annotations

from typing import Any, Dict, List

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import NxControllerCoordinator, NxClient


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: NxControllerCoordinator = data["coordinator"]

    tracked: Dict[str, NxControllerSensor] = {}

    @callback
    def _update_entities() -> None:
        if not coordinator.data:
            return
        new_entities: List[NxControllerSensor] = []
        for primary_mac in coordinator.data:
            if primary_mac in tracked:
                continue
            entity = NxControllerSensor(coordinator, primary_mac)
            tracked[primary_mac] = entity
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    _update_entities()
    coordinator.async_add_listener(_update_entities)


class NxControllerSensor(CoordinatorEntity[NxControllerCoordinator], SensorEntity):
    """Sensor representing a network client."""

    _attr_should_poll = False
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator: NxControllerCoordinator, primary_mac: str) -> None:
        super().__init__(coordinator)
        self._primary_mac = primary_mac
        self._alias = coordinator.alias
        self._attr_unique_id = f"{self._alias}_{primary_mac.replace(':', '')}"

    @property
    def _client(self) -> NxClient:
        return self.coordinator.data[self._primary_mac]

    @property
    def name(self) -> str:
        return f"{self._alias}_{self._primary_mac.replace(':', '_')}"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return "online" if self._client.online else "offline"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        client = self._client
        hostname = client.hostname or f"Desconhecido ({client.primary_mac})"
        return {
            ATTR_FRIENDLY_NAME: hostname,
            "mac_address": client.primary_mac,
            "ipv4": client.ipv4,
            "ipv6": client.ipv6,
            "hostname": client.hostname,
            "interface": client.interface,
            "connection_type": client.connection_type,
            "rx_bytes": client.rx_bytes,
            "tx_bytes": client.tx_bytes,
            "signal_dbm": client.signal_dbm,
            "last_seen": client.last_seen,
            "router_alias": self._alias,
            "dhcp_source": client.dhcp_source,
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, f"router_{self._alias}")},
            name=self._alias,
            manufacturer="OpenWrt",
            model="NxController",
        )
