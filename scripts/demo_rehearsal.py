"""End-to-end demo rehearsal harness.

Runs the full HealthSwarm demo flow against the live relay/dashboard
without requiring E1's agents to exist:

    1. Health-check the dashboard relay
    2. Run the swarm graph for a chosen patient (real Mongo data)
    3. Pause for the audience to observe the candidate fan-out
    4. Fire the LanguageDetected wow moment (mocks E2 if no real call)
    5. Fire the closing BookingResult event

When E2's voice gateway is live (NGROK_URL shared), pass --real-call
to place an actual Twilio call instead of mocking the language event.

    python scripts/demo_rehearsal.py
    python scripts/demo_rehearsal.py --patient maria-001
    python scripts/demo_rehearsal.py --real-call --to +1XXXXXXXXXX
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Ensure project root is on sys.path so `common` and `scripts.sim_swarm` resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv

load_dotenv()

RELAY = os.getenv("TELEMETRY_RELAY_URL", "http://localhost:3001/telemetry")
RELAY_BASE = RELAY.rsplit("/telemetry", 1)[0]
GATEWAY = os.getenv("NGROK_URL", "").rstrip("/")

PATIENT_LANG = {
    "joon-001":  "Korean",
    "maria-001": "Spanish",
    "rahul-001": "Hindi",
}


def beacon(src, dst, kind, payload):
    try:
        requests.post(RELAY, json={"src": src, "dst": dst, "kind": kind, "payload": payload}, timeout=2)
    except Exception as e:
        print(f"  [warn] beacon failed: {e!r}")


def step(label, sleep_s=0.0):
    print(f"  >> {label}")
    if sleep_s:
        time.sleep(sleep_s)


def health_check() -> bool:
    try:
        r = requests.get(f"{RELAY_BASE}/health", timeout=2)
        ok = r.status_code == 200
    except Exception:
        ok = False
    print(f"  relay {RELAY_BASE}/health  ->  {'OK' if ok else 'DOWN'}")
    return ok


def run_swarm_graph(patient_id: str):
    """Reuse sim_swarm to emit the agent-graph events.

    Returns (failed_count, outreach_id) so the caller can attach the same
    outreach_id to subsequent mocked voice beacons.
    """
    # Defer import so the rehearsal works even if pymongo isn't installed
    # on a demo box (only sim_swarm needs it)
    import certifi
    from sim_swarm import build_scenario, run_once  # type: ignore
    from pymongo import MongoClient
    db = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())["healthswarm"]
    events = build_scenario(db, patient_id)
    outreach_id = (events[0].payload.get("outreach_id") if events else None)
    failed = run_once(events, speed=1.0)
    return failed, outreach_id


def run_real_call(to_number: str, patient_lang: str, patient_name: str, specialty: str):
    """Trigger E2's voice gateway to place an actual Twilio call.
    Beacons (CallStarted, LanguageDetected, BookingResult) come from the
    voice_gateway side, not from us — we just kick it off.
    """
    if not GATEWAY:
        raise SystemExit("NGROK_URL not set — cannot place real call")
    payload = {
        "to": to_number,
        "language": patient_lang,
        "patient_name": patient_name,
        "specialty": specialty,
    }
    r = requests.post(f"{GATEWAY}/call", json=payload, timeout=10)
    r.raise_for_status()
    print(f"  call_sid={r.json().get('call_sid')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", default="joon-001",
                    choices=["joon-001", "maria-001", "rahul-001"])
    ap.add_argument("--real-call", action="store_true",
                    help="Trigger E2's voice_gateway /call instead of mocking language event")
    ap.add_argument("--to", default=os.getenv("DEMO_TARGET_PHONE"),
                    help="Phone number to dial (real-call mode)")
    args = ap.parse_args()

    print("\n=== HealthSwarm demo rehearsal ===\n")

    if not health_check():
        print("  -> start the relay: python -m uvicorn dashboard_relay.main:app --port 3001")
        return 1

    # Phase A — agent graph (intake → profiler/finder → matcher → caller)
    print("\n[A] Swarm coordinates the booking")
    failed, outreach_id = run_swarm_graph(args.patient)
    if failed:
        print(f"  ! {failed} beacon(s) failed during graph run")
        return 1

    print("\n  pausing 3s so judges can read the graph…")
    time.sleep(3)

    # Phase B — voice / language switch (the wow moment)
    lang = PATIENT_LANG.get(args.patient, "English")
    print(f"\n[B] swarm-caller dials clinic, hears {lang} receptionist")

    if args.real_call:
        if not args.to:
            print("  ERROR: --to <phone> required for --real-call (or set DEMO_TARGET_PHONE)")
            return 1
        step("placing real Twilio call via voice_gateway", 0)
        run_real_call(args.to, lang, args.patient.split('-')[0].title(),
                      "dermatologist" if args.patient == "joon-001" else "clinic")
        step("(beacons CallStarted/LanguageDetected/BookingResult come from E2's gateway)", 0)
        # Real beacons land asynchronously — give the call ~30s
        for i in range(30):
            print(f"  …waiting on call ({i+1}s)", end="\r")
            time.sleep(1)
        print()
    else:
        # Mock E2's beacons so the dashboard tells the full story even
        # without a real call placed. Carry the outreach_id forward so
        # the relay can correlate everything into one outreach_attempts row.
        step("CallStarted (mock)", 0.4)
        beacon("swarm-caller", "clinic", "CallStarted", {
            "outreach_id": outreach_id,
            "call_sid":    f"MOCK-{outreach_id}",
            "to":          "+1-555-DEMO",
            "from":        os.getenv("TWILIO_PHONE_NUMBER", "+1-555-AGENT"),
        })
        step(f"LanguageDetected: {lang} (mock — would be real with E2's gateway)", 1.5)
        beacon("swarm-caller", "clinic", "LanguageDetected", {
            "outreach_id": outreach_id,
            "language":    lang,
            "latency_ms":  2400,
            "mocked":      True,
        })
        step("BookingResult (mock)", 3.0)
        beacon("swarm-caller", "clinic", "BookingResult", {
            "outreach_id": outreach_id,
            "outcome":     "booked",
            "when":        "Thu 2pm",
            "language":    lang,
            "mocked":      True,
        })

    print("\n=== rehearsal complete — check the dashboard ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
