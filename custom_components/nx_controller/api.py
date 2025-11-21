from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp.client_exceptions import ClientError
import asyncssh


class OpenWrtError(Exception):
    """Generic OpenWrt error."""


class OpenWrtAuthError(OpenWrtError):
    """Authentication related errors."""


class OpenWrtConnectionError(OpenWrtError):
    """Connection errors while talking to OpenWrt."""


_LOGGER = logging.getLogger(__name__)

DEFAULT_SSH_DISCOVERY_COMMAND = "iw dev"
DEFAULT_SSH_COMMAND = "iwinfo wl0 assoclist"
DEFAULT_SSH_COMMANDS = [
    DEFAULT_SSH_DISCOVERY_COMMAND,
    DEFAULT_SSH_COMMAND,
    "iwinfo wlan0 assoclist",
    "iw dev wlan0 station dump",
]

INTERFACE_COMMAND_TEMPLATES = [
    "iwinfo {interface} assoclist",
    "iw dev {interface} station dump",
]


@dataclass
class OpenWrtDevice:
    """Representation of a device known by OpenWrt."""

    mac: str
    hostname: str | None
    ip_address: str | None
    interface: str | None
    attributes: dict[str, Any]


class OpenWrtClient:
    """HTTP client for the OpenWrt JSON-RPC API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        use_ssl: bool = True,
        verify_ssl: bool = True,
        session: aiohttp.ClientSession | None = None,
        timeout: int = 10,
    ) -> None:
        self._host = _normalize_host(host)
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._verify_ssl = verify_ssl
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._ubus_session: str | None = None

    @property
    def _base_url(self) -> str:
        scheme = "https" if self._use_ssl else "http"
        return f"{scheme}://{self._host}/ubus"

    async def _async_get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def async_validate(self) -> None:
        """Validate credentials without returning data."""

        await self._async_login(force=True)

    async def async_get_clients(self) -> list[dict[str, Any]]:
        """Return connected clients with metadata."""

        await self._async_login()

        leases = await self._collect_dhcp_leases()
        wireless_status = await self._call_ubus("network.wireless", "status", {})

        ifaces: list[str] = []
        for radio in wireless_status.values():
            for interface in radio.get("interfaces", []):
                if ifname := interface.get("ifname"):
                    ifaces.append(ifname)

        clients: list[dict[str, Any]] = []
        for ifname in ifaces:
            hostapd_object = f"hostapd.{ifname}"
            try:
                raw = await self._call_ubus(hostapd_object, "get_clients", {})
            except OpenWrtError:
                continue

            for mac, details in raw.get("clients", {}).items():
                normalized_mac = mac.lower()
                lease = leases.get(normalized_mac)
                attributes = {
                    "interface": ifname,
                    "signal": details.get("signal"),
                    "rx_rate": details.get("rx_rate"),
                    "tx_rate": details.get("tx_rate"),
                    "rx_bytes": details.get("rx_bytes"),
                    "tx_bytes": details.get("tx_bytes"),
                    "connected_time": details.get("connected_time"),
                    "authorized": details.get("authorized"),
                    "inactive": details.get("inactive"),
                }

                clients.append(
                    {
                        "mac": normalized_mac,
                        "hostname": details.get("hostname")
                        or (lease.get("hostname") if lease else None),
                        "ip_address": details.get("ipaddr")
                        or (lease.get("ip_address") if lease else None),
                        "interface": ifname,
                        "connected": bool(details.get("assoc", True)),
                        "attributes": attributes,
                    }
                )

        return clients

    async def _collect_dhcp_leases(self) -> dict[str, dict[str, Any]]:
        """Return DHCP leases indexed by MAC."""

        leases: dict[str, dict[str, Any]] = {}

        for method in ("ipv4leases", "leases"):
            try:
                payload = await self._call_ubus("dhcp", method, {})
            except OpenWrtError:
                continue

            for lease in payload.get("lease", []) or payload.get("leases", []):
                mac = (lease.get("mac") or lease.get("macaddr") or "").lower()
                if not mac:
                    continue
                leases[mac] = {
                    "hostname": lease.get("hostname") or lease.get("host"),
                    "ip_address": lease.get("ip") or lease.get("ipaddr"),
                    "expires": lease.get("expires") or lease.get("valid"),
                    "remaining": lease.get("remaining") or lease.get("valid_until"),
                }

        return leases

    async def _async_login(self, *, force: bool = False) -> None:
        """Authenticate with the router if needed."""

        if self._ubus_session and not force:
            return

        session = await self._async_get_session()

        try:
            response = await session.post(
                self._base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "call",
                    "params": [
                        "00000000000000000000000000000000",
                        "session",
                        "login",
                        {"username": self._username, "password": self._password},
                    ],
                },
                ssl=self._verify_ssl,
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, ClientError) as exc:
            raise OpenWrtConnectionError("Failed to reach OpenWrt host") from exc

        try:
            data = await response.json(content_type=None)
        except Exception as exc:  # pylint: disable=broad-except
            raise OpenWrtConnectionError("Invalid JSON response during login") from exc

        result = data.get("result")
        if not result or result[0] != 0:
            raise OpenWrtAuthError("Invalid credentials for OpenWrt")

        self._ubus_session = result[1].get("ubus_rpc_session")

    async def _call_ubus(self, path: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Perform a raw ubus call and return the payload."""

        if not self._ubus_session:
            await self._async_login()

        session = await self._async_get_session()

        try:
            response = await session.post(
                self._base_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "call",
                    "params": [
                        self._ubus_session,
                        path,
                        method,
                        params,
                    ],
                },
                ssl=self._verify_ssl,
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, ClientError) as exc:
            self._ubus_session = None
            raise OpenWrtConnectionError("Failed to reach OpenWrt host") from exc

        data = await response.json(content_type=None)
        result = data.get("result")
        if not result or result[0] != 0:
            raise OpenWrtError(f"ubus call failed for {path}:{method}")

        return result[1]


class SSHAccessPointClient:
    """Client to collect station info from non-native APs via SSH."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 22,
        command: str | None = DEFAULT_SSH_COMMAND,
        commands: list[str] | None = None,
        timeout: int = 10,
    ) -> None:
        self._host = _normalize_host(host)
        self._username = username
        self._password = password
        self._port = port
        cleaned_commands: list[str] = []
        if commands:
            cleaned_commands = [cmd.strip() for cmd in commands if cmd.strip()]
        elif command:
            cleaned_commands = [command]
        if not cleaned_commands:
            cleaned_commands = DEFAULT_SSH_COMMANDS
        elif DEFAULT_SSH_DISCOVERY_COMMAND not in cleaned_commands:
            cleaned_commands.insert(0, DEFAULT_SSH_DISCOVERY_COMMAND)

        self._commands = cleaned_commands
        self._timeout = timeout

    async def async_validate(self) -> None:
        """Validate SSH credentials by executing the command once."""

        await self._async_run_command(self._commands[0])

    async def async_get_clients(self) -> list[dict[str, Any]]:
        """Return connected clients parsed from the command output."""

        clients_by_mac: dict[str, dict[str, Any]] = {}
        last_error: Exception | None = None
        discovered_interfaces: set[str] = set()
        commands_to_try = list(self._commands)

        while commands_to_try:
            command = commands_to_try.pop(0)
            try:
                output = await self._async_run_command(command)
            except Exception as err:  # pylint: disable=broad-except
                last_error = err
                continue

            if _is_iw_dev_listing(command):
                interfaces = self._parse_interfaces(output)
                if interfaces:
                    _LOGGER.debug(
                        "Discovered wireless interfaces on %s: %s",
                        self._host,
                        ", ".join(sorted(interfaces)),
                    )
                new_commands = self._build_interface_commands(
                    interfaces, discovered_interfaces, commands_to_try
                )
                commands_to_try.extend(new_commands)
                continue

            interface = _extract_interface_from_command(command)
            for device in self._parse_assoclist_output(output, interface):
                mac = device.get("mac")
                if not mac:
                    continue
                merged = clients_by_mac.setdefault(mac, device)
                if merged is device:
                    continue
                merged["attributes"].update(device.get("attributes", {}))

        if not clients_by_mac and last_error:
            raise last_error

        return list(clients_by_mac.values())

    async def _async_run_command(self, command: str) -> str:
        """Execute the configured command over SSH and return stdout."""

        try:
            async with asyncssh.connect(
                self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                known_hosts=None,
            ) as conn:
                result = await asyncio.wait_for(
                    conn.run(command, check=True), timeout=self._timeout
                )
        except asyncio.TimeoutError as exc:
            raise OpenWrtConnectionError("SSH command timed out") from exc
        except asyncssh.PermissionDenied as exc:
            raise OpenWrtAuthError("SSH permission denied") from exc
        except asyncssh.AuthError as exc:
            raise OpenWrtAuthError("SSH authentication failed") from exc
        except asyncssh.ProcessError as exc:
            raise OpenWrtConnectionError("SSH command failed") from exc
        except asyncssh.Error as exc:
            raise OpenWrtConnectionError("SSH connection failed") from exc

        return result.stdout

    def _parse_assoclist_output(
        self, output: str, interface: str | None = None
    ) -> list[dict[str, Any]]:
        """Parse iwinfo assoclist output into device dictionaries."""

        clients: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        mac_pattern = re.compile(r"(?i)^(([0-9a-f]{2}:){5}[0-9a-f]{2})")
        signal_pattern = re.compile(r"(-?\d+)\s*dBm")

        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            mac_match = mac_pattern.match(stripped)
            if mac_match:
                mac = mac_match.group(1).lower()
                signal_match = signal_pattern.search(stripped)
                attributes: dict[str, Any] = {}
                if signal_match:
                    attributes["signal"] = int(signal_match.group(1))

                current = {
                    "mac": mac,
                    "hostname": None,
                    "ip_address": None,
                    "interface": interface,
                    "connected": True,
                    "attributes": attributes,
                }
                clients.append(current)
                continue

            if current is None:
                continue

            if stripped.startswith("RX:"):
                current["attributes"]["rx_info"] = stripped[3:].strip()
            elif stripped.startswith("TX:"):
                current["attributes"]["tx_info"] = stripped[3:].strip()

        return clients

    def _parse_interfaces(self, output: str) -> set[str]:
        """Return interface names discovered from `iw dev` output."""

        interfaces: set[str] = set()
        for line in output.splitlines():
            line = line.strip()
            if not line or "Interface" not in line:
                continue
            if match := re.search(r"Interface\s+(?P<iface>[\w.-]+)", line):
                interfaces.add(match.group("iface"))

        return interfaces

    def _build_interface_commands(
        self,
        interfaces: set[str],
        discovered_interfaces: set[str],
        pending_commands: list[str],
    ) -> list[str]:
        """Prepare per-interface commands derived from discovered interfaces."""

        new_commands: list[str] = []

        for iface in interfaces:
            if iface in discovered_interfaces:
                continue
            discovered_interfaces.add(iface)
            for template in INTERFACE_COMMAND_TEMPLATES:
                formatted = template.format(interface=iface)
                if formatted in self._commands or formatted in pending_commands:
                    continue
                new_commands.append(formatted)

        return new_commands


def _is_iw_dev_listing(command: str) -> bool:
    """Return True if the command lists interfaces using `iw dev`."""

    normalized = command.strip().lower()
    if "station dump" in normalized:
        return False
    return normalized == "iw dev" or normalized.startswith("iw dev ")


def _extract_interface_from_command(command: str) -> str | None:
    """Try to infer an interface name from iw/iwinfo commands."""

    normalized = command.strip()
    if not normalized:
        return None

    if match := re.search(r"^iw\s+dev\s+(?P<iface>[\w.-]+)", normalized, re.IGNORECASE):
        return match.group("iface")

    if match := re.search(r"^iwinfo\s+(?P<iface>[\w.-]+)", normalized, re.IGNORECASE):
        return match.group("iface")

    return None


def _normalize_host(raw_host: str) -> str:
    """Strip protocols/trailing slashes to normalize host values."""

    cleaned = raw_host.strip()
    parsed = urlparse(cleaned)

    # If the user included a path without a scheme (e.g. 192.168.1.1/cgi-bin/luci),
    # urlparse will place everything in ``path``. Prefixing with ``//`` lets us use
    # ``netloc`` to reliably grab the host:port portion.
    if parsed.scheme:
        cleaned = parsed.netloc or parsed.path
    elif parsed.path and "/" in parsed.path:
        cleaned = urlparse(f"//{cleaned}").netloc

    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE)
    return cleaned.rstrip("/")
