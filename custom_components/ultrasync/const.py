"""Constants the Interlogix/Hills ComNav UltraSync Hub."""

DOMAIN = "ultrasync"

# What each zone is (a door, a motion sensor, ...), chosen in the options. It
# maps the zone's number (as text) to one of ZONE_TYPES.
CONF_ZONE_TYPES = "zone_types"

# The choices, which are Home Assistant binary sensor device classes. "none"
# keeps the plain on/off sensor.
ZONE_TYPE_NONE = "none"
ZONE_TYPES = (
    ZONE_TYPE_NONE,
    "door",
    "window",
    "garage_door",
    "opening",
    "motion",
    "occupancy",
    "smoke",
    "gas",
    "moisture",
    "vibration",
    "safety",
)

# Optional: the panel's MAC address, typed in by the user
CONF_MAC = "mac"

# Scan Time (in seconds)
DEFAULT_SCAN_INTERVAL = 1

DEFAULT_NAME = "UltraSync"

# Services
SERVICE_AWAY = "away"
SERVICE_STAY = "stay"
SERVICE_DISARM = "disarm"
SERVICE_BYPASS = "bypass"
SERVICE_UNBYPASS = "unbypass"
SERVICE_SWITCH = "switch"
SERVICE_PANIC = "panic"
SERVICE_MEDICAL = "medical"
SERVICE_FIRE = "fire"

# Index used for managing loaded sensors
SENSORS = "sensors"

DATA_COORDINATOR = "coordinator"
DATA_UNDO_UPDATE_LISTENER = "undo_update_listener"
SENSOR_UPDATE_LISTENER = "ultrasync_update_sensors"
