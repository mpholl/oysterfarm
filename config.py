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


# transient runtime state (not a user-adjustable setting): a manual fan
# "run for x minutes" request, and manual on/off overrides for each device,
# both requested from the web interface
DEVICE_OVERRIDE_STATES = ("auto", "on", "off")


def _load_state():
    try:
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(updates):
    state = _load_state()
    state.update(updates)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    return state


def get_fan_force_until():
    return _load_state().get("fan_force_until")


def set_fan_force_until(until):
    _save_state({"fan_force_until": until})


def get_device_override(device):
    return _load_state().get(f"{device}_override", "auto")


def set_device_override(device, state):
    if state not in DEVICE_OVERRIDE_STATES:
        raise ValueError(f"invalid override state: {state!r}")
    _save_state({f"{device}_override": state})
