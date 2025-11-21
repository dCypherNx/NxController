from __future__ import annotations

import asyncio
from dataclasses import dataclass
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

    async def fetch_interface_devices(self) -> dict[str, Any]:
        """Return the list of interfaces and the devices connected to them."""

        try:
            async with asyncssh.connect(
                self.host, username=self.username, password=self.password, known_hosts=None
            ) as conn:
                interfaces = await self._list_interfaces(conn)
                devices = await self._collect_devices(conn, interfaces)
        except (asyncssh.Error, OSError) as err:
            raise NxSSHError("Unable to communicate with the controller") from err

        return {
            "interfaces": interfaces,
            "devices": {device.mac: device.as_dict for device in devices},
        }

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
            return []

        devices: list[DiscoveredDevice] = []
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
                devices.append(
                    DiscoveredDevice(
                        mac=mac.lower(),
                        interface=interface,
                        ip=ip,
                        state=state,
                    )
                )
        return devices
