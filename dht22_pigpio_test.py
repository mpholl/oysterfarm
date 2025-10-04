#!/usr/bin/env python3
import time
import pigpio
import DHT22  # the helper file you just created

pi = pigpio.pi()
sensor = DHT22.sensor(pi, 4)  # GPIO4

while True:
    sensor.trigger()
    time.sleep(2.0)
    print(f"{sensor.temperature():.1f} °C, {sensor.humidity():.1f} %RH")
