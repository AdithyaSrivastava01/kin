# swarm_caller — telephony/outreach agent (Engineer 1)
import os
import time
import threading

import requests

from common.telemetry import beacon
from agents.swarm_fingerprint import agent as fingerprint

VOICE_GATEWAY_URL   = os.getenv("VOICE_GATEWAY_URL",   "http://localhost:8000")
DEMO_PHONE_FALLBACK = os.getenv("DEMO_PHONE_FALLBACK",  "+1-555-DEMO")
VOICE_GW_TIMEOUT    = float(os.getenv("VOICE_GW_TIMEOUT",    "10"))
CALL_POLL_INTERVAL  = float(os.getenv("CALL_POLL_INTERVAL_S", "5"))
CALL_MAX_WAIT       = float(os.getenv("CALL_MAX_WAIT_S",      "150"))


def _call_one(
    clinic: dict,
    patient: dict,
    requirements: dict,
    out: list,
    lock: threading.Lock,
) -> None:
    """Place one inquiry call, wait for its transcript, fingerprint it, append to out."""
    phone = clinic.get("phone") or DEMO_PHONE_FALLBACK

    beacon("swarm-caller", "clinic", "CallStarted", {
        "clinic": clinic.get("name"),
        "phone":  phone,
        "patient": patient.get("name"),
        "language": patient.get("language", "English"),
    })

    # 1 — Place the call
    try:
        resp = requests.post(
            f"{VOICE_GATEWAY_URL}/call",
            json={
                "to":           phone,
                "language":     patient.get("language", "English"),
                "patient_name": patient.get("name"),
                "specialty":    patient.get("specialty"),
                "insurance":    patient.get("insurance"),
                "time_pref":    requirements.get("time_pref"),
            },
            timeout=VOICE_GW_TIMEOUT,
        )
        resp.raise_for_status()
        call_sid = resp.json().get("call_sid", "")
    except Exception as e:
        print(f"[swarm-caller] call to {clinic.get('name')} failed to start: {e!r}")
        fp = fingerprint.run(clinic, [], requirements)
        with lock:
            out.append(fp)
        return

    # 2 — Poll /transcript/{call_sid} until the call finishes or we time out
    transcript = []
    deadline = time.time() + CALL_MAX_WAIT
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{VOICE_GATEWAY_URL}/transcript/{call_sid}",
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                transcript = data.get("transcript", [])
                break
            # 202 = still in progress, keep polling
        except Exception:
            pass
        time.sleep(CALL_POLL_INTERVAL)

    # 3 — Fingerprint this call's transcript
    fp = fingerprint.run(clinic, transcript, requirements)
    with lock:
        out.append(fp)


def run(candidates: list[dict], patient: dict, requirements: dict) -> list[dict]:
    """Call every candidate clinic concurrently and return a fingerprint per call.

    candidates   — list of clinic dicts from swarm-finder
    patient      — profile dict from swarm-profiler
                   (must include: name, language, insurance, specialty)
    requirements — booking preferences from swarm-intake
                   (time_pref, urgency, accessibility, gender_pref, ...)

    Returns a list of fingerprint dicts (one per clinic) ready for swarm-matcher.
    """
    if not candidates:
        return []

    results: list[dict] = []
    lock = threading.Lock()

    threads = [
        threading.Thread(
            target=_call_one,
            args=(clinic, patient, requirements, results, lock),
            daemon=True,
        )
        for clinic in candidates
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return results
