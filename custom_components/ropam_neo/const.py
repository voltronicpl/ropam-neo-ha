"""Stałe integracji Ropam Neo."""

DOMAIN = "ropam_neo"
MANUFACTURER = "Ropam Elektronik"

CONF_DEVICE_ID = "device_id"
CONF_TCP_KEY = "tcp_key"
CONF_USER_CODE = "user_code"
CONF_PANIC_BUTTON = "panic_button"

DEFAULT_PORT = 9999
SETUP_TIMEOUT = 25

PANEL_URL_PATH = "ropam-neo"
PANEL_STATIC_URL = "/ropam_neo_static"
PANEL_JS = "ropam-neo-panel.js"
PANEL_ELEMENT = "ropam-neo-panel"

EVENT_MESSAGE = "ropam_neo_message"

PLATFORMS = ["alarm_control_panel", "binary_sensor", "button", "sensor", "switch"]

VERSION = "1.1"
