from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN


def _device_info(entry: ConfigEntry) -> dict:
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

    host = hass.data[DOMAIN][entry.entry_id]["host"]
    async_add_entities([NxControllerRouterSensor(entry, host)])


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
