#!/usr/bin/env python3
"""Weather (METAR) feed (dev stub).

Serves a deterministic METAR for the field over HTTP so the ATC display has a
weather consumer and the weather-denial scenario has an observable effect. The
observation cycles on the same epoch-based clock as the ADS-B feed.

TODO: TAF, NEXRAD replay, realistic hourly sequences; the full build is a
separate weather-radar sheet. This is the minimum ATC needs to consume.
"""
import argparse
import json
import time
from datetime import datetime, timezone

from flask import Flask, jsonify

app = Flask(__name__)
CFG = {}

# A short deterministic rotation of conditions, indexed by hour-of-cycle.
_SEQ = [
    "{st} {dd}{hh}51Z {wind} 10SM FEW040 24/12 A3002",
    "{st} {dd}{hh}51Z {wind} 8SM SCT030 BKN100 22/14 A2998",
    "{st} {dd}{hh}51Z {wind} 4SM BR OVC008 18/16 A2995",
    "{st} {dd}{hh}51Z {wind} 2SM -RA OVC006 17/16 A2990",
]


def _metar():
    now = datetime.now(timezone.utc)
    cyc = CFG.get("cycle_seconds", 172800)
    hour = int((time.time() % cyc) // 3600)
    tmpl = _SEQ[hour % len(_SEQ)]
    wind = ["18008KT", "21012KT", "09006KT", "27015G22KT"][hour % 4]
    return tmpl.format(st=CFG.get("station", "KBAX"),
                       dd=now.strftime("%d"), hh=now.strftime("%H"), wind=wind)


@app.route("/metar")
def metar():
    return jsonify(station=CFG.get("station"), raw=_metar())


@app.route("/healthz")
def healthz():
    return jsonify(status="ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    CFG = json.load(open(ap.parse_args().config))
    app.run(host="0.0.0.0", port=int(CFG.get("port", 8081)))
