"""Constants for the Pirkanmaan Jätehuolto integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "pirkka_jatehuolto"
BASE_URL = "https://extranet.pjhoy.fi/pirkka"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"

PLATFORMS: list[Platform] = [Platform.SENSOR]

DEFAULT_MAX_REFRESH = timedelta(days=7)
DEFAULT_NO_DATE_REFRESH = timedelta(days=1)
DEFAULT_PAST_DATE_REFRESH = timedelta(hours=6)
DEFAULT_POST_DATE_REFRESH_HOUR = 3
DEFAULT_POST_DATE_REFRESH_MINUTE = 15
DEFAULT_JITTER_MINUTES = (1, 10)
MAX_FAILURE_BACKOFF = timedelta(hours=12)
