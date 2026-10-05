#!/usr/bin/env python3
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, Response
from config import (
    load_config, save_config,
    get_fan_force_until, set_fan_force_until,
    get_device_override, set_device_override, DEVICE_OVERRIDE_STATES,
)

# ========= Configuration =========
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR  = BASE_DIR / "logs"                 # absolute path (reliable under systemd)
HOST, PORT = "0.0.0.0", 8000
APP_TITLE  = "Oyster Mushroom Farm Status"

app = Flask(__name__)

# ========= Helpers =========
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
    Return list of {t_iso, temperature, humidity, fan, humidifier}.
    - t_iso is ISO string (local time, no TZ)
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
                    try:
                        # "YYYY-mm-dd HH:MM:SS" -> ISO
                        t_iso = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").isoformat()
                    except ValueError:
                        t_iso = str(ts)

                rows.append({
                    "t_iso": t_iso or None,
                    "temperature": _coerce_float(obj.get("temperature_C")),
                    "humidity":    _coerce_float(obj.get("humidity_%")),
                    "fan":         _coerce_int01(obj.get("fan_status")),
                    "humidifier":  _coerce_int01(obj.get("humidifier_status")),
                })
    return rows

# ========= Routes =========
@app.route("/")
def index():
    # We use a numeric x-axis (epoch ms) so no date adapter is needed.
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
  .toggle-group {{ display:inline-flex; border:1px solid #cbd5e1; border-radius:10px; overflow:hidden; }}
  .toggle-group button {{ border:none; border-radius:0; background:#fff; color:var(--fg); padding:6px 12px; }}
  .toggle-group button + button {{ border-left:1px solid #cbd5e1; }}
  .toggle-group button.active {{ background:#0f172a; color:#fff; }}
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

    <div class="card" style="margin-bottom:16px;">
      <h3 style="margin:0 0 8px 0;">Settings</h3>
      <form id="settingsForm" class="controls" style="margin-bottom:0;">
        <label>Humidity low (%):
          <input type="number" id="hum_low" min="0" max="100" step="1" style="width:70px;">
        </label>
        <label>Humidity high (%):
          <input type="number" id="hum_high" min="0" max="100" step="1" style="width:70px;">
        </label>
        <label>Humidity purge (%):
          <input type="number" id="hum_purge" min="0" max="100" step="1" style="width:70px;">
        </label>
        <label>Fan run duration (min):
          <input type="number" id="fan_on" min="0" step="0.5" style="width:70px;">
        </label>
        <label>Fan run interval (min):
          <input type="number" id="fan_pause" min="0" step="0.5" style="width:70px;">
        </label>
        <label>Humidifier burst (min):
          <input type="number" id="humidifier_on" min="0" step="0.5" style="width:70px;">
        </label>
        <label>Humidifier pause (min):
          <input type="number" id="humidifier_pause" min="0" step="0.5" style="width:70px;">
        </label>
        <label>Max purge run (min):
          <input type="number" id="purge_max" min="0" step="1" style="width:70px;">
        </label>
        <button type="submit">Save</button>
        <span id="settingsStatus" style="margin-left:auto;"></span>
      </form>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <h3 style="margin:0 0 8px 0;">Manual fan override</h3>
      <form id="fanForceForm" class="controls" style="margin-bottom:0;">
        <label>Run fan for (min):
          <input type="number" id="fan_force_minutes" min="0" step="1" value="10" style="width:70px;">
        </label>
        <button type="submit">Force fan on</button>
        <button type="button" id="fanForceCancel" hidden>Cancel</button>
        <span id="fanForceStatus" style="margin-left:auto;"></span>
      </form>
    </div>

    <div class="card" style="margin-bottom:16px;">
      <h3 style="margin:0 0 8px 0;">Device overrides</h3>
      <div class="controls" style="margin-bottom:0;">
        <span>Fan:</span>
        <div class="toggle-group" data-device="fan">
          <button type="button" data-state="auto">Auto</button>
          <button type="button" data-state="on">On</button>
          <button type="button" data-state="off">Off</button>
        </div>
        <span>Humidifier:</span>
        <div class="toggle-group" data-device="humidifier">
          <button type="button" data-state="auto">Auto</button>
          <button type="button" data-state="on">On</button>
          <button type="button" data-state="off">Off</button>
        </div>
        <span id="overrideStatus" style="margin-left:auto;"></span>
      </div>
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
        <h3 style="margin:0 0 8px 0;">Fan</h3>
        <canvas id="fanChart"></canvas>
      </div>
      <div class="card" style="grid-column:1/-1">
        <h3 style="margin:0 0 8px 0;">Humidifier</h3>
        <canvas id="humidifierChart"></canvas>
      </div>
    </div>
  </div>
  <footer>Logs path: {LOG_DIR}</footer>

  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <script>
    function tsToMs(tiso) {{
      // Convert ISO string to epoch ms; returns NaN if invalid.
      return Date.parse(tiso);
    }}

    const commonOpts = {{
      parsing: false, normalized: true, animation: false, responsive: true,
      scales: {{
        x: {{
          type: 'linear',
          ticks: {{
            callback: (v) => {{
              const d = new Date(v);
              if (isNaN(d)) return '';
              const Y = d.getFullYear();
              const M = String(d.getMonth()+1).padStart(2,'0');
              const D = String(d.getDate()).padStart(2,'0');
              const h = String(d.getHours()).padStart(2,'0');
              const m = String(d.getMinutes()).padStart(2,'0');
              return `${{M}}-${{D}} ${{h}}:${{m}}`;
            }},
            maxRotation: 0, autoSkip: true
          }}
        }},
        y: {{ beginAtZero: false }}
      }},
      plugins: {{
        legend: {{ display: true, position: 'top' }},
        tooltip: {{
          callbacks: {{
            title(items) {{
              if (!items.length) return '';
              const d = new Date(items[0].parsed.x);
              return d.toLocaleString();
            }}
          }}
        }}
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

    function deviceChartOptions() {{
      return {{
        ...commonOpts,
        plugins: {{ ...commonOpts.plugins, legend: {{ display: false }} }},
        scales: {{
          x: commonOpts.scales.x,
          y: {{ min: 0, max: 1, ticks: {{ stepSize: 1, callback: (v) => v === 1 ? 'On' : 'Off' }} }}
        }}
      }};
    }}

    const fanChart = new Chart(document.getElementById('fanChart').getContext('2d'), {{
      type: 'line',
      data: {{ datasets: [{{
        label: 'Fan', data: [], borderWidth: 2, pointRadius: 0, stepped: true,
        fill: 'origin', backgroundColor: 'rgba(59,130,246,0.25)', borderColor: 'rgba(59,130,246,1)'
      }}] }},
      options: deviceChartOptions()
    }});

    const humidifierChart = new Chart(document.getElementById('humidifierChart').getContext('2d'), {{
      type: 'line',
      data: {{ datasets: [{{
        label: 'Humidifier', data: [], borderWidth: 2, pointRadius: 0, stepped: true,
        fill: 'origin', backgroundColor: 'rgba(16,185,129,0.25)', borderColor: 'rgba(16,185,129,1)'
      }}] }},
      options: deviceChartOptions()
    }});

    async function loadSettings() {{
      const status = document.getElementById('settingsStatus');
      try {{
        const res = await fetch('/api/config', {{ cache: 'no-store' }});
        const cfg = await res.json();
        document.getElementById('hum_low').value = cfg.hum_low;
        document.getElementById('hum_high').value = cfg.hum_high;
        document.getElementById('hum_purge').value = cfg.hum_purge;
        document.getElementById('fan_on').value = cfg.fan_on / 60;
        document.getElementById('fan_pause').value = cfg.fan_pause / 60;
        document.getElementById('humidifier_on').value = cfg.humidifier_on / 60;
        document.getElementById('humidifier_pause').value = cfg.humidifier_pause / 60;
        document.getElementById('purge_max').value = cfg.purge_max / 60;
      }} catch (e) {{
        console.error(e);
        status.textContent = 'Failed to load settings';
      }}
    }}

    document.getElementById('settingsForm').addEventListener('submit', async (e) => {{
      e.preventDefault();
      const status = document.getElementById('settingsStatus');
      status.textContent = 'Saving…';
      const payload = {{
        hum_low: parseFloat(document.getElementById('hum_low').value),
        hum_high: parseFloat(document.getElementById('hum_high').value),
        hum_purge: parseFloat(document.getElementById('hum_purge').value),
        fan_on: parseFloat(document.getElementById('fan_on').value) * 60,
        fan_pause: parseFloat(document.getElementById('fan_pause').value) * 60,
        humidifier_on: parseFloat(document.getElementById('humidifier_on').value) * 60,
        humidifier_pause: parseFloat(document.getElementById('humidifier_pause').value) * 60,
        purge_max: parseFloat(document.getElementById('purge_max').value) * 60,
      }};
      try {{
        const res = await fetch('/api/config', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload),
        }});
        const data = await res.json();
        if (!res.ok) {{
          status.textContent = data.error || 'Failed to save settings';
          return;
        }}
        status.textContent = 'Saved';
      }} catch (e) {{
        console.error(e);
        status.textContent = 'Failed to save settings';
      }}
    }});

    loadSettings();

    function fmtRemaining(sec) {{
      sec = Math.round(sec);
      const m = Math.floor(sec / 60);
      const s = sec % 60;
      return `${{m}}:${{String(s).padStart(2,'0')}}`;
    }}

    function renderFanForce(data) {{
      const status = document.getElementById('fanForceStatus');
      const cancelBtn = document.getElementById('fanForceCancel');
      if (data.forced) {{
        status.textContent = `Fan forced on — ${{fmtRemaining(data.seconds_remaining)}} remaining`;
        cancelBtn.hidden = false;
      }} else {{
        status.textContent = '';
        cancelBtn.hidden = true;
      }}
    }}

    async function loadFanForce() {{
      try {{
        const res = await fetch('/api/fan/force', {{ cache: 'no-store' }});
        renderFanForce(await res.json());
      }} catch (e) {{
        console.error(e);
      }}
    }}

    document.getElementById('fanForceForm').addEventListener('submit', async (e) => {{
      e.preventDefault();
      const status = document.getElementById('fanForceStatus');
      status.textContent = 'Starting…';
      const minutes = parseFloat(document.getElementById('fan_force_minutes').value);
      try {{
        const res = await fetch('/api/fan/force', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ minutes }}),
        }});
        const data = await res.json();
        if (!res.ok) {{
          status.textContent = data.error || 'Failed to start fan';
          return;
        }}
        renderFanForce(data);
      }} catch (e) {{
        console.error(e);
        status.textContent = 'Failed to start fan';
      }}
    }});

    document.getElementById('fanForceCancel').addEventListener('click', async () => {{
      try {{
        const res = await fetch('/api/fan/force', {{ method: 'DELETE' }});
        renderFanForce(await res.json());
      }} catch (e) {{
        console.error(e);
      }}
    }});

    loadFanForce();
    setInterval(loadFanForce, 5000);

    function renderOverrideButtons(device, state) {{
      document.querySelectorAll(`.toggle-group[data-device="${{device}}"] button`).forEach(btn => {{
        btn.classList.toggle('active', btn.dataset.state === state);
      }});
    }}

    async function loadOverride(device) {{
      try {{
        const res = await fetch(`/api/override/${{device}}`, {{ cache: 'no-store' }});
        const data = await res.json();
        renderOverrideButtons(device, data.state);
      }} catch (e) {{
        console.error(e);
      }}
    }}

    document.querySelectorAll('.toggle-group button').forEach(btn => {{
      btn.addEventListener('click', async () => {{
        const device = btn.closest('.toggle-group').dataset.device;
        const state = btn.dataset.state;
        const status = document.getElementById('overrideStatus');
        status.textContent = 'Updating…';
        try {{
          const res = await fetch(`/api/override/${{device}}`, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ state }}),
          }});
          const data = await res.json();
          if (!res.ok) {{
            status.textContent = data.error || 'Failed to update';
            return;
          }}
          renderOverrideButtons(device, data.state);
          status.textContent = '';
        }} catch (e) {{
          console.error(e);
          status.textContent = 'Failed to update';
        }}
      }});
    }});

    loadOverride('fan');
    loadOverride('humidifier');

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

        const tSeries = pts.filter(p => p.t_iso && p.temperature != null)
                           .map(p => ({{ x: tsToMs(p.t_iso), y: +p.temperature }}))
                           .filter(p => !Number.isNaN(p.x));
        const hSeries = pts.filter(p => p.t_iso && p.humidity != null)
                           .map(p => ({{ x: tsToMs(p.t_iso), y: +p.humidity }}))
                           .filter(p => !Number.isNaN(p.x));
        // pins are active-low (main.py: on=0, off=1), so invert here for display —
        // the chart's "On"/1 should mean the device is actually running
        const fanSeries = pts.filter(p => p.t_iso && p.fan != null)
                             .map(p => ({{ x: tsToMs(p.t_iso), y: 1 - (+p.fan) }}))
                             .filter(p => !Number.isNaN(p.x));
        const humiSeries = pts.filter(p => p.t_iso && p.humidifier != null)
                              .map(p => ({{ x: tsToMs(p.t_iso), y: 1 - (+p.humidifier) }}))
                              .filter(p => !Number.isNaN(p.x));

        tempChart.data.datasets[0].data = tSeries;
        humChart.data.datasets[0].data  = hSeries;
        fanChart.data.datasets[0].data  = fanSeries;
        humidifierChart.data.datasets[0].data = humiSeries;

        tempChart.update('none'); humChart.update('none');
        fanChart.update('none'); humidifierChart.update('none');

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

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(load_config())

    body = request.get_json(silent=True) or {}
    try:
        hum_low = float(body["hum_low"])
        hum_high = float(body["hum_high"])
        hum_purge = float(body["hum_purge"])
        fan_on = float(body["fan_on"])
        fan_pause = float(body["fan_pause"])
        humidifier_on = float(body["humidifier_on"])
        humidifier_pause = float(body["humidifier_pause"])
        purge_max = float(body["purge_max"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid or missing settings"}), 400

    if not (0 <= hum_low < hum_high < hum_purge <= 100):
        return jsonify({"error": "Require 0 <= humidity low < high < purge <= 100"}), 400
    if fan_on <= 0 or fan_pause <= 0:
        return jsonify({"error": "Fan timers must be positive"}), 400
    if humidifier_on <= 0 or humidifier_pause <= 0:
        return jsonify({"error": "Humidifier burst/pause times must be positive"}), 400
    if purge_max <= 0:
        return jsonify({"error": "Max purge run time must be positive"}), 400

    cfg = save_config({
        "hum_low": hum_low,
        "hum_high": hum_high,
        "hum_purge": hum_purge,
        "fan_on": fan_on,
        "fan_pause": fan_pause,
        "humidifier_on": humidifier_on,
        "humidifier_pause": humidifier_pause,
        "purge_max": purge_max,
    })
    return jsonify(cfg)

def _fan_force_status():
    until = get_fan_force_until()
    remaining = (until - time.time()) if until is not None else 0
    forced = remaining > 0
    return {
        "forced": forced,
        "until": until if forced else None,
        "seconds_remaining": max(0, remaining) if forced else 0,
    }

@app.route("/api/fan/force", methods=["GET", "POST", "DELETE"])
def api_fan_force():
    if request.method == "GET":
        return jsonify(_fan_force_status())

    if request.method == "DELETE":
        set_fan_force_until(None)
        return jsonify(_fan_force_status())

    body = request.get_json(silent=True) or {}
    try:
        minutes = float(body["minutes"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Invalid or missing 'minutes'"}), 400
    if not (0 < minutes <= 24 * 60):
        return jsonify({"error": "Minutes must be between 0 and 1440"}), 400

    set_fan_force_until(time.time() + minutes * 60)
    return jsonify(_fan_force_status())

@app.route("/api/override/<device>", methods=["GET", "POST"])
def api_override(device):
    if device not in ("fan", "humidifier"):
        return jsonify({"error": "Unknown device"}), 404

    if request.method == "GET":
        return jsonify({"state": get_device_override(device)})

    body = request.get_json(silent=True) or {}
    state = body.get("state")
    if state not in DEVICE_OVERRIDE_STATES:
        return jsonify({"error": f"state must be one of {DEVICE_OVERRIDE_STATES}"}), 400

    set_device_override(device, state)
    return jsonify({"state": state})

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

# ---- Debug endpoints ----
@app.route("/api/files")
def api_files():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    files = [str(p) for p in iter_log_files(31)]
    return jsonify({"log_dir": str(LOG_DIR), "found_files": files})

@app.route("/debug")
def debug_page():
    return Response(f"""<pre>
Title: {APP_TITLE}
Log directory: {LOG_DIR}
Files found (last 31d):
{chr(10).join(str(p) for p in iter_log_files(31))}

Try:
  /api/files
  /api/data?days=2&sample=30
</pre>""", mimetype="text/plain")

# ========= Entrypoint =========
if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Serving {APP_TITLE} on http://{HOST}:{PORT}")
    print(f"Logs directory: {LOG_DIR}")
    app.run(host=HOST, port=PORT, debug=False)
