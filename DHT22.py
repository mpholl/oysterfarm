# DHT22.py
# Minimal DHT22/AM2302 sensor reader using pigpio
import time, pigpio

class sensor:
    def __init__(self, pi, gpio):
        self.pi = pi
        self.gpio = gpio
        self.temperature_val = 0.0
        self.humidity_val = 0.0
        self.next_read_time = time.time()
        self.cb = None
        pi.set_mode(gpio, pigpio.INPUT)
        pi.set_pull_up_down(gpio, pigpio.PUD_UP)

    def _callback(self, gpio, level, tick):
        self.edges.append((level, tick))

    def trigger(self):
        # Only trigger every 2s (sensor spec)
        if time.time() < self.next_read_time:
            return
        self.next_read_time = time.time() + 2.0

        self.edges = []
        self.cb = self.pi.callback(self.gpio, pigpio.EITHER_EDGE, self._callback)

        # Send start signal
        self.pi.set_mode(self.gpio, pigpio.OUTPUT)
        self.pi.write(self.gpio, 0)
        time.sleep(0.001)  # 1 ms
        self.pi.set_mode(self.gpio, pigpio.INPUT)
        self.pi.set_pull_up_down(self.gpio, pigpio.PUD_UP)

        time.sleep(0.05)
        self.cb.cancel()

        # Decode waveform
        highs = []
        for i in range(1, len(self.edges)):
            prev = self.edges[i - 1]
            cur = self.edges[i]
            if prev[0] == 1 and cur[0] == 0:
                dt = pigpio.tickDiff(prev[1], cur[1])
                highs.append(dt)

        if len(highs) < 40:
            return None

        bits = [1 if w > 50 else 0 for w in highs[-40:]]
        data = []
        for i in range(0, 40, 8):
            byte = 0
            for bit in bits[i:i+8]:
                byte = (byte << 1) | bit
            data.append(byte)

        if len(data) == 5 and ((sum(data[:4]) & 0xFF) == data[4]):
            self.humidity_val = ((data[0] << 8) + data[1]) / 10.0
            t_raw = ((data[2] << 8) + data[3])
            if t_raw & 0x8000:
                t_raw = -((t_raw & 0x7FFF))
            self.temperature_val = t_raw / 10.0

    def temperature(self):
        return self.temperature_val

    def humidity(self):
        return self.humidity_val
