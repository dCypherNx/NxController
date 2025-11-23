"""Constants for the NxController integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "nx_controller"
NAME = "NxController"
PLATFORMS = ["sensor"]
STORAGE_KEY = f"{DOMAIN}_devices"
STORAGE_VERSION = 1

CONF_ALIAS = "alias"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_IS_DHCP_SERVER = "is_dhcp_server"

DEFAULT_PORT = 22
DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)

EVENT_NEW_MAC_DETECTED = f"{DOMAIN}.new_mac_detected"
SERVICE_MAP_MAC = "map_mac"
