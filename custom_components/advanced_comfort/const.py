"""Constants for Advanced Comfort Controller."""

DOMAIN = "advanced_comfort"
NAME = "Advanced Comfort Controller"
TEMPERATURE_MODES = ["auto", "cool", "heat"]
HUMIDITY_MODES = ["auto", "humidify", "dehumidify"]
DEFAULTS = {
    "nodes": [],
    "auxiliaries": [],
    "hysteresis": 0.1,
    "min_dwell": 120,
    "sensor_timeout": 3600,
    "min_target": 5,
    "max_target": 40,
    "target": 24,
}
