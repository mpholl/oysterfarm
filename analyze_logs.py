#!/usr/bin/env python3
import json
import statistics
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# === CONFIG ===
LOG_DIR = Path(__file__).resolve().parent / "logs"
IDEAL_RANGE = (80, 95)  # Ideal humidity range for mushrooms (in %)

def iter_log_entries():
    """Yield parsed JSON entries from all log-*.jsonl files."""
    for file in sorted(LOG_DIR.glob("log-*.jsonl")):
        with file.open() as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue
                if "humidity_%" in entry:
                    yield entry

def analyze():
    humidities = []
    timestamps = []
    by_day = defaultdict(list)

    for e in iter_log_entries():
        h = e.get("humidity_%")
        ts = e.get("timestamp")
        if h is None or ts is None:
            continue
        try:
            h = float(h)
            t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

        humidities.append(h)
        timestamps.append(t)
        day = t.date().isoformat()
        by_day[day].append(h)

    if not humidities:
        print("No humidity data found.")
        return

    # ---- Basic statistics ----
    mean_h = statistics.mean(humidities)
    median_h = statistics.median(humidities)
    min_h, max_h = min(humidities), max(humidities)
    std_h = statistics.stdev(humidities) if len(humidities) > 1 else 0
    in_range = sum(IDEAL_RANGE[0] <= h <= IDEAL_RANGE[1] for h in humidities)
    frac_in_range = 100 * in_range / len(humidities)

    print("📊 Overall Humidity Statistics")
    print("==============================")
    print(f"Data points:     {len(humidities)}")
    print(f"Mean humidity:   {mean_h:.2f} %")
    print(f"Median humidity: {median_h:.2f} %")
    print(f"Min humidity:    {min_h:.2f} %")
    print(f"Max humidity:    {max_h:.2f} %")
    print(f"Std deviation:   {std_h:.2f}")
    print(f"In ideal range {IDEAL_RANGE[0]}–{IDEAL_RANGE[1]}%: {frac_in_range:.1f} % of samples\n")

    print("📅 Daily averages")
    print("=================")
    daily_means = {}
    for day in sorted(by_day.keys()):
        vals = by_day[day]
        avg = statistics.mean(vals)
        daily_means[day] = avg
        print(f"{day}: {avg:.2f} % (n={len(vals)})")

    # ---- PLOTS ----
    print("\nGenerating plots...")

    # 1️⃣ Histogram
    plt.figure(figsize=(8,5))
    plt.hist(humidities, bins=30, edgecolor="black", color="#60a5fa")
    plt.axvspan(IDEAL_RANGE[0], IDEAL_RANGE[1], color="#bbf7d0", alpha=0.5, label="Ideal range")
    plt.xlabel("Humidity (%)")
    plt.ylabel("Count")
    plt.title("Humidity Distribution")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()

    # 2️⃣ Time series
    plt.figure(figsize=(10,5))
    plt.plot(timestamps, humidities, color="#3b82f6", linewidth=1)
    plt.axhspan(IDEAL_RANGE[0], IDEAL_RANGE[1], color="#bbf7d0", alpha=0.5, label="Ideal range")
    plt.xlabel("Time")
    plt.ylabel("Humidity (%)")
    plt.title("Humidity Over Time")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    plt.gcf().autofmt_xdate()

    # 3️⃣ Daily averages
    plt.figure(figsize=(8,5))
    days = [datetime.strptime(d, "%Y-%m-%d") for d in daily_means.keys()]
    means = list(daily_means.values())
    plt.plot(days, means, marker="o", color="#16a34a")
    plt.xlabel("Day")
    plt.ylabel("Average Humidity (%)")
    plt.title("Daily Average Humidity")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    plt.gcf().autofmt_xdate()

    plt.show()

if __name__ == "__main__":
    analyze()
