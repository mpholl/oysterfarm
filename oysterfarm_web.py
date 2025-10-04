#!/usr/bin/env python3
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, request, Response

# --- Configuration ---
LOG_DIR = Path("./logs")             # where your dht22-YYYY-MM-DD.jsonl files live
HOST = "0.0.0.0"                     # listen on all interfaces
PORT = 8000                          # visit http://<pi-ip>:8000
APP_TITLE = "Oysterfarm Status"

app = Flask(__name__)

# ---------- Helpers ----------

def iter_log_files(days: int):
    """Yield jsonl file paths for today and previous N-1 days (if present)."""
    today = datetime.now().date()
    for i in range(days):
        day = today - timedelta(days=i)
        f = LOG_DIR / f"log-{day.isoformat()}.jsonl"
        if f.exists():
            yield f

def load_data(days: int, sample: int):
    """
    Load NDJSON readings for the last `days` and return a list of dicts.
    Optional `sample` keeps every Nth row to reduce payload.
    """
    rows = []
    # Newest first in iter, but we’ll keep chronological order below.
    files = list(iter_log_files(days))
    files.sort()  # ascending by date

    keep_every = max(1, int(sample))

    idx = 0
    for path in files:
        with path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if (idx % keep_every) != 0:
                    idx += 1
                    continue
                try:
                    obj = json.loads(line)
                    # Normalize timestamp to ISO8601 if needed
                    ts = obj.get("timestamp")
                    if ts:
                        try:
                            # input like "2025-10-04 23:18:22"
                            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                            obj["timestamp_iso"] = dt.isoformat()  # local time, no TZ
                        except ValueError:
                            # if already ISO-ish, just pass through
                            obj["timestamp_iso"] = ts
                    rows.append({
                        "t": obj.get("timestamp_iso") or obj.get("timestamp"),
                        "temperature_C": obj.get("temperature_C"),
                        "humidity_%": obj.get("humidity_%"),
                        "fan_status": obj.get("fan_status"),
                        "humidifier_status": obj.get("humidifier_status")
                    })
                except json.JSONDecodeError:
                    # skip bad lines
                    pass
                idx += 1
    return rows

# ---------- Routes ----------

@app.route("/")
def index():
    # Lightweight single-page app with Chart.js
    return Response(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{APP_TITLE}</title>
<link rel="preconnect" href="https://cdn.jsdelivr.net"/>
<link rel="preconnect" href="https://cdnjs.cloudflare.com"/>
<style>
  :root {{ --fg:#0f172a; --muted:#64748b; --card:#f8fafc; --bg:#ffffff; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; color:var(--fg); background:var(--bg); }}
  header {{ padding:16px 20px; border-bottom:1px solid #e2e8f0; background:#fff; position:sticky; top:0; z-index:10; }}
  h1 {{ margin:0; font-size:20px; }}
  .container {{ padding: 16px; max-width: 1100px; margin: 0 auto; }}
  .controls {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:16px; color:var(--muted); }}
  label {{ font-size:14px; }}
  input, select {{ padding:6px 8px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; }}
  button {{ padding:8px 12px; border:1px solid #1e293b; background:#0f172a; color:white; border-radius:10px; cursor:pointer; }}
  button:disabled {{ opacity:.6; cursor:not-allowed; }}
  .grid {{ display:grid; grid-template-columns: 1fr; gap: 16px; }}
  @media(min-width: 900px) {{ .grid {{ grid-template-columns: 1fr 1fr; }} }}
  .card {{ background:var(--card); border:1px solid #e2e8f0; border-radius:16px; padding:12px; box-shadow: 0 1px 2px rgba(0,0,0,.03); }}
  canvas {{ width:100%; height:360px; }}
  footer {{ color:var(--muted); font-size:12px; padding: 16px; text-align:center; }}
</style>
</head>
<body>
  <header>
    <h1>{APP_TITLE}</h1>
  </header>
  <div class="container">
    <div class="controls">
      <label>Days:
        <select id="days">
          <option value="1">1</option>
          <option value="2" selected>2</option>
          <option value="3">3</option>
          <option value="7">7</option>
          <option value="14">14</option>
        </select>
      </label>
      <label>Sampling (keep every Nth point):
        <select id="sample">
          <option value="1" selected>1 (all)</option>
          <option value="2">2</option>
          <option value="5">5</option>
          <option value="10">10</option>
          <option value="30">30</option>
          <option value="60">60</option>
        </select>
      </label>
      <label>Auto-refresh:
        <select id="refresh">
          <option value="0">Off</option>
          <option value="5" selected>5s</option>
          <option value="10">10s</option>
          <option value="30">30s</option>
          <option value="60">60s</option>
        </select>
      </label>
      <button id="reload">Reload</button>
      <span id="status" style="margin-left:auto;">Ready</span>
    </div>

    <div class="grid">
      <div class="card">
        <h3 style="margin:0 0 8px 0;">Temperature (°C)</h3>
        <canvas id="tempChart"></canvas>
      </div>
      <div class="card">
        <h3 style="margin:0 0 8px 0;">Humidity (%RH)</h3>
        <canvas id="humChart"></canvas>
      </div>
    </div>
  </div>
  <footer>
    Served by Flask on your Raspberry Pi • Data from DHT22 NDJSON logs
  </footer>

  <!-- Chart.js + date adapter -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.umd.min.js"></script>

  <script>
    const tempCtx = document.getElementById('tempChart').getContext('2d');
    const humCtx  = document.getElementById('humChart').getContext('2d');

    const commonOpts = {{
      parsing: false,
      normalized: true,
      animation: false,
      responsive: true,
      scales: {{
        x: {{
          type: 'time',
          time: {{ tooltipFormat: 'yyyy-MM-dd HH:mm:ss' }},
          ticks: {{ maxRotation: 0, autoSkip: true }}
        }},
        y: {{ beginAtZero: false }}
      }},
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label(ctx) {{
              const y = ctx.parsed.y;
              return y !== null ? y.toFixed(1) + (ctx.chart.canvas.id === 'humChart' ? ' %' : ' °C') : '';
            }}
          }}
        }}
      }}
    }};

    const tempChart = new Chart(tempCtx, {{
      type: 'line',
      data: {{ datasets: [{{ label: 'Temperature (°C)', data: [], borderWidth: 2, pointRadius: 0 }}] }},
      options: commonOpts
    }});

    const humChart = new Chart(humCtx, {{
      type: 'line',
      data: {{ datasets: [{{ label: 'Humidity (%)', data: [], borderWidth: 2, pointRadius: 0 }}] }},
      options: commonOpts
    }});

    let timer = null;

    async function loadData() {{
      const days = document.getElementById('days').value;
      const sample = document.getElementById('sample').value;
      const status = document.getElementById('status');

      status.textContent = 'Loading…';
      try {{
        const res = await fetch(`/api/data?days=${{days}}&sample=${{sample}}`, {{ cache: 'no-store' }});
        const payload = await res.json();
        const points = payload.data;

        tempChart.data.datasets[0].data = points
          .filter(p => p.temperature_C !== null && p.temperature_C !== undefined && p.t)
          .map(p => ({{ x: p.t, y: p.temperature_C }}));
        humChart.data.datasets[0].data = points
          .filter(p => p.humidity_% !== null && p.humidity_% !== undefined && p.t)
          .map(p => ({{ x: p.t, y: p.humidity_% }}));

        tempChart.update('none');
        humChart.update('none');

        status.textContent = `Loaded ${{points.length}} points`;
      }} catch (e) {{
        console.error(e);
        status.textContent = 'Error loading data';
      }}
    }}

    function setupAutoRefresh() {{
      const refreshSel = document.getElementById('refresh');
      if (timer) {{
        clearInterval(timer);
        timer = null;
      }}
      const sec = parseInt(refreshSel.value, 10);
      if (sec > 0) {{
        timer = setInterval(loadData, sec * 1000);
      }}
    }}

    document.getElementById('reload').addEventListener('click', loadData);
    document.getElementById('days').addEventListener('change', loadData);
    document.getElementById('sample').addEventListener('change', loadData);
    document.getElementById('refresh').addEventListener('change', setupAutoRefresh);

    // Initial load
    loadData();
    setupAutoRefresh();
  </script>
</body>
</html>
""", mimetype="text/html")

@app.route("/api/data")
def api_data():
    """
    Returns JSON: {{ data: [ {{t, temperature_C, humidity_%}}, ... ] }}
    Query params:
      - days   (int, default 2): how many days of files to load
      - sample (int, default 1): keep every Nth point
    """
    try:
        days = int(request.args.get("days", "2"))
    except ValueError:
        days = 2
    try:
        sample = int(request.args.get("sample", "1"))
    except ValueError:
        sample = 1

    days = max(1, min(days, 31))   # safety bounds
    sample = max(1, sample)

    if not LOG_DIR.exists():
        return jsonify({"data": [], "error": f"Log dir {LOG_DIR} not found"}), 200

    data = load_data(days=days, sample=sample)
    return jsonify({"data": data})

# ---------- Entrypoint ----------

if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Serving {APP_TITLE} on http://{HOST}:{PORT}   (logs in {LOG_DIR.resolve()})")
    app.run(host=HOST, port=PORT, debug=False)
