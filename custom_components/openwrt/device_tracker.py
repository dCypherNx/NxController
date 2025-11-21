from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.components.device_tracker.const import SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DATA_COORDINATOR, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up OpenWrt device trackers."""

    coordinator: DataUpdateCoordinator[list[dict[str, Any]]] = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]

    tracked: dict[str, OpenWrtDeviceTracker] = {}

    def _handle_coordinator_update() -> None:
        new_entities: list[OpenWrtDeviceTracker] = []
        for device in coordinator.data or []:
            mac = device.get("mac")
            if not mac:
                continue
            if mac not in tracked:
                entity = OpenWrtDeviceTracker(coordinator, entry, mac)
                tracked[mac] = entity
                new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    _handle_coordinator_update()
    entry.async_on_unload(coordinator.async_add_listener(_handle_coordinator_update))


class OpenWrtDeviceTracker(CoordinatorEntity[DataUpdateCoordinator[list[dict[str, Any]]]], TrackerEntity):
    """Representation of an OpenWrt tracked device."""

    _attr_source_type = SourceType.ROUTER

    def __init__(
        self, coordinator: DataUpdateCoordinator[list[dict[str, Any]]], entry: ConfigEntry, mac: str
    ) -> None:
        super().__init__(coordinator)
        self._mac = mac
        self._attr_unique_id = f"openwrt-{entry.entry_id}-{mac}"
        self._entry = entry

    @property
    def available(self) -> bool:
        device = self._device
        return device is not None and device.get("connected", True)

    @property
    def name(self) -> str | None:
        if self._device and (hostname := self._device.get("hostname")):
            return hostname
        return self._mac

    @property
    def ip_address(self) -> str | None:
        if self._device:
            return self._device.get("ip_address")
        return None

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._mac)},
            name=self._device.get("hostname") if self._device else self._mac,
            manufacturer="OpenWrt",
            via_device=(DOMAIN, self._entry.entry_id),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self._device:
            return {}
        attributes = dict(self._device.get("attributes", {}))
        if sources := self._device.get("sources"):
            attributes["sources"] = sources
        if hostname := self._device.get("hostname"):
            attributes.setdefault("hostname", hostname)
        if ip_address := self._device.get("ip_address"):
            attributes.setdefault("ip_address", ip_address)
        return attributes

    @property
    def _device(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        for device in self.coordinator.data:
            if device.get("mac") == self._mac:
                return device
        return None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
