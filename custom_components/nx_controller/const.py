from datetime import timedelta
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform

DOMAIN = "nx_controller"
PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

CONF_SSH_USERNAME = CONF_USERNAME
CONF_SSH_PASSWORD = CONF_PASSWORD
