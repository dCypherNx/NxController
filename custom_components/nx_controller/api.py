from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import ipaddress
import re
from typing import Any, Iterable

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


@dataclass
class AggregatedDevice:
    """Normalized representation of a controller client."""

    primary_mac: str
    mac_addresses: set[str] = field(default_factory=set)
    interfaces: set[str] = field(default_factory=set)
    radios: set[str] = field(default_factory=set)
    ipv4_addresses: set[str] = field(default_factory=set)
    ipv6_addresses: set[str] = field(default_factory=set)
    host: str | None = None
    state: str | None = None
    name: str | None = None
    connections: list[dict[str, Any]] = field(default_factory=list)


class _DeviceAggregator:
    """Aggregate raw device data and enrich it with DHCP context."""

    def __init__(
        self, wifi_radios: dict[str, str], dhcp_config: dict[str, Any] | None
    ) -> None:
        self._wifi_radios = wifi_radios
        self._dhcp_hosts: dict[str, dict[str, Any]] = (dhcp_config or {}).get(
            "hosts", {}
        ) or {}
        self._dhcp_names_by_ip: dict[str, str] = {}
        self._dhcp_ips_by_mac: dict[str, str] = {}
        for mac, host in self._dhcp_hosts.items():
            ip = host.get("ip")
            name = host.get("name")
            if ip and name:
                self._dhcp_names_by_ip[ip] = name
            if ip:
                self._dhcp_ips_by_mac[mac] = ip

        self._entries: dict[str, AggregatedDevice] = {}
        self._endpoint_to_primary: dict[str, str] = {}

    def add_device(self, device: DiscoveredDevice) -> None:
        """Add a device to the aggregation bucket."""

        mac = device.mac.lower()
        interface = device.interface
        primary_mac = (
            self._endpoint_to_primary.get(mac)
            or (device.ip and self._endpoint_to_primary.get(device.ip))
            or mac
        )

        self._endpoint_to_primary.setdefault(mac, primary_mac)
        if device.ip:
            self._endpoint_to_primary.setdefault(device.ip, primary_mac)

        entry = self._entries.setdefault(
            primary_mac, AggregatedDevice(primary_mac=primary_mac)
        )
        entry.mac_addresses.add(mac)
        entry.interfaces.add(interface)

        radio = self._wifi_radios.get(interface)
        if radio:
            entry.radios.add(radio)

        connection_details: dict[str, Any] = {
            "interface": interface,
            "ip": device.ip,
            "state": device.state,
        }

        if radio:
            connection_details["radio"] = radio

        entry.connections.append(connection_details)

        if device.state:
            entry.state = device.state

        self._attach_ip(entry, device.ip)

    def _attach_ip(self, entry: AggregatedDevice, ip_value: str | None) -> None:
        """Attach an IP address or hostname to the aggregated entry."""

        if not ip_value:
            return

        try:
            ip_obj = ipaddress.ip_address(ip_value)
        except ValueError:
            entry.host = ip_value
            return

        if ip_obj.version == 4:
            entry.ipv4_addresses.add(ip_value)
        else:
            entry.ipv6_addresses.add(ip_value)

    def _apply_dhcp_context(self) -> None:
        """Enrich missing information using DHCP reservations."""

        for entry in self._entries.values():
            if not entry.ipv4_addresses and not entry.ipv6_addresses:
                for mac in entry.mac_addresses:
                    dhcp_ip = self._dhcp_ips_by_mac.get(mac)
                    if dhcp_ip:
                        self._attach_ip(entry, dhcp_ip)

            dhcp_name = self._dhcp_name_for(entry.mac_addresses, entry.ipv4_addresses)
            if dhcp_name:
                entry.name = dhcp_name

    def _resolved_host(self, entry: AggregatedDevice) -> str | None:
        """Return a consolidated host value, preferring the best identifier."""

        if entry.name:
            return entry.name

        if entry.host:
            return entry.host

        if entry.ipv4_addresses:
            return sorted(entry.ipv4_addresses)[0]

        if entry.ipv6_addresses:
            return sorted(entry.ipv6_addresses)[0]

        return None

    def _dhcp_name_for(
        self, macs: Iterable[str], ipv4_addresses: Iterable[str]
    ) -> str | None:
        """Return the DHCP name based on MAC or IPv4 assignment."""

        for mac in macs:
            host = self._dhcp_hosts.get(mac)
            if host and host.get("name"):
                return host["name"]

        for ip_value in ipv4_addresses:
            name = self._dhcp_names_by_ip.get(ip_value)
            if name:
                return name

        return None

    def as_payload(self) -> dict[str, Any]:
        """Return a deterministic representation suitable for the coordinator."""

        self._apply_dhcp_context()

        payload: dict[str, Any] = {}
        for primary_mac, entry in self._entries.items():
            mac_list = [primary_mac] + [
                mac for mac in sorted(entry.mac_addresses) if mac != primary_mac
            ]
            connections = sorted(
                entry.connections,
                key=lambda conn: (
                    conn.get("interface") or "",
                    conn.get("ip") or "",
                ),
            )
            host_value = self._resolved_host(entry)
            payload[primary_mac] = {
                "primary_mac": primary_mac,
                "interfaces": sorted(entry.interfaces),
                "radios": sorted(entry.radios),
                "ipv4_addresses": sorted(entry.ipv4_addresses),
                "ipv6_addresses": sorted(entry.ipv6_addresses),
                "state": entry.state,
                "host": host_value,
                "mac_addresses": mac_list,
                "name": entry.name,
                "connections": connections,
            }

        return payload


def apply_dhcp_fallbacks(
    devices: dict[str, Any], dhcp_data: dict[str, Any] | None
) -> None:
    """Populate missing IPs and names using DHCP provider data."""

    if not dhcp_data:
        return

    dhcp_hosts: dict[str, dict[str, Any]] = dhcp_data.get("hosts") or {}
    dhcp_ip_by_mac: dict[str, str] = {
        mac: host["ip"]
        for mac, host in dhcp_hosts.items()
        if host.get("ip")
    }
    dhcp_name_by_ip: dict[str, str] = {
        host["ip"]: host["name"]
        for host in dhcp_hosts.values()
        if host.get("ip") and host.get("name")
    }

    for device in devices.values():
        mac_addresses = [mac.lower() for mac in device.get("mac_addresses", [])]
        ipv4_addresses = set(device.get("ipv4_addresses") or [])

        if not ipv4_addresses:
            for mac in mac_addresses:
                dhcp_ip = dhcp_ip_by_mac.get(mac)
                if dhcp_ip:
                    ipv4_addresses.add(dhcp_ip)

            if ipv4_addresses:
                device["ipv4_addresses"] = sorted(ipv4_addresses)

        if device.get("name"):
            continue

        for mac in mac_addresses:
            host_info = dhcp_hosts.get(mac)
            if host_info and host_info.get("name"):
                device["name"] = host_info["name"]
                if not device.get("host"):
                    device["host"] = device["name"]
                break

        if device.get("name"):
            continue

        for ip in device.get("ipv4_addresses", []):
            dhcp_name = dhcp_name_by_ip.get(ip)
            if dhcp_name:
                device["name"] = dhcp_name
                if not device.get("host"):
                    device["host"] = dhcp_name
                break


def _hostname_entry() -> dict[str, Any]:
    """Return a default hostname entry structure."""

    return {
        "static_hostname": None,
        "dhcpv4_hostname": None,
        "dhcpv6_hostname": None,
        "ipv4": None,
        "ipv6": None,
    }


def _normalize_mac(mac: str | None) -> str | None:
    """Normalize a MAC address to upper case colon-separated format."""

    if not mac:
        return None

    mac_clean = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(mac_clean) != 12:
        return None

    mac_clean = mac_clean.upper()
    return ":".join(mac_clean[i : i + 2] for i in range(0, 12, 2))


def _valid_hostname(value: str | None) -> str | None:
    """Return a sanitized hostname or ``None`` when invalid."""

    if not value:
        return None

    cleaned = value.strip()
    if not cleaned or cleaned == "*":
        return None

    return cleaned


def _parse_static_hosts(text: str) -> dict[str, dict[str, Any]]:
    """Parse static host entries from ``uci show dhcp`` output."""

    sections: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        if not line.startswith("dhcp."):
            continue

        key, _, value = line.partition("=")
        if not value:
            continue

        value_clean = value.strip().strip('"')
        key_parts = key.split(".")
        if len(key_parts) < 2:
            continue

        section_id = key_parts[1]
        option = ".".join(key_parts[2:]) if len(key_parts) > 2 else None
        section_data = sections.setdefault(section_id, {})

        if option:
            section_data[option] = value_clean
        else:
            section_data["_type"] = value_clean

    hosts: dict[str, dict[str, Any]] = {}
    for section_data in sections.values():
        if section_data.get("_type") != "host":
            continue

        macs_raw = section_data.get("mac")
        if not macs_raw:
            continue

        hostname = _valid_hostname(section_data.get("name") or section_data.get("hostname"))
        ip_value = section_data.get("ip")

        for mac in macs_raw.split():
            normalized_mac = _normalize_mac(mac)
            if not normalized_mac:
                continue

            host_entry = hosts.setdefault(normalized_mac, _hostname_entry())
            host_entry["static_hostname"] = hostname
            if ip_value:
                host_entry["ipv4"] = ip_value

    return hosts


def _parse_dhcpv4(text: str) -> dict[str, dict[str, Any]]:
    """Parse DHCPv4 lease data from ``/tmp/dhcp.leases`` output."""

    leases: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue

        _, mac, ip_value, hostname_raw = parts[:4]
        normalized_mac = _normalize_mac(mac)
        if not normalized_mac:
            continue

        hostname = _valid_hostname(hostname_raw)

        entry = leases.setdefault(normalized_mac, _hostname_entry())
        if hostname:
            entry["dhcpv4_hostname"] = hostname
        if ip_value:
            entry["ipv4"] = ip_value

    return leases


def _parse_dhcpv6(text: str) -> dict[str, dict[str, Any]]:
    """Parse DHCPv6 lease data from ``/tmp/odhcpd.leases`` output."""

    leases: dict[str, dict[str, Any]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue

        ipv6_value, mac, hostname_raw = parts[:3]
        normalized_mac = _normalize_mac(mac)
        if not normalized_mac:
            continue

        hostname = _valid_hostname(hostname_raw)

        entry = leases.setdefault(normalized_mac, _hostname_entry())
        if hostname:
            entry["dhcpv6_hostname"] = hostname
        if ipv6_value:
            entry["ipv6"] = ipv6_value

    return leases


def _resolve_hostname(entry: dict[str, Any] | None) -> str | None:
    """Resolve hostname priority for a collected entry."""

    if not entry:
        return None

    for key in ("static_hostname", "dhcpv4_hostname", "dhcpv6_hostname"):
        value = _valid_hostname(entry.get(key)) if entry.get(key) is not None else None
        if value:
            return value

    return None


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
                wifi_radios = await self._wifi_radios(conn)
                devices = await self._collect_devices(conn, interfaces)
                hostname_sources = await self._collect_hostname_sources(conn)
                dhcp_config = (
                    await self._collect_dhcp_config(conn) if collect_dhcp else None
                )
        except (asyncssh.Error, OSError) as err:
            raise NxSSHError("Unable to communicate with the controller") from err

        aggregator = _DeviceAggregator(wifi_radios, dhcp_config)
        for device in devices:
            aggregator.add_device(device)

        payload = {
            "interfaces": interfaces,
            "devices": aggregator.as_payload(),
            "hostname_sources": hostname_sources,
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
        seen_interfaces: set[str] = set()
        for line in result.stdout.splitlines():
            # Expected output: '1: lo: <...>'
            if ":" not in line:
                continue
            parts = line.split(":", 2)
            if len(parts) < 2:
                continue
            name = parts[1].strip()
            if "@" in name:
                name = name.split("@", 1)[0].strip()
            if name and name != "lo" and name not in seen_interfaces:
                interfaces.append(name)
                seen_interfaces.add(name)
        if not interfaces:
            raise NxSSHError("No interfaces discovered")
        return interfaces

    async def _wifi_radios(self, conn: asyncssh.SSHClientConnection) -> dict[str, str]:
        """Map wireless interfaces to their radios (phys)."""

        result = await conn.run("iw dev", check=False)
        if result.exit_status != 0 or not result.stdout:
            return {}

        interface_to_radio: dict[str, str] = {}
        current_radio: str | None = None

        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("phy#"):
                current_radio = stripped.replace("phy#", "phy", 1)
                continue

            if not stripped.startswith("Interface "):
                continue

            parts = stripped.split()
            if len(parts) < 2:
                continue

            interface = parts[1]
            if current_radio:
                interface_to_radio[interface] = current_radio

        return interface_to_radio

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
            if len(key_parts) == 2:
                _, section = key_parts
                section_data = sections.setdefault(section, {})
                section_data["_type"] = value.strip().strip('"')
                continue

            _, section, option = key_parts
            section_data = sections.setdefault(section, {})
            section_data[option] = value.strip().strip('"')

        dhcp_ranges: dict[str, dict[str, Any]] = {}
        dhcp_hosts: dict[str, dict[str, str]] = {}
        for section_data in sections.values():
            section_type = section_data.get("_type")

            if section_type == "dhcp":
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

            if section_type == "host":
                macs = section_data.get("mac")
                if not macs:
                    continue

                for mac in macs.split():
                    mac_clean = mac.strip().lower()
                    if not mac_clean:
                        continue

                    dhcp_hosts[mac_clean] = {
                        "name": section_data.get("name") or section_data.get("hostname"),
                        "ip": section_data.get("ip"),
                    }

        return {"ranges": dhcp_ranges, "hosts": dhcp_hosts}

    async def _collect_hostname_sources(
        self, conn: asyncssh.SSHClientConnection
    ) -> dict[str, dict[str, Any]]:
        """Collect hostname information from static hosts and DHCP leases."""

        hostname_sources: dict[str, dict[str, Any]] = {}

        static_result = await conn.run("uci show dhcp", check=False)
        if static_result.exit_status == 0 and static_result.stdout:
            for mac, data in _parse_static_hosts(static_result.stdout).items():
                entry = hostname_sources.setdefault(mac, _hostname_entry())
                if data.get("static_hostname"):
                    entry["static_hostname"] = data["static_hostname"]
                if data.get("ipv4"):
                    entry["ipv4"] = data["ipv4"]

        dhcpv4_result = await conn.run("cat /tmp/dhcp.leases", check=False)
        if dhcpv4_result.exit_status == 0 and dhcpv4_result.stdout:
            for mac, data in _parse_dhcpv4(dhcpv4_result.stdout).items():
                entry = hostname_sources.setdefault(mac, _hostname_entry())
                if data.get("dhcpv4_hostname"):
                    entry["dhcpv4_hostname"] = data["dhcpv4_hostname"]
                if data.get("ipv4"):
                    entry["ipv4"] = data["ipv4"]

        dhcpv6_result = await conn.run("cat /tmp/odhcpd.leases", check=False)
        if dhcpv6_result.exit_status == 0 and dhcpv6_result.stdout:
            for mac, data in _parse_dhcpv6(dhcpv6_result.stdout).items():
                entry = hostname_sources.setdefault(mac, _hostname_entry())
                if data.get("dhcpv6_hostname"):
                    entry["dhcpv6_hostname"] = data["dhcpv6_hostname"]
                if data.get("ipv6"):
                    entry["ipv6"] = data["ipv6"]

        return hostname_sources

    @staticmethod
    def _as_int(value: str | None) -> int | None:
        """Convert a value to int when possible."""

        if value is None:
            return None

        try:
            return int(value)
        except (TypeError, ValueError):
            return None
