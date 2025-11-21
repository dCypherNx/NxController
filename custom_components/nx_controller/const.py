from __future__ import annotations

from datetime import timedelta
from homeassistant.const import Platform

DOMAIN = "nx_controller"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)

CONF_USE_SSL = "use_ssl"
CONF_VERIFY_SSL = "verify_ssl"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SOURCES = "sources"
CONF_SOURCE_NAME = "name"
CONF_SOURCE_TYPE = "type"
CONF_PORT = "port"
CONF_SSH_COMMAND = "ssh_command"
CONF_SSH_COMMANDS = "ssh_commands"

SOURCE_TYPE_OPENWRT = "openwrt"
SOURCE_TYPE_SSH = "ssh_ap"

DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"
DATA_CLIENTS = "clients"

PLATFORMS = [Platform.DEVICE_TRACKER]
