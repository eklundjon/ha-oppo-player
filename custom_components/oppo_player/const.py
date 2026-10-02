"""Constants for the Oppo UDP-20x integration."""

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.remote import DOMAIN as REMOTE_DOMAIN

DOMAIN = "oppo_player"
# The domain this integration used before 0.3.0 (shared with upstream
# simbaja/ha_oppoudp). Its config entries can be imported; see migration.py.
LEGACY_DOMAIN = "oppo_udp"

# socket:// (native IP control) default: the Oppo listens on TCP 23.
DEFAULT_PORT = 23
# rfc2217:// / esphome:// reach the RS-232 port through a network serial
# gateway, which commonly listens on 4999 (e.g. Global Caché iTach).
DEFAULT_GATEWAY_PORT = 4999
# Local RS-232 defaults: the Oppo runs 9600 8N1 (docs/PROTOCOL.md).
DEFAULT_SERIAL_DEVICE = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 9600

# Config-entry data keys. New entries store a serialx CONF_URL (plus
# CONF_BAUDRATE for local serial); legacy entries hold CONF_HOST/CONF_PORT and
# are mapped to socket://host:port at read time (see controller.entry_url).
CONF_URL = "url"
CONF_BAUDRATE = "baudrate"
# Set on an entry created by importing an old oppo_udp entry, until setup has
# moved that entry's entities and device over (migration.py).
CONF_LEGACY_ENTRY_ID = "legacy_entry_id"

PLATFORMS = [MEDIA_PLAYER_DOMAIN, REMOTE_DOMAIN]

SIGNAL_CONNECTED = "oppo_player_connected"
SIGNAL_DISCONNECTED = "oppo_player_disconnected"
SIGNAL_CLIENT_CREATED = "oppo_player_client_created"
