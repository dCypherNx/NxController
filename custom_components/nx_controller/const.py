from homeassistant.const import CONF_HOST, Platform

DOMAIN = "nx_controller"
PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)
