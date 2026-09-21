import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")

# settings adjustable from the web interface
DEFAULTS = {
    "hum_low": 80,        # if humidity lower, run humidifier
    "hum_high": 90,       # if humidity higher, stop humidifier
    "hum_purge": 95,      # if humidity higher, purge tent with fan
    "fan_on": 2 * 60,     # [s] run fan for this time
    "fan_pause": 45 * 60, # [s] switch on fan, if off for more than this time
    "humidifier_on": 5 * 60,      # [s] humidifier burst duration, while humidity < hum_low
    "humidifier_pause": 25 * 60,  # [s] pause between humidifier bursts, to let humidity diffuse before re-checking
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
        for key in DEFAULTS:
            if key in data:
                cfg[key] = data[key]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save_config(updates):
    cfg = load_config()
    cfg.update({k: v for k, v in updates.items() if k in DEFAULTS})
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    return cfg


# transient runtime state (not a user-adjustable setting), e.g. a manual fan
# override requested from the web interface: "run the fan until this time"
def get_fan_force_until():
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
        return data.get("fan_force_until")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def set_fan_force_until(until):
    with open(STATE_PATH, "w") as f:
        json.dump({"fan_force_until": until}, f, indent=2)
