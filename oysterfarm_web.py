#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response

# ====== Config ======
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "logs"                 # absolute path, reliable under systemd
HOST, PORT = "0.0.0.0", 8000
APP_TITLE  = "Oyster Mushroom Farm Status"   # your title

app = Flask(__name__)

# ====== Helpers ======
def iter_log_files(days: int):
    """Yield existing log-YYYY-MM-DD.jsonl files (oldest→newest) for last N days."""
    today = datetime.now().date()
    files = []
    for i in range(days):
        day = today - timedelta(days=i)
        f = LOG_DIR / f"log-{day.isoformat()}.jsonl"
        if f.exists():
            files.append(f)
    files.sort()
    return files

def _coerce_float(x):
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def _coerce_int01(x):
    if x in (0, 1):
        return int(x)
    if isinstance(x, bool):
        return 1 if x else 0
    try:
        v = int(x)
        return 1 if v != 0 else 0
    except (TypeError, ValueError):
        return None

def load_data(days: int, sample: int):
    """
    Return list of {t, temperature, humidity, fan, humidifier}.
    - t is ISO string
    - values are floats (temp/hum) or 0/1 (fan/humidifier)
    - keeps every Nth row (sample)
    """
    rows = []
    keep_every = max(1, int(sample))
    idx = 0

    for path in iter_log_files(days):
        with path.open("r") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                if (idx % keep_every) != 0:
                    idx += 1
                    continue
                idx += 1
                try:
                    obj = json.loads(s)
                except json.JSONDecodeError:
                    continue

                # timestamp normalization
                ts = obj.get("timestamp")
                t_iso = None
                if ts:
                    # Try "YYYY-mm-dd HH:MM:SS" first, else pass through
                    try:
                        t_iso = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").isoformat()
                    except ValueError:
                        t_iso = str(ts)

                rows.append({
                    "t": t_iso or None,
                    "temperature": _coerce_float(obj.get("temperature_C")),
                    "humidity":    _coerce_float(obj.get("humidity_%")),
                    "fan":         _coerce_int01(obj.get("fan_status")),
                    "humidifier":  _coerce_int01(obj.get("humidifier_status")),
                })
    return rows

# ====== Routes ======
@app.route("/")
def index():
    return Response(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{APP_TITLE}</title>
<style>
  :root {{ --fg:#0f172a; --muted:#64748b; --card:#f8fafc; --bg:#ffffff; }}
  * {{ box-sizing:border-box }}
  body {{ margin:0; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; color:var(--fg); background:var(--bg); }}
  header {{ padding:16px 20px; border-bottom:1px solid #e2e8f0; background:#fff; position:sticky; top:0; z-index:10; }}
  h1 {{ margin:0; font-size:20px; }}
  .container {{ padding:16px; max-width:1100px; margin:0 auto; }}
  .controls {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:16px; color:var(--muted); }}
  label {{ font-size:14px; }}
  select {{ padding:6px 8px; border:1px solid #cbd5e1; border-radius:8px; font-size:14px; }}
  button {{ padding:8px 12px; border:1px solid #1e293b; background:#0f172a; color:#fff; border-radius:10px; cursor:pointer; }}
  .grid {{ display:grid; grid-template-columns:1fr; gap:16px; }}
  @media(min-width:900px) {{ .grid {{ grid-template-columns:1fr 1fr; }} }}
  .card {{ background:var(--card); border:1px solid #e2e8f0; border-radius:16px; padding:12px; box-shadow:0 1px 2px rgba(0,0,0,.03); }}
  canvas {{ width:100%; height:360px; }}
  footer {{ color:var(--muted); font-size:12px; padding:16px; text-align:center; }}
</style>
</head>
<body>
  <header><h1>{APP_TITLE}</h1></header>
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
      <label>Sampling:
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
      <div class="card" style="grid-column:1/-1">
        <h3 style="margin:0 0 8px 0;">Devices (on/off)</h3>
        <canvas id="devChart"></canvas>
      </div>
    </div>
  </div>
  <footer>Logs path: {LOG_DIR}</footer>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.umd.min.js"></script>
  <script>
    const commonOpts = {{
      parsing: false, normalized: true, animation: false, responsive: true,
      scales: {{
        x: {{ type: 'time', time: {{ tooltipFormat: 'yyyy-MM-dd HH:mm:ss' }}, ticks: {{ maxRotation: 0, autoSkip: true }} }},
        y: {{ beginAtZero: false }}
      }},
      plugins: {{
        legend: {{ display: true, position: 'top' }},
        tooltip: {{ mode: 'nearest', intersect: false }}
      }}
    }};

    const tempChart = new Chart(document.getElementById('tempChart').getContext('2d'), {{
      type: 'line',
      data: {{ datasets: [{{ label: 'Temperature (°C)', data: [], borderWidth: 2, pointRadius: 0 }}] }},
      options: commonOpts
    }});

    const humChart = new Chart(document.getElementById('humChart').getContext('2d'), {{
      type: 'line',
      data: {{ datasets: [{{ label: 'Humidity (%)', data: [], borderWidth: 2, pointRadius: 0 }}] }},
      options: commonOpts
    }});

    const devChart = new Chart(document.getElementById('devChart').getContext('2d'), {{
      type: 'line',
      data: {{ datasets: [
        {{ label: 'Fan', data: [], borderWidth: 2, pointRadius: 0, stepped: true }},
        {{ label: 'Humidifier', data: [], borderWidth: 2, pointRadius: 0, stepped: true }}
      ]}},
      options: {{
        ...commonOpts,
        scales: {{
          x: commonOpts.scales.x,
          y: {{ min: 0, max: 1, ticks: {{ stepSize: 1 }} }}
        }}
      }}
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
        const pts = payload.data || [];

        const tSeries = pts.filter(p => p.t && p.temperature !== null && p.temperature !== undefined)
                           .map(p => ({{ x: p.t, y: p.temperature }}));
        const hSeries = pts.filter(p => p.t && p.humidity !== null && p.humidity !== undefined)
                           .map(p => ({{ x: p.t, y: p.humidity }}));
        const fanSeries = pts.filter(p => p.t && p.fan !== null && p.fan !== undefined)
                             .map(p => ({{ x: p.t, y: +p.fan }}));
        const humiSeries = pts.filter(p => p.t && p.humidifier !== null && p.humidifier !== undefined)
                              .map(p => ({{ x: p.t, y: +p.humidifier }}));

        tempChart.data.datasets[0].data = tSeries;
        humChart.data.datasets[0].data  = hSeries;
        devChart.data.datasets[0].data  = fanSeries;
        devChart.data.datasets[1].data  = humiSeries;

        tempChart.update('none'); humChart.update('none'); devChart.update('none');

        status.textContent = pts.length ? `Loaded ${{pts.length}} points` : 'No data found';
      }} catch (e) {{
        console.error(e);
        status.textContent = 'Error loading data';
      }}
    }}

    function setupAutoRefresh() {{
      if (timer) {{ clearInterval(timer); timer = null; }}
      const sec = parseInt(document.getElementById('refresh').value, 10);
      if (sec > 0) {{ timer = setInterval(loadData, sec * 1000); }}
    }}

    document.getElementById('reload').addEventListener('click', loadData);
    document.getElementById('days').addEventListener('change', loadData);
    document.getElementById('sample').addEventListener('change', loadData);
    document.getElementById('refresh').addEventListener('change', setupAutoRefresh);

    loadData();
    setupAutoRefresh();
  </script>
</body>
</html>
""", mimetype="text/html")

@app.route("/api/data")
def api_data():
    try:
        days = int(request.args.get("days", "2"))
    except ValueError:
        days = 2
    try:
        sample = int(request.args.get("sample", "1"))
    except ValueError:
        sample = 1

    days = max(1, min(days, 31))
    sample = max(1, sample)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    data = load_data(days=days, sample=sample)
    return jsonify({"data": data})

# ---- Debug utilities ----
@app.route("/api/files")
def api_files():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    files = [str(p) for p in iter_log_files(31)]
    return jsonify({"log_dir": str(LOG_DIR), "found_files": files})

@app.route("/debug")
def debug_page():
    return Response(f"""<pre>
Log directory: {LOG_DIR}
Files found (last 31d):
{chr(10).join(str(p) for p in iter_log_files(31))}
Try the data API:
  /api/data?days=2&sample=30
  /api/files
</pre>""", mimetype="text/plain")

# ====== Entrypoint ======
if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Serving {APP_TITLE} on http://{HOST}:{PORT}")
    print(f"Logs directory: {LOG_DIR}")
    app.run(host=HOST, port=PORT, debug=False)
