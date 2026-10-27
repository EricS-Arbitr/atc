#!/usr/bin/env python3
"""Deterministic ATC schedule generator.

Builds schedule.json from route templates seeded from airfield.yml, so the feed
has dense, repeatable traffic across the whole exercise cycle instead of the
3-flight sample's ~15-minute burst.

Produces the expanded flight schema the feed + FDP consume: callsign, icao_hex
(synthetic AE-range), squawk, ac_type, category, flight_rule, heavy/fuel,
departure_offset_s (absolute in the cycle), and waypoints
[{lat,lon,alt_ft,gs_kt,offset_s,on_ground}] with offset_s relative to departure.

Deterministic: same seed -> byte-identical schedule. Continuous presence is
guaranteed by staggered orbit "shifts" that tile the cycle, plus discrete
arrivals/departures/patterns for texture.

Usage:
    python3 generate_schedule.py --airfield airfield.yml --cycle 172800 \
        --seed 20260101 --interval 1500 --out schedule.json
"""
import argparse
import json
import math
import os
import random

# (ac_type, category, heavy, fuel_gal, callsign_prefix, cruise_kt, app_kt)
FLEET = [
    ("C-17",   "heavy",  True,  5000, "RCH",  330, 230),
    ("KC-135", "heavy",  True, 10000, "PAT",  320, 220),
    ("C-130",  "medium", False,   0,  "RCH",  260, 170),
    ("F-16",   "fast",   False,   0,  "VIPER",420, 200),
    ("C-172",  "light",  False,   0,  "N",    110,  70),
    ("UH-60",  "helo",   False,   0,  "ARMY", 120,  80),
]


def point(lat, lon, brg_deg, dist_nm):
    """Equirectangular offset — fine at terminal-area scale."""
    b = math.radians(brg_deg)
    dlat = (dist_nm / 60.0) * math.cos(b)
    dlon = (dist_nm / 60.0) * math.sin(b) / math.cos(math.radians(lat))
    return round(lat + dlat, 5), round(lon + dlon, 5)


def callsign(rng, prefix):
    if prefix == "N":
        return f"N{rng.randint(100,999)}{rng.choice('ABCDEGHJKLMPRSTUVWXYZ')}{rng.choice('ABCDEGHJKLMPRSTUVWXYZ')}"
    return f"{prefix}{rng.randint(1,99):02d}" if prefix in ("VIPER", "ARMY", "PAT") \
        else f"{prefix}{rng.randint(100,999)}"


def squawk(rng):
    # VFR 1200 for light, else a discrete beacon code
    return "1200" if rng.random() < 0.15 else f"{rng.randint(1,6)}{rng.randint(0,7)}{rng.randint(0,7)}{rng.randint(0,7)}"


def arrival(af, rng, ac):
    brg = rng.uniform(0, 360)
    elev = af["field_elev_ft"]
    p0 = point(af["lat"], af["lon"], brg, 25)
    p1 = point(af["lat"], af["lon"], brg, 10)
    return [
        {"lat": p0[0], "lon": p0[1], "alt_ft": 9000, "gs_kt": ac[6] + 60, "offset_s": 0,   "on_ground": False},
        {"lat": p1[0], "lon": p1[1], "alt_ft": 3000, "gs_kt": ac[6],      "offset_s": 360, "on_ground": False},
        {"lat": af["lat"], "lon": af["lon"], "alt_ft": elev, "gs_kt": 0,  "offset_s": 720, "on_ground": True},
    ]


def departure(af, rng, ac, rwy_hdg):
    elev = af["field_elev_ft"]
    p1 = point(af["lat"], af["lon"], rwy_hdg, 10)
    p2 = point(af["lat"], af["lon"], rwy_hdg, 25)
    return [
        {"lat": af["lat"], "lon": af["lon"], "alt_ft": elev, "gs_kt": 0,       "offset_s": 0,   "on_ground": True},
        {"lat": p1[0], "lon": p1[1], "alt_ft": 4000,  "gs_kt": ac[6],          "offset_s": 300, "on_ground": False},
        {"lat": p2[0], "lon": p2[1], "alt_ft": 12000, "gs_kt": ac[5],          "offset_s": 720, "on_ground": False},
    ]


def pattern(af, rng, ac, rwy_hdg):
    elev, pa = af["field_elev_ft"], af["field_elev_ft"] + af.get("pattern_alt_ft_agl", 1000)
    dw = point(af["lat"], af["lon"], (rwy_hdg + 90) % 360, 1.5)
    base = point(af["lat"], af["lon"], (rwy_hdg + 180) % 360, 2.0)
    return [
        {"lat": af["lat"], "lon": af["lon"], "alt_ft": elev, "gs_kt": 0,  "offset_s": 0,    "on_ground": True},
        {"lat": dw[0], "lon": dw[1],   "alt_ft": pa,   "gs_kt": ac[6], "offset_s": 240,  "on_ground": False},
        {"lat": base[0], "lon": base[1], "alt_ft": pa, "gs_kt": ac[6], "offset_s": 480,  "on_ground": False},
        {"lat": af["lat"], "lon": af["lon"], "alt_ft": elev, "gs_kt": 0, "offset_s": 900, "on_ground": True},
    ]


def orbit(af, rng, ac, dur):
    """A racetrack orbit near the field, airborne for `dur` seconds."""
    alt = rng.choice([18000, 22000, 25000])
    legs, step = [], 300
    n = max(dur // step, 4)
    for i in range(int(n) + 1):
        brg = (i * 40) % 360
        p = point(af["lat"], af["lon"], brg, 12)
        legs.append({"lat": p[0], "lon": p[1], "alt_ft": alt, "gs_kt": ac[5],
                     "offset_s": i * step, "on_ground": False})
    return legs


def make_flight(af, rng, n, dep_off, kind, dur_orbit=0):
    ac = rng.choice(FLEET)
    rwy = rng.choice(af["runways"])["true_hdg"]
    if kind == "arrival":
        wps, rule = arrival(af, rng, ac), "inbound"
    elif kind == "departure":
        wps, rule = departure(af, rng, ac, rwy), "outbound"
    elif kind == "pattern":
        ac = rng.choice([a for a in FLEET if a[1] in ("light", "helo")])
        wps, rule = pattern(af, rng, ac, rwy), "local"
    else:  # orbit — tankers/fighters/transports loiter, not light/helo
        ac = rng.choice([a for a in FLEET if a[1] in ("heavy", "fast", "medium")])
        wps, rule = orbit(af, rng, ac, dur_orbit), "local"
    fl = {
        "callsign": callsign(rng, ac[4]),
        "icao_hex": f"AE{n:04X}",
        "squawk": squawk(rng),
        "ac_type": ac[0], "category": ac[1], "flight_rule": rule,
        "destination": af["ident_icao"] if rule == "inbound" else "KADW",
        "origin": af["ident_icao"] if rule != "inbound" else "KADW",
        "heavy": ac[2], "departure_offset_s": dep_off, "waypoints": wps,
    }
    if ac[2] and ac[3]:
        fl["fuel_request_gal"] = rng.randint(int(ac[3] * 0.8), ac[3])
    return fl


def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--airfield", default=os.path.join(here, "airfield.yml"))
    ap.add_argument("--cycle", type=int, default=172800)
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--interval", type=int, default=1500,
                    help="mean seconds between discrete movements")
    ap.add_argument("--orbit-shift", type=int, default=10800, help="orbit shift length (s)")
    ap.add_argument("--out", default=os.path.join(here, "schedule.json"))
    a = ap.parse_args()

    # Minimal YAML read (airfield.yml is flat under `airfield:`) without PyYAML dep.
    try:
        import yaml
        af = yaml.safe_load(open(a.airfield))["airfield"]
    except ImportError:
        af = _mini_airfield(a.airfield)

    rng = random.Random(a.seed)
    flights, n = [], 1

    # Orbit shifts tile the cycle so >=1 aircraft is always airborne.
    t = 0
    while t < a.cycle:
        dur = min(a.orbit_shift, a.cycle - t)
        if dur >= 1200:
            flights.append(make_flight(af, rng, n, t, "orbit", dur_orbit=dur))
            n += 1
        t += a.orbit_shift

    # Discrete movements (arrival/departure/pattern) jittered around `interval`.
    t = 0
    kinds = ["arrival", "departure", "arrival", "departure", "pattern"]
    while t < a.cycle:
        kind = rng.choice(kinds)
        fl = make_flight(af, rng, n, t, kind)
        if t + fl["waypoints"][-1]["offset_s"] <= a.cycle:
            flights.append(fl)
            n += 1
        t += int(rng.uniform(a.interval * 0.5, a.interval * 1.5))

    flights.sort(key=lambda f: f["departure_offset_s"])
    out = {"_generated": {"seed": a.seed, "cycle_s": a.cycle, "flights": len(flights)},
           "flights": flights}
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"wrote {a.out}: {len(flights)} flights over {a.cycle}s "
          f"(seed {a.seed})")


def _mini_airfield(path):
    """Tiny parser for the flat airfield.yml if PyYAML is unavailable."""
    af, cur = {}, None
    for line in open(path):
        s = line.split("#", 1)[0].rstrip()
        if not s.strip() or s.strip() == "airfield:":
            continue
        if s.lstrip().startswith("- {"):
            af.setdefault("runways", []).append(
                eval(s.lstrip()[2:], {"__builtins__": {}}))
            continue
        if ":" in s:
            k, v = [x.strip() for x in s.split(":", 1)]
            if v in ("", "[]"):
                continue
            try:
                af[k] = int(v)
            except ValueError:
                try:
                    af[k] = float(v)
                except ValueError:
                    af[k] = v.strip('"')
    return af


if __name__ == "__main__":
    main()
