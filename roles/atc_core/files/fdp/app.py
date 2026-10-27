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
.wrap{display:flex;height:100vh}.scope,.strips{flex:1;padding:12px;overflow:auto}
.scope{border-right:1px solid #1d2a3a}h2{color:#6fb3ff}
table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #1d2a3a;padding:4px;text-align:left}</style>
</head><body><div class="wrap">
<div class="scope"><h2>RADAR — {{ af.ident_icao }}</h2>
<p>tar1090 embeds here (TODO). Field {{ af.lat }},{{ af.lon }} elev {{ af.field_elev_ft }}ft.</p></div>
<div class="strips"><h2>FLIGHT STRIPS</h2>
<table><tr><th>Callsign</th><th>Hex</th><th>Alt</th><th>GS</th><th>Squawk</th></tr>
{% for a in ac %}<tr><td>{{ a.get('flight','') }}</td><td>{{ a.get('hex','') }}</td>
<td>{{ a.get('alt_baro','') }}</td><td>{{ a.get('gs','') }}</td><td>{{ a.get('squawk','') }}</td></tr>{% endfor %}
</table></div></div>
<script>setTimeout(()=>location.reload(),2000)</script></body></html>"""


@app.route("/")
def ops():
    return render_template_string(OPS_PAGE, ac=_aircraft(), af=CFG.get("airfield", {}))


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
