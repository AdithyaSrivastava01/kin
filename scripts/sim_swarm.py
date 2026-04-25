"""Synthetic swarm event generator for the dashboard.

Emits the agent-graph events that E1's swarm-* agents will eventually
produce — pulled from real MongoDB data so the dashboard tells a
believable story even before E1 ships.

Skipped on purpose:
  - LanguageDetected, CallStarted, BookingResult — E2's voice gateway
    produces these for real (see voice_gateway/main.py:239).

Usage:
    python scripts/sim_swarm.py                 # one run, joon-001
    python scripts/sim_swarm.py --patient maria-001
    python scripts/sim_swarm.py --loop          # run forever, every ~30s
    python scripts/sim_swarm.py --speed 0.3     # 30% of normal step gaps
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

RELAY = os.getenv("TELEMETRY_RELAY_URL", "http://localhost:3001/telemetry")

# Specialty hints per patient — lets the sim choose a realistic query for
# each persona without hardcoding everything.
PATIENT_SCENARIO = {
    "joon-001":  {"specialty": "dermatologist", "ask": "for a dermatologist near Koreatown"},
    "maria-001": {"specialty": "clinic",        "ask": "to see her primary care doctor"},
    "rahul-001": {"specialty": "cardiologist",  "ask": "for a cardiology follow-up"},
}


@dataclass
class Event:
    src: str
    dst: str
    kind: str
    payload: dict
    delay: float  # seconds to sleep BEFORE emitting


def build_scenario(db, patient_id: str) -> list[Event]:
    """Pull real data and assemble the agent-graph event sequence."""
    p = db.patients.find_one({"patient_id": patient_id})
    if not p:
        raise SystemExit(f"patient {patient_id!r} not found in MongoDB")

    scenario = PATIENT_SCENARIO.get(patient_id, {"specialty": "clinic", "ask": "for an appointment"})
    specialty = scenario["specialty"]

    # Real geo query — same one swarm-finder will run
    candidates = list(db.clinics.find({
        "specialty": specialty,
        "location": {"$near": {
            "$geometry": p["location"],
            "$maxDistance": 15_000,
        }},
    }).limit(5))

    # Insurance match — real lookup against insurance_map collection
    insured = []
    for c in candidates:
        m = db.insurance_map.find_one({"clinic_name": c["name"]})
        accepted = m and p["insurance"]["provider"] in m.get("accepts", [])
        if accepted:
            insured.append(c)
    matched = (insured or candidates)[0] if (insured or candidates) else None

    events: list[Event] = [
        Event("patient", "swarm-intake", "AppointmentRequest", {
            "patient_id": patient_id,
            "query": f"{p['name']} needs an appointment {scenario['ask']}.",
            "language": p["primary_language"],
        }, delay=0.0),

        # Fan out to profiler + finder in parallel (small gap)
        Event("swarm-intake", "swarm-profiler", "ChatMessage", {
            "patient_id": patient_id,
        }, delay=0.6),
        Event("swarm-intake", "swarm-finder", "ChatMessage", {
            "specialty": specialty,
            "lat": p["location"]["coordinates"][1],
            "lon": p["location"]["coordinates"][0],
            "radius_km": 15,
        }, delay=0.1),

        # Profiler returns first (Mongo lookup is fast)
        Event("swarm-profiler", "swarm-intake", "ProfileLoaded", {
            "name": p["name"],
            "language": p["primary_language"],
            "insurance": p["insurance"]["provider"],
            "allergies": p.get("allergies", []),
            "medications": [m["name"] for m in p.get("medications", [])],
        }, delay=0.9),

        # Finder returns slightly later (Overpass-style search took longer)
        Event("swarm-finder", "swarm-intake", "CandidatesFound", {
            "specialty": specialty,
            "count": len(candidates),
            "top": [c["name"] for c in candidates[:3]],
        }, delay=1.4),

        # Hand off to matcher
        Event("swarm-intake", "swarm-matcher", "ChatMessage", {
            "candidates": [c["name"] for c in candidates[:3]],
            "language": p["primary_language"],
            "insurance": p["insurance"]["provider"],
        }, delay=0.7),

        # Matcher picks the winner
        Event("swarm-matcher", "swarm-intake", "ClinicMatched", {
            "clinic": matched["name"] if matched else None,
            "address": (matched or {}).get("address"),
            "phone": (matched or {}).get("phone") or "+1-555-DEMO",
            "score": round(random.uniform(0.78, 0.96), 2),
            "rationale": "specialty + insurance + proximity",
        }, delay=1.1),

        # Hand the booking task to swarm-caller (E2's voice gateway will
        # take it from here in a real run)
        Event("swarm-intake", "swarm-caller", "ChatMessage", {
            "clinic": matched["name"] if matched else None,
            "phone": (matched or {}).get("phone") or "+1-555-DEMO",
            "language": p["primary_language"],
            "patient_name": p["name"],
            "specialty": specialty,
        }, delay=0.8),
    ]
    return events


def run_once(events: list[Event], speed: float = 1.0) -> int:
    sent = 0
    failed = 0
    for evt in events:
        time.sleep(evt.delay * speed)
        try:
            r = requests.post(RELAY, json={
                "src": evt.src, "dst": evt.dst,
                "kind": evt.kind, "payload": evt.payload,
            }, timeout=2)
            ok = r.ok
        except Exception as e:
            print(f"  [warn] beacon failed: {e!r}")
            ok = False
        if ok:
            sent += 1
            print(f"  {evt.src:>16} -> {evt.dst:<16} {evt.kind}")
        else:
            failed += 1
    print(f"\n  sent={sent}  failed={failed}")
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", default="joon-001",
                    help="patient_id (joon-001, maria-001, rahul-001)")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="multiplier on inter-event delays (1.0=real, 0.3=fast)")
    ap.add_argument("--loop", action="store_true",
                    help="keep cycling through patients every ~30s")
    args = ap.parse_args()

    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set in .env", file=sys.stderr)
        return 1
    db = MongoClient(uri, serverSelectionTimeoutMS=5_000)["healthswarm"]

    # Verify the relay is up before we waste time
    health = RELAY.replace("/telemetry", "/health")
    try:
        r = requests.get(health, timeout=2)
        if r.status_code != 200:
            print(f"WARN: relay /health returned {r.status_code}")
    except Exception as e:
        print(f"ERROR: relay not reachable at {RELAY!r} ({e!r})", file=sys.stderr)
        print("       Start it with: python -m uvicorn dashboard_relay.main:app --port 3001",
              file=sys.stderr)
        return 1

    if args.loop:
        rotation = list(PATIENT_SCENARIO.keys())
        i = 0
        while True:
            pid = rotation[i % len(rotation)]
            print(f"\n--- {pid} ---")
            run_once(build_scenario(db, pid), args.speed)
            i += 1
            time.sleep(20)
    else:
        return run_once(build_scenario(db, args.patient), args.speed)


if __name__ == "__main__":
    sys.exit(main() or 0)
