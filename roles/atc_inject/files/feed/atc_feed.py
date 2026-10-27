#!/usr/bin/env python3
"""ATC synthetic ADS-B feed engine (dev stub).

Emits SBS/BaseStation messages over TCP, bound to all interfaces, accepting
multiple concurrent clients. The exercise clock is EPOCH-BASED so it survives
restarts and stays aligned range-wide:

    cycle_position = (now_utc - epoch) % cycle_seconds

STATUS: working stub. It interpolates each flight linearly between waypoints
and emits SBS MSG type 1 (ident), 3 (position) and 4 (velocity) so readsb
shows callsign/alt/speed. Good enough to drive readsb + tar1090 + the FDP.

TODO(design §4A/§4B, Phase target):
  * Beast-format DF17 extended squitter on beast_port (real ADS-B frames) so
    defenders work genuine ADS-B, not decoded text. readsb then uses beast_in.
  * Mode-A squawk over the Mode S path; scripted events (7700 etc.).
  * Cycle-wrap gap handling (retire airborne tracks cleanly at wrap).
  * Replace linear interpolation with great-circle + turn/climb profiles.
  * Optional independent primary-radar/MLAT feed (atc_primary_radar_enabled).
"""
import argparse
import json
import socket
import threading
import time
from datetime import datetime, timezone


def _parse_epoch(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


class Clients:
    """Fan-out to all connected TCP clients; drop the dead ones."""

    def __init__(self):
        self._socks = []
        self._lock = threading.Lock()

    def add(self, sock):
        with self._lock:
            self._socks.append(sock)

    def broadcast(self, line: bytes):
        with self._lock:
            dead = []
            for s in self._socks:
                try:
                    s.sendall(line)
                except OSError:
                    dead.append(s)
            for s in dead:
                self._socks.remove(s)
                try:
                    s.close()
                except OSError:
                    pass


def _accept_loop(server: socket.socket, clients: Clients):
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            break
        clients.add(conn)


def _interp(wps, t):
    """Linear interpolate (lat, lon, alt_ft, gs_kt) at offset t seconds."""
    if not wps:
        return None
    if t <= wps[0]["offset_s"]:
        return wps[0]
    for a, b in zip(wps, wps[1:]):
        if a["offset_s"] <= t <= b["offset_s"]:
            span = (b["offset_s"] - a["offset_s"]) or 1
            f = (t - a["offset_s"]) / span
            return {
                "lat": a["lat"] + (b["lat"] - a["lat"]) * f,
                "lon": a["lon"] + (b["lon"] - a["lon"]) * f,
                "alt_ft": a["alt_ft"] + (b["alt_ft"] - a["alt_ft"]) * f,
                "gs_kt": a.get("gs_kt", 0) + (b.get("gs_kt", 0) - a.get("gs_kt", 0)) * f,
            }
    return wps[-1]


def _sbs(mtype, hexid, rest):
    """One SBS/BaseStation CSV line. `mtype` is the transmission type (field 2,
    REQUIRED — readsb drops the record without it). `rest` is the 12 trailing
    fields 11..22 (Callsign, Altitude, GroundSpeed, Track, Lat, Lon,
    VerticalRate, Squawk, Alert, Emergency, SPI, IsOnGround)."""
    gen = datetime.now(timezone.utc)
    ds = gen.strftime("%Y/%m/%d")
    ts = gen.strftime("%H:%M:%S.000")
    base = ["MSG", str(mtype), "1", "1", hexid, "1", ds, ts, ds, ts]
    return (",".join(base + rest) + "\r\n").encode()


def run(cfg):
    epoch = _parse_epoch(cfg["exercise_epoch"])
    cycle = cfg["cycle_seconds"]
    flights = json.load(open(cfg["schedule"]))["flights"]
    period = 1.0 / max(cfg.get("rate_hz", 1), 1)

    clients = Clients()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((cfg["bind"], cfg["sbs_port"]))
    srv.listen(16)
    threading.Thread(target=_accept_loop, args=(srv, clients), daemon=True).start()
    print(f"[atc_feed] SBS on {cfg['bind']}:{cfg['sbs_port']} "
          f"({len(flights)} flights, {cycle}s cycle)", flush=True)

    while True:
        pos_in_cycle = (time.time() - epoch) % cycle
        for fl in flights:
            dep = fl.get("departure_offset_s", 0)
            wps = fl.get("waypoints", [])
            if not wps:
                continue
            t = pos_in_cycle - dep
            if t < wps[0]["offset_s"] or t > wps[-1]["offset_s"]:
                continue   # not airborne this instant
            p = _interp(wps, t)
            if p is None:
                continue
            hexid = fl["icao_hex"]
            on_gnd = "1" if p.get("alt_ft", 0) <= wps[0]["alt_ft"] + 50 else "0"
            # MSG1 identification: callsign (field 11)
            clients.broadcast(_sbs(1, hexid, [fl["callsign"]] + [""] * 11))
            # MSG3 airborne position: altitude (12), lat (15), lon (16), onground (22)
            clients.broadcast(_sbs(3, hexid, ["", str(int(p["alt_ft"])), "", "",
                                              f"{p['lat']:.5f}", f"{p['lon']:.5f}",
                                              "", fl.get("squawk", ""), "", "", "", on_gnd]))
            # MSG4 velocity: ground speed (13)
            clients.broadcast(_sbs(4, hexid, ["", "", str(int(p["gs_kt"])), "",
                                              "", "", "", "", "", "", "", ""]))
        time.sleep(period)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    cfg = json.load(open(ap.parse_args().config))
    run(cfg)
