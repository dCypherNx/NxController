"""NxController integration entry point."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Set

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ALIAS,
    CONF_HOST,
    CONF_IS_DHCP_SERVER,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    EVENT_NEW_MAC_DETECTED,
    SERVICE_MAP_MAC,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .ssh_client import (
    NxSSHClient,
    NxSSHError,
    normalize_mac,
    utcnow_iso,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class NxClient:
    """Normalized representation of a network client."""

    primary_mac: str
    alias: str
    macs: Set[str] = field(default_factory=set)
    hostname: Optional[str] = None
    ipv4: Optional[str] = None
    ipv6: Optional[str] = None
    interface: Optional[str] = None
    connection_type: Optional[str] = None
    rx_bytes: Optional[int] = None
    tx_bytes: Optional[int] = None
    signal_dbm: Optional[int] = None
    last_seen: Optional[str] = None
    dhcp_source: Optional[str] = None
    online: bool = False


class DeviceRegistry:
    """Persistence for mapping dynamic MACs to primary MACs."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.devices: Dict[str, Dict[str, object]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.devices = data.get("devices", {})

    async def async_save(self) -> None:
        await self._store.async_save({"version": STORAGE_VERSION, "devices": self.devices})

    def _normalize_hostname(self, hostname: Optional[str]) -> Optional[str]:
        if not hostname:
            return None
        normalized = hostname.strip()
        return normalized.lower() or None

    def get_primary_for_mac(self, alias: str, mac: str) -> Optional[str]:
        for primary, info in self.devices.items():
            if info.get("alias") != alias:
                continue
            if mac in info.get("macs", []):
                return primary
        return None

    def _update_metadata(self, info: Dict[str, object], hostname: Optional[str], ipv4: Optional[str]) -> None:
        metadata: Dict[str, object] = info.setdefault("metadata", {})  # type: ignore[arg-type]
        normalized_hostname = self._normalize_hostname(hostname)
        if normalized_hostname:
            metadata["hostname"] = normalized_hostname
        if ipv4:
            metadata["ipv4"] = ipv4

    def ensure_device(self, alias: str, mac: str, hostname: Optional[str], ipv4: Optional[str]) -> str:
        existing = self.get_primary_for_mac(alias, mac)
        if existing:
            return existing
        self.devices[mac] = {"alias": alias, "macs": [mac], "metadata": {}}
        self._update_metadata(self.devices[mac], hostname, ipv4)
        return mac

    def add_mac(self, alias: str, primary_mac: str, alt_mac: str) -> None:
        primary = self.devices.get(primary_mac)
        if not primary:
            raise ValueError("Primary MAC not found")
        if primary.get("alias") != alias:
            raise ValueError("Alias mismatch for primary device")
        alt_primary = self.get_primary_for_mac(alias, alt_mac)
        if alt_primary and alt_primary != primary_mac:
            alt_info = self.devices.pop(alt_primary)
            for mac in alt_info.get("macs", []):
                if mac not in primary["macs"]:
                    primary["macs"].append(mac)
            self._update_metadata(
                primary,
                alt_info.get("metadata", {}).get("hostname"),
                alt_info.get("metadata", {}).get("ipv4"),
            )
        if alt_mac not in primary["macs"]:
            primary["macs"].append(alt_mac)

    def find_by_identity(self, alias: str, hostname: Optional[str], ipv4: Optional[str]) -> Optional[str]:
        """Find primary device matching hostname and IPv4 rules."""

        if not hostname and not ipv4:
            return None

        target_hostname = self._normalize_hostname(hostname)

        for primary, info in self.devices.items():
            if info.get("alias") != alias:
                continue
            metadata: Dict[str, object] = info.get("metadata", {})  # type: ignore[arg-type]
            stored_hostname = self._normalize_hostname(metadata.get("hostname"))
            stored_ipv4 = metadata.get("ipv4")

            if target_hostname:
                if stored_hostname and stored_hostname != target_hostname:
                    continue
                if ipv4:
                    if stored_ipv4 and stored_ipv4 != ipv4:
                        continue
                    return primary
            if not target_hostname and ipv4:
                if stored_hostname:
                    continue
                if stored_ipv4 == ipv4:
                    return primary
        return None

    def map_mac(
        self, alias: str, mac: str, hostname: Optional[str], ipv4: Optional[str]
    ) -> tuple[str, bool]:
        """Map a MAC to a primary device using hostname/IP association rules."""

        existing_primary = self.get_primary_for_mac(alias, mac)
        if existing_primary:
            self._update_metadata(self.devices[existing_primary], hostname, ipv4)
            return existing_primary, False

        identity_primary = self.find_by_identity(alias, hostname, ipv4)
        if identity_primary:
            self.add_mac(alias, identity_primary, mac)
            self._update_metadata(self.devices[identity_primary], hostname, ipv4)
            return identity_primary, True

        primary = self.ensure_device(alias, mac, hostname, ipv4)
        return primary, True


class NxControllerCoordinator(DataUpdateCoordinator[Dict[str, NxClient]]):
    """Data update coordinator for NxController."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, registry: DeviceRegistry) -> None:
        self.entry = entry
        self.registry = registry
        self.alias = entry.data[CONF_ALIAS]
        self.is_dhcp_server = entry.data.get(CONF_IS_DHCP_SERVER, False)
        self.client = NxSSHClient(
            entry.data[CONF_HOST],
            entry.data.get(CONF_PORT, DEFAULT_PORT),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{self.alias}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> Dict[str, NxClient]:
        previous_clients: Dict[str, NxClient] = self.data or {}
        clients: Dict[str, NxClient] = {}
        try:
            hosts = await self.client.async_get_dhcp_hosts() if self.is_dhcp_server else []
            dhcp_v4 = await self.client.async_get_dhcp_leases() if self.is_dhcp_server else []
            dhcp_v6 = await self.client.async_get_odhcpd_leases() if self.is_dhcp_server else []
            neighbors = await self.client.async_get_neighbors()
            wifi_interfaces = await self.client.async_get_wifi_interfaces()
            wifi_clients: List[dict] = []
            for iface in wifi_interfaces:
                assoc = await self.client.async_get_wifi_clients(iface)
                for item in assoc:
                    wifi_clients.append({"mac": item.mac, "interface": item.interface, "signal": item.signal_dbm})
        except NxSSHError as err:
            raise UpdateFailed(str(err)) from err

        def register_client(mac: str, data: dict) -> None:
            normalized_mac = normalize_mac(mac)
            if not normalized_mac:
                return

            hostname: Optional[str] = (data.get("hostname") or "").strip() or None
            ipv4: Optional[str] = data.get("ipv4") or data.get("ip")

            primary, is_new = self.registry.map_mac(self.alias, normalized_mac, hostname, ipv4)

            client = clients.get(primary)
            if not client:
                if previous := previous_clients.get(primary):
                    client = replace(previous)
                    client.macs = set(previous.macs)
                else:
                    client = NxClient(primary_mac=primary, alias=self.alias, macs=set())
                clients[primary] = client
            client.macs.add(normalized_mac)
            if hostname:
                client.hostname = hostname
            if ipv4:
                client.ipv4 = ipv4
            ipv6 = data.get("ipv6")
            if ipv6:
                client.ipv6 = ipv6
            if data.get("interface"):
                client.interface = data.get("interface")
            if data.get("connection_type"):
                client.connection_type = data.get("connection_type")
            if data.get("rx_bytes") is not None:
                client.rx_bytes = data.get("rx_bytes")
            if data.get("tx_bytes") is not None:
                client.tx_bytes = data.get("tx_bytes")
            if data.get("signal_dbm") is not None:
                client.signal_dbm = data.get("signal_dbm")
            if data.get("dhcp_source"):
                client.dhcp_source = data.get("dhcp_source")
            if data.get("online") is not None:
                client.online = data.get("online")
            if data.get("last_seen"):
                client.last_seen = data.get("last_seen")
            if is_new:
                self.hass.bus.async_fire(
                    EVENT_NEW_MAC_DETECTED,
                    {
                        "alias": self.alias,
                        "mac": normalized_mac,
                        "ipv4": client.ipv4,
                        "ipv6": client.ipv6,
                        "hostname": client.hostname,
                        "connection_type": client.connection_type,
                    },
                )

        for entry in hosts:
            register_client(
                entry["mac"],
                {
                    "hostname": entry.get("hostname"),
                    "ipv4": entry.get("ip"),
                    "dhcp_source": entry.get("source"),
                    "online": False,
                    "last_seen": utcnow_iso(),
                },
            )

        for lease in dhcp_v4:
            register_client(
                lease["mac"],
                {
                    "hostname": lease.get("hostname"),
                    "ipv4": lease.get("ip"),
                    "dhcp_source": lease.get("source"),
                    "online": False,
                    "last_seen": utcnow_iso(),
                },
            )

        for lease in dhcp_v6:
            register_client(
                lease["mac"],
                {
                    "hostname": lease.get("hostname"),
                    "ipv6": lease.get("ipv6"),
                    "dhcp_source": lease.get("source"),
                    "online": False,
                    "last_seen": utcnow_iso(),
                },
            )

        for neighbor in neighbors:
            register_client(
                neighbor.mac,
                {
                    "ipv4": neighbor.ip,
                    "interface": neighbor.interface,
                    "connection_type": "wired"
                    if neighbor.interface and not neighbor.interface.startswith("wl")
                    else None,
                    "online": True,
                    "last_seen": utcnow_iso(),
                },
            )

        for wifi in wifi_clients:
            register_client(
                wifi["mac"],
                {
                    "interface": wifi.get("interface"),
                    "connection_type": "wireless",
                    "signal_dbm": wifi.get("signal"),
                    "online": True,
                    "last_seen": utcnow_iso(),
                },
            )

        await self.registry.async_save()

        for primary, info in self.registry.devices.items():
            if info.get("alias") != self.alias:
                continue
            if primary in clients:
                continue
            previous = previous_clients.get(primary)
            if previous:
                clients[primary] = replace(previous)
                clients[primary].online = False
            else:
                clients[primary] = NxClient(
                    primary_mac=primary,
                    alias=self.alias,
                    macs=set(info.get("macs", [])),
                    online=False,
                )

        return clients


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the NxController integration."""

    hass.data.setdefault(DOMAIN, {})

    async def async_handle_map_mac(call: ServiceCall) -> None:
        alias = call.data[CONF_ALIAS]
        primary = normalize_mac(call.data.get("primary_mac", ""))
        alt = normalize_mac(call.data.get("alt_mac", ""))
        if not primary or not alt:
            raise ValueError("Invalid MAC provided")
        target_entry_id = None
        for entry_id, data in hass.data[DOMAIN].items():
            if isinstance(data, NxControllerCoordinator) or "coordinator" in data:
                coordinator: NxControllerCoordinator = (
                    data if isinstance(data, NxControllerCoordinator) else data["coordinator"]
                )
                if coordinator.alias == alias:
                    target_entry_id = entry_id
                    registry = coordinator.registry
                    break
        if not target_entry_id:
            raise ValueError("Alias not found")
        registry.add_mac(alias, primary, alt)
        await registry.async_save()
        entity_reg = er.async_get(hass)
        alt_unique = f"{alias}_{alt.replace(':', '')}"
        for entity_id, entry in list(entity_reg.entities.items()):
            if entry.unique_id == alt_unique:
                entity_reg.async_remove(entity_id)
        coordinator.async_set_updated_data(coordinator.data)
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_MAP_MAC, async_handle_map_mac)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NxController from a config entry."""

    registry = DeviceRegistry(hass)
    await registry.async_load()

    coordinator = NxControllerCoordinator(hass, entry, registry)

    try:
        await coordinator.client.async_run_command("echo NxController")
    except NxSSHError as err:
        raise ConfigEntryNotReady(str(err)) from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "registry": registry,
    }

    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    await coordinator.async_config_entry_first_refresh()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload NxController config entry."""

    data = hass.data[DOMAIN].get(entry.entry_id)
    if data:
        await data["coordinator"].client.close()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
