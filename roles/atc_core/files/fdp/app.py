#!/usr/bin/env python3
"""Flight Data Processor (dev stub).

Reads readsb's aircraft.json (live decoded feed) and serves electronic flight
strips + a combined radar/strips ops page for the CWP kiosk. Landing detection
and the fuel-requisition trigger (design §4C/§4D) are stubbed and gated.

TODO:
  * Persist strips/landings to SQLite (config.db); add the reset path.
  * Landing detection from aircraft.json (alt/gs/on-ground transition at field)
    -> on a HEAVY landing, POST to fuel_requisition_url when enabled.
  * RANGE-VULN (gated by vulns_enabled, default false): SQLi in the strip
    filter, unauthenticated /api/update_squawk. Mark each `# RANGE-VULN:` and
    document in docs/atc_instructor_answer_key.md.
  * Embed tar1090 in the ops page (split radar + strips); real styling.
"""
import argparse
import json
import os

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
CFG = {}


def _aircraft():
    path = CFG.get("aircraft_json", "")
    try:
        with open(path) as fh:
            return json.load(fh).get("aircraft", [])
    except (OSError, ValueError):
        return []


OPS_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Blackstone AUX — ATC</title>
<style>body{background:#0b0f14;color:#cfe3ff;font:14px monospace;margin:0}
.wrap{display:flex;height:100vh}.scope{flex:3;border-right:1px solid #1d2a3a}
.strips{flex:2;padding:12px;overflow:auto}.scope iframe{width:100%;height:100%;border:0}
h2{color:#6fb3ff;margin:0 0 8px}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #1d2a3a;padding:4px;text-align:left}</style>
</head><body><div class="wrap">
<div class="scope">
{% if tar %}<iframe src="{{ tar }}"></iframe>
{% else %}<div style="padding:12px"><h2>RADAR — {{ af.ident_icao }}</h2>
<p>tar1090 URL not configured.</p></div>{% endif %}</div>
<div class="strips"><h2>FLIGHT STRIPS — {{ af.ident_icao }}</h2>
<table><thead><tr><th>Callsign</th><th>Hex</th><th>Alt</th><th>GS</th><th>Squawk</th></tr></thead>
<tbody id="strips"></tbody></table>
<p id="foot" style="color:#5a7694">loading…</p></div></div>
<script>
// Refresh ONLY the strips (not the tar1090 iframe) every 2s.
async function tick(){
  try{
    const ac = await (await fetch('/api/strips')).json();
    document.getElementById('strips').innerHTML = ac.map(a =>
      `<tr><td>${a.flight||''}</td><td>${a.hex||''}</td><td>${a.alt_baro||''}</td>`+
      `<td>${a.gs||''}</td><td>${a.squawk||''}</td></tr>`).join('');
    document.getElementById('foot').textContent = `updated every 2s · ${ac.length} tracked`;
  }catch(e){ document.getElementById('foot').textContent = 'feed unreachable'; }
}
tick(); setInterval(tick, 2000);
</script></body></html>"""


@app.route("/")
def ops():
    return render_template_string(OPS_PAGE, af=CFG.get("airfield", {}),
                                  tar=CFG.get("tar1090_url", ""))


@app.route("/api/strips")
def strips():
    return jsonify(_aircraft())


@app.route("/healthz")
def healthz():
    return jsonify(status="ok", vulns=CFG.get("vulns_enabled", False),
                   count=len(_aircraft()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    CFG = json.load(open(ap.parse_args().config))
    app.run(host="0.0.0.0", port=int(CFG.get("port", 8080)))
