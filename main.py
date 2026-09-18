import time
from datetime import datetime
import pigpio
import DHT22
import json
import signal
import os
from config import load_config


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

        # if humidity is below threshold, start humidifying (in bursts, see below)
        if humidity<hum_low:
            humidifying = True
        # if humidity is high, stop humidifying
        elif humidity>hum_high:
            humidifying = False
            pi.write(humidifierpin, off)
        # if humidity higher than hum_purge, turn off humidifier and run fan
        if humidity>hum_purge:
            humidifying = False
            pi.write(humidifierpin, off)
            pi.write(fanpin, on)
            purging = True

        # check if currently purging
        if purging:
            if humidity<hum_high:   # if purging and humidity in range, stop
                pi.write(fanpin, off)
                purging = False
                fan_timestamp = time.time()
        else:        # check if fan has run in the last 45 mins, run for some time, then turn of
            # if fan is running, check if ran for longer than on time
            if (pi.read(fanpin) == on) and (time.time() - fan_timestamp > fan_on):
                pi.write(fanpin, off)
                fan_timestamp = time.time()
            #if fan isn't running, check if it's off for longer than off_time
            if (pi.read(fanpin) == off) and (time.time() - fan_timestamp > fan_pause):
                pi.write(fanpin, on)
                fan_timestamp = time.time()

            # pulse the humidifier in short bursts rather than running it continuously,
            # so humidity has time to diffuse to the sensor before overshooting hum_purge
            if humidifying:
                if (pi.read(humidifierpin) == on) and (time.time() - humidifier_timestamp > humidifier_on):
                    pi.write(humidifierpin, off)
                    humidifier_timestamp = time.time()
                if (pi.read(humidifierpin) == off) and (time.time() - humidifier_timestamp > humidifier_pause):
                    pi.write(humidifierpin, on)
                    humidifier_timestamp = time.time()
            else:
                pi.write(humidifierpin, off)

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
        


