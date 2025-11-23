"""Async SSH client and parsers for NxController."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import asyncssh

MAC_REGEX = re.compile(r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})")


class NxSSHError(Exception):
    """Raised when SSH operations fail."""


@dataclass
class WifiClient:
    """Representation of a wireless client."""

    mac: str
    interface: Optional[str]
    signal_dbm: Optional[int]


@dataclass
class NeighborEntry:
    """Representation of a neighbor entry."""

    mac: str
    ip: str
    interface: Optional[str]


class NxSSHClient:
    """Thin asyncssh wrapper for NxController."""

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._lock = asyncio.Lock()
        self._conn: Optional[asyncssh.SSHClientConnection] = None

    async def _ensure_connection(self) -> asyncssh.SSHClientConnection:
        if self._conn and not self._conn._transport.is_closing():
            return self._conn
        async with self._lock:
            if self._conn and not self._conn._transport.is_closing():
                return self._conn
            try:
                self._conn = await asyncssh.connect(
                    self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    known_hosts=None,
                    server_host_key_algs=["ssh-rsa", "ssh-ed25519", "ssh-dss"],
                )
            except (asyncssh.Error, OSError) as err:
                raise NxSSHError(str(err)) from err
        return self._conn

    async def close(self) -> None:
        """Close the SSH connection."""

        if self._conn:
            self._conn.close()
            self._conn = None

    async def async_run_command(self, command: str) -> str:
        """Run a command over SSH and return stdout."""

        conn = await self._ensure_connection()
        try:
            result = await conn.run(command, check=False)
        except (asyncssh.Error, OSError) as err:
            raise NxSSHError(str(err)) from err
        if result.exit_status is None:
            raise NxSSHError("Command execution failed")
        return result.stdout or ""

    async def async_get_dhcp_hosts(self) -> List[Dict[str, str]]:
        output = await self.async_run_command("uci show dhcp 2>/dev/null || true")
        return parse_dhcp_hosts(output)

    async def async_get_dhcp_leases(self) -> List[Dict[str, str]]:
        output = await self.async_run_command("cat /tmp/dhcp.leases 2>/dev/null || true")
        return parse_dhcp_leases(output)

    async def async_get_odhcpd_leases(self) -> List[Dict[str, str]]:
        output = await self.async_run_command("cat /tmp/odhcpd.leases 2>/dev/null || true")
        return parse_odhcpd_leases(output)

    async def async_get_neighbors(self) -> List[NeighborEntry]:
        output = await self.async_run_command(
            "ip neigh show 2>/dev/null || cat /proc/net/arp 2>/dev/null || true"
        )
        return parse_neighbors(output)

    async def async_get_wifi_interfaces(self) -> Set[str]:
        output = await self.async_run_command("iwinfo 2>/dev/null || true")
        interfaces = parse_iwinfo_interfaces(output)
        if interfaces:
            return interfaces
        alt_output = await self.async_run_command("iw dev 2>/dev/null || true")
        return parse_iw_dev_interfaces(alt_output)

    async def async_get_wifi_clients(self, interface: str) -> List[WifiClient]:
        output = await self.async_run_command(
            f"iwinfo {interface} assoclist 2>/dev/null || true"
        )
        return parse_wifi_assoclist(output, interface)


def normalize_mac(mac: str) -> Optional[str]:
    match = MAC_REGEX.search(mac or "")
    if not match:
        return None
    parts = match.group(0).replace("-", ":").split(":")
    return ":".join(part.upper().zfill(2) for part in parts)


def parse_dhcp_hosts(output: str) -> List[Dict[str, str]]:
    hosts: Dict[str, Dict[str, str]] = {}
    for line in output.splitlines():
        if not line.startswith("dhcp.@host"):
            continue
        key_val = line.split("=", 1)
        if len(key_val) != 2:
            continue
        path, value = key_val
        match = re.search(r"host\[(\d+)\]\.([^.]+)", path)
        if not match:
            continue
        idx = match.group(1)
        field = match.group(2)
        value = value.strip().strip("'\"")
        host = hosts.setdefault(idx, {})
        host[field] = value
    results = []
    for host in hosts.values():
        mac = normalize_mac(host.get("mac", ""))
        if not mac:
            continue
        results.append(
            {
                "mac": mac,
                "ip": host.get("ip"),
                "hostname": host.get("name"),
                "source": "static",
            }
        )
    return results


def parse_dhcp_leases(output: str) -> List[Dict[str, str]]:
    leases: List[Dict[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        _, mac_raw, ip, hostname = parts[:4]
        mac = normalize_mac(mac_raw)
        if not mac:
            continue
        leases.append(
            {
                "mac": mac,
                "ip": ip,
                "hostname": hostname if hostname != "*" else None,
                "source": "dynamic",
            }
        )
    return leases


def parse_odhcpd_leases(output: str) -> List[Dict[str, str]]:
    leases: List[Dict[str, str]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        mac = None
        hostname = None
        ipv6 = None
        for part in parts:
            if not ipv6 and ":" in part and not MAC_REGEX.fullmatch(part):
                ipv6 = part
            if not hostname and part.isascii() and ":" not in part and not MAC_REGEX.fullmatch(part):
                hostname = part
            if MAC_REGEX.fullmatch(part):
                mac = normalize_mac(part)
        if mac:
            leases.append(
                {
                    "mac": mac,
                    "ipv6": ipv6,
                    "hostname": hostname if hostname and hostname != "*" else None,
                    "source": "dynamic",
                }
            )
    return leases


def parse_neighbors(output: str) -> List[NeighborEntry]:
    neighbors: List[NeighborEntry] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        if "ip neigh" in line or line.startswith("IP address"):
            continue
        parts = line.split()
        mac: Optional[str] = None
        ip: Optional[str] = None
        interface: Optional[str] = None
        if "dev" in parts:
            dev_index = parts.index("dev")
            if dev_index + 1 < len(parts):
                interface = parts[dev_index + 1]
        if "lladdr" in parts:
            mac_index = parts.index("lladdr")
            if mac_index + 1 < len(parts):
                mac = normalize_mac(parts[mac_index + 1])
        if not mac and len(parts) >= 6 and MAC_REGEX.fullmatch(parts[3]):
            mac = normalize_mac(parts[3])
        if parts:
            ip_candidate = parts[0]
            if ip_candidate[0].isdigit() or ":" in ip_candidate:
                ip = ip_candidate
        if mac and ip:
            neighbors.append(NeighborEntry(mac=mac, ip=ip, interface=interface))
    return neighbors


def parse_iwinfo_interfaces(output: str) -> Set[str]:
    interfaces: Set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        iface = line.split()[0]
        if iface:
            interfaces.add(iface)
    return interfaces


def parse_iw_dev_interfaces(output: str) -> Set[str]:
    interfaces: Set[str] = set()
    for line in output.splitlines():
        if "Interface" in line:
            parts = line.split()
            if len(parts) >= 2:
                interfaces.add(parts[1])
    return interfaces


def parse_wifi_assoclist(output: str, interface: str) -> List[WifiClient]:
    clients: List[WifiClient] = []
    for line in output.splitlines():
        match = MAC_REGEX.search(line)
        if not match:
            continue
        mac = normalize_mac(match.group(0))
        if not mac:
            continue
        signal_match = re.search(r"(-?\d+)\s*dBm", line)
        signal = int(signal_match.group(1)) if signal_match else None
        clients.append(WifiClient(mac=mac, interface=interface, signal_dbm=signal))
    return clients


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
