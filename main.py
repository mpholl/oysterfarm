import time
from datetime import datetime
import pigpio
import DHT22
import json
import os


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
pi.write(humidifierpin, 1)
pi.write(fanpin,1)

# the main loop

while True:
    # read out the humidity and temperature
    temperature = sensor.temperature()
    humidity = sensor.humidity()
    # log humidity and temperature


    # if humidity is below threshold, turn off fan, run humidifier, 

    # if humidity is high, stop humidifier

    # check if fan has run in the last 45 mins, run for some time, then turn of

    # sleep for a few seconds
    time.sleep(5)

    


