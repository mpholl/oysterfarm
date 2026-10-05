import time
from datetime import datetime
import pigpio
import DHT22
import json
import signal
import os
from config import load_config, get_fan_force_until, set_fan_force_until, get_device_override


# timer settings
sleep_time = 5          # [s] sleep for this time at the end of each loop

# humidity thresholds and fan/humidifier timers are adjustable from the web
# interface and are re-read from config.json every loop iteration (see load_config())
purging = False
humidifying = False


# logging folders and filenames
LOG_DIR = "logs"         # Folder for log files
FNAME_FMT = "log-{date}.jsonl"  # daily log file name format

def open_log_for_today():
    os.makedirs(LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(LOG_DIR, FNAME_FMT.format(date=today))
    f = open(path, "a", buffering=1)  # line-buffered for safety
    return today, f

# handle ctrl+c to write a last log
stop = False
def handle_sig(signum, frame):
    global stop
    stop = True

signal.signal(signal.SIGINT, handle_sig)
signal.signal(signal.SIGTERM, handle_sig)

# initialize pi
pi = pigpio.pi()

# initialize pins
sensorpin = 4
humidifierpin = 23
fanpin = 24

sensor = DHT22.sensor(pi, sensorpin)
pi.set_mode(humidifierpin, pigpio.OUTPUT)
pi.set_mode(fanpin, pigpio.OUTPUT)


# turn off humidifier and pin, to start (off: 1, on: 0)
on = 0
off = 1
pi.write(humidifierpin, off)
pi.write(fanpin, off)

current_day, log_file = open_log_for_today()
print(f"Logging to {log_file.name} (Ctrl+C to stop)")
fan_timestamp = time.time()
humidifier_timestamp = time.time()
purge_timestamp = time.time()

# the main loop
try: 
    while not stop:
        sensor.trigger()
        # sleep for a few seconds
        time.sleep(sleep_time)
        # check if we need a new log file
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        if date_str != current_day:
            log_file.close()
            current_day, log_file = open_log_for_today()
            print(f"Rotated log → {log_file.name}")
        
        # read out the humidity and temperature
        temperature = sensor.temperature()
        humidity = sensor.humidity()

        # re-read adjustable settings, in case they were changed via the web interface
        cfg = load_config()
        hum_low = cfg["hum_low"]
        hum_high = cfg["hum_high"]
        hum_purge = cfg["hum_purge"]
        fan_on = cfg["fan_on"]
        fan_pause = cfg["fan_pause"]
        humidifier_on = cfg["humidifier_on"]
        humidifier_pause = cfg["humidifier_pause"]
        purge_max = cfg["purge_max"]

        now_ts = time.time()

        # --- humidifier control ---
        # if humidity is below threshold, start humidifying (in bursts, see below)
        if humidity<hum_low:
            humidifying = True
        # if humidity is high, stop humidifying
        elif humidity>hum_high:
            humidifying = False
        # if humidity higher than hum_purge, stop humidifying and purge tent with fan
        if humidity>hum_purge:
            humidifying = False
            if not purging:   # just starting a new purge, start the max-runtime timer
                purge_timestamp = now_ts
            purging = True

        # a manual on/off override from the web interface takes priority over
        # the automatic humidity-based control above
        humidifier_override = get_device_override("humidifier")
        if humidifier_override == "on":
            pi.write(humidifierpin, on)
            humidifier_timestamp = now_ts
        elif humidifier_override == "off":
            pi.write(humidifierpin, off)
            humidifier_timestamp = now_ts
        elif not humidifying:
            pi.write(humidifierpin, off)
        else:
            # pulse the humidifier in short bursts rather than running it continuously,
            # so humidity has time to diffuse to the sensor before overshooting hum_purge
            if (pi.read(humidifierpin) == on) and (now_ts - humidifier_timestamp > humidifier_on):
                pi.write(humidifierpin, off)
                humidifier_timestamp = now_ts
            if (pi.read(humidifierpin) == off) and (now_ts - humidifier_timestamp > humidifier_pause):
                pi.write(humidifierpin, on)
                humidifier_timestamp = now_ts

        # --- fan control ---
        # a manual "force fan on for x minutes" request from the web interface
        fan_force_until = get_fan_force_until()
        fan_forced = fan_force_until is not None and now_ts < fan_force_until
        if fan_force_until is not None and not fan_forced:
            # forced run just expired: turn the fan off and restart the regular
            # pause timer from now, instead of leaving it running for another
            # full fan_on burst
            set_fan_force_until(None)
            pi.write(fanpin, off)
            fan_timestamp = now_ts

        # a manual on/off override takes priority over both the timed force
        # above and the automatic purge/pulse schedule below
        fan_override = get_device_override("fan")
        if fan_override == "on":
            pi.write(fanpin, on)
            fan_timestamp = now_ts
        elif fan_override == "off":
            pi.write(fanpin, off)
            fan_timestamp = now_ts
        elif fan_forced:
            pi.write(fanpin, on)
        elif purging:
            pi.write(fanpin, on)
            back_in_range = humidity<(hum_low+hum_high)/2   # humidity back to mid-range, stop
            timed_out = (now_ts - purge_timestamp>=purge_max) and humidity<hum_purge   # ran too long, but at least below the purge threshold
            if back_in_range or timed_out:
                pi.write(fanpin, off)
                purging = False
                fan_timestamp = now_ts
        else:        # check if fan has run in the last 45 mins, run for some time, then turn of
            # if fan is running, check if ran for longer than on time
            if (pi.read(fanpin) == on) and (now_ts - fan_timestamp > fan_on):
                pi.write(fanpin, off)
                fan_timestamp = now_ts
            #if fan isn't running, check if it's off for longer than off_time
            if (pi.read(fanpin) == off) and (now_ts - fan_timestamp > fan_pause):
                pi.write(fanpin, on)
                fan_timestamp = now_ts

        # finally log everything
        entry = {
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "temperature_C": sensor.temperature(),
                "humidity_%": sensor.humidity(),
                "fan_status": pi.read(fanpin),
                "humidifier_status": pi.read(humidifierpin)
                }
        log_file.write(json.dumps(entry) + "\n")
        print(entry)

        
finally:
    log_file.close()
    pi.write(humidifierpin, off)
    pi.write(fanpin, off)
    pi.stop()
    print("Stopped cleanly.")
        


