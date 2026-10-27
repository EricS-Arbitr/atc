#!/usr/bin/env python3
"""Deterministic schedule generator (STUB).

10 hand-typed flights do not fill a 48 h cycle; a realistic shift is ~15-25
movements/day. This builds schedule.json from route templates (arrival to each
runway end, departure, closed-pattern work, orbits/holds) seeded from
airfield.yml, so movements are repeatable.

TODO(design §4A): implement the templates + a seeded RNG; emit the expanded
schema (origin/dest, heavy/fuel flags, on_ground, scripted squawk/emergency
events). For now Phase 1 uses the committed sample schedule.json fixture.

Usage (once implemented):
    python3 generate_schedule.py --airfield airfield.yml --hours 48 --seed 20260101 \
        --out schedule.json
"""
import argparse
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--airfield", default="airfield.yml")
    ap.add_argument("--hours", type=int, default=48)
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--out", default="schedule.json")
    ap.parse_args()
    print("generate_schedule.py is a stub — see TODO. Using the committed "
          "sample schedule.json for Phase 1.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
