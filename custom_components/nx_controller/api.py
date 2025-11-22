from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
from typing import Any

import asyncssh


class NxSSHError(Exception):
    """Raised when SSH communication with the controller fails."""


@dataclass
class DiscoveredDevice:
    """Representation of a connected device."""

    mac: str
    interface: str
    ip: str | None
    state: str | None

    @property
    def as_dict(self) -> dict[str, Any]:
        """Return a dictionary representation for coordinator consumers."""

        return {
            "interface": self.interface,
            "ip": self.ip,
            "state": self.state,
        }


class NxSSHClient:
    """Handle SSH interactions with the Nx Controller device."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self.username = username
        self.password = password

    async def fetch_interface_devices(self, collect_dhcp: bool = False) -> dict[str, Any]:
        """Return the list of interfaces and the devices connected to them.

        When ``collect_dhcp`` is True, DHCP configuration is also fetched using
        ``uci show dhcp``.
        """

        try:
            async with asyncssh.connect(
                self.host, username=self.username, password=self.password, known_hosts=None
            ) as conn:
                interfaces = await self._list_interfaces(conn)
                devices = await self._collect_devices(conn, interfaces)
                dhcp_config = (
                    await self._collect_dhcp_config(conn) if collect_dhcp else None
                )
        except (asyncssh.Error, OSError) as err:
            raise NxSSHError("Unable to communicate with the controller") from err

        aggregated_devices: dict[str, dict[str, Any]] = {}
        endpoint_to_primary_mac: dict[str, str] = {}

        for device in devices:
            identifier = device.ip or device.mac
            primary_mac = endpoint_to_primary_mac.get(identifier, device.mac)

            entry = aggregated_devices.setdefault(
                primary_mac,
                {
                    "interfaces": set(),
                    "ipv4_addresses": set(),
                    "ipv6_addresses": set(),
                    "state": device.state,
                    "host": None,
                    "mac_addresses": [primary_mac],
                },
            )

            if identifier not in endpoint_to_primary_mac:
                endpoint_to_primary_mac[identifier] = primary_mac

            endpoint_to_primary_mac.setdefault(device.mac, primary_mac)

            if device.mac not in entry["mac_addresses"]:
                entry["mac_addresses"].append(device.mac)

            entry["interfaces"].add(device.interface)

            if device.ip:
                try:
                    ip_obj = ipaddress.ip_address(device.ip)
                except ValueError:
                    entry["host"] = device.ip
                else:
                    if ip_obj.version == 4:
                        entry["ipv4_addresses"].add(device.ip)
                    else:
                        entry["ipv6_addresses"].add(device.ip)

            if device.state:
                entry["state"] = device.state

        devices_payload = {
            mac: {
                "interfaces": sorted(value["interfaces"]),
                "ipv4_addresses": sorted(value["ipv4_addresses"]),
                "ipv6_addresses": sorted(value["ipv6_addresses"]),
                "state": value.get("state"),
                "host": value.get("host"),
                "mac_addresses": value.get("mac_addresses", []),
            }
            for mac, value in aggregated_devices.items()
        }

        payload = {
            "interfaces": interfaces,
            "devices": devices_payload,
        }

        if dhcp_config is not None:
            payload["dhcp"] = dhcp_config

        return payload

    async def _list_interfaces(self, conn: asyncssh.SSHClientConnection) -> list[str]:
        """Collect interface names from the controller."""

        result = await conn.run("ip -o link show", check=False)
        if result.exit_status != 0:
            raise NxSSHError("Failed to obtain interfaces")

        interfaces: list[str] = []
        for line in result.stdout.splitlines():
            # Expected output: '1: lo: <...>'
            if ":" not in line:
                continue
            parts = line.split(":", 2)
            if len(parts) < 2:
                continue
            name = parts[1].strip()
            if name and name != "lo":
                interfaces.append(name)
        if not interfaces:
            raise NxSSHError("No interfaces discovered")
        return interfaces

    async def _collect_devices(
        self, conn: asyncssh.SSHClientConnection, interfaces: list[str]
    ) -> list[DiscoveredDevice]:
        """Collect connected devices from all interfaces."""

        tasks = [self._list_devices_for_interface(conn, interface) for interface in interfaces]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        devices: list[DiscoveredDevice] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            devices.extend(result)
        return devices

    async def _list_devices_for_interface(
        self, conn: asyncssh.SSHClientConnection, interface: str
    ) -> list[DiscoveredDevice]:
        """Parse neighbour information for a given interface."""

        result = await conn.run(f"ip neigh show dev {interface}", check=False)
        if result.exit_status != 0:
            result = None

        devices: list[DiscoveredDevice] = []
        seen_macs: set[str] = set()

        if result and result.stdout:
            for line in result.stdout.splitlines():
                # Example: '192.168.1.10 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE'
                parts = line.split()
                if not parts:
                    continue
                ip = parts[0] if parts else None
                mac: str | None = None
                state: str | None = None
                if "lladdr" in parts:
                    lladdr_index = parts.index("lladdr")
                    if lladdr_index + 1 < len(parts):
                        mac = parts[lladdr_index + 1]
                if parts:
                    state = parts[-1]

                if mac:
                    mac = mac.lower()
                    seen_macs.add(mac)
                    devices.append(
                        DiscoveredDevice(
                            mac=mac,
                            interface=interface,
                            ip=ip,
                            state=state,
                        )
                    )

        stations = await conn.run(
            f"iw dev {interface} station dump", check=False
        )
        if stations.exit_status == 0 and stations.stdout:
            for line in stations.stdout.splitlines():
                stripped_line = line.strip()
                if not stripped_line.lower().startswith("station "):
                    continue

                parts = stripped_line.split()
                if len(parts) < 2:
                    continue

                mac = parts[1].lower()
                if mac in seen_macs:
                    continue

                seen_macs.add(mac)
                devices.append(
                    DiscoveredDevice(
                        mac=mac,
                        interface=interface,
                        ip=None,
                        state=None,
                    )
                )

        return devices

    async def _collect_dhcp_config(self, conn: asyncssh.SSHClientConnection) -> dict[str, Any]:
        """Collect DHCP configuration using ``uci show dhcp``."""

        result = await conn.run("uci show dhcp", check=False)
        if result.exit_status != 0:
            raise NxSSHError("Failed to obtain DHCP configuration")

        sections: dict[str, dict[str, str]] = {}
        for line in result.stdout.splitlines():
            if not line.startswith("dhcp."):
                continue

            key, _, value = line.partition("=")
            if not value:
                continue

            key_parts = key.split(".", 2)
            if len(key_parts) < 3:
                continue

            _, section, option = key_parts
            section_data = sections.setdefault(section, {})
            section_data[option] = value.strip().strip("'\"")

        dhcp_ranges: dict[str, dict[str, Any]] = {}
        for section_data in sections.values():
            interface = section_data.get("interface")
            if not interface:
                continue

            start = self._as_int(section_data.get("start"))
            limit = self._as_int(section_data.get("limit"))
            leasetime = section_data.get("leasetime")

            range_info: dict[str, Any] = {}
            if start is not None:
                range_info["start"] = start
            if limit is not None:
                range_info["limit"] = limit
            if start is not None and limit is not None:
                range_info["end"] = start + limit - 1
            if leasetime:
                range_info["leasetime"] = leasetime

            if range_info:
                dhcp_ranges[interface] = range_info

        return dhcp_ranges

    @staticmethod
    def _as_int(value: str | None) -> int | None:
        """Convert a value to int when possible."""

        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None
