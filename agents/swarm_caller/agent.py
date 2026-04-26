# swarm_caller — telephony/outreach agent
import os
import time
import threading

import requests

from common.telemetry import beacon
from agents.swarm_fingerprint import agent as fingerprint

VOICE_GATEWAY_URL = os.getenv("VOICE_GATEWAY_URL", "http://localhost:8000")
DEMO_PHONE_FALLBACK = os.getenv("DEMO_PHONE_FALLBACK", "+1-555-DEMO")
VOICE_GW_TIMEOUT = float(os.getenv("VOICE_GW_TIMEOUT", "10"))
CALL_POLL_INTERVAL = float(os.getenv("CALL_POLL_INTERVAL_S", "5"))
CALL_MAX_WAIT = float(os.getenv("CALL_MAX_WAIT_S", "150"))
MAX_FALLBACK_ATTEMPTS = int(os.getenv("MAX_FALLBACK_ATTEMPTS", "3"))


def _profile_problem(patient: dict) -> str:
    """Best-effort reason-for-visit from the patient profile when the
    free-text request didn't surface one. Used as the {{problem}}
    dynamic variable for the booking agent.
    """
    diagnoses = patient.get("diagnoses") or []
    if isinstance(diagnoses, list) and diagnoses:
        return ", ".join(str(d) for d in diagnoses[:2])
    return f"a follow-up consultation with a {patient.get('specialty', 'doctor')}"


def _failed_fingerprint(clinic: dict, reason: str) -> dict:
    """Build a fingerprint dict locally for an unreachable clinic — no LLM round-trip."""
    name = clinic.get("name", "Unknown clinic")
    return {
        "clinic_name": name,
        "clinic": clinic,
        "available": False,
        "insurance_accepted": None,
        "wait_time": None,
        "key_facts": [reason],
        "summary": f"{name} unreachable — {reason}.",
    }


def _call_one(
    clinic: dict,
    patient: dict,
    requirements: dict,
    out: list,
    lock: threading.Lock,
) -> None:
    """Place one inquiry call, wait for its transcript, fingerprint it, append to out."""
    phone = clinic.get("phone") or DEMO_PHONE_FALLBACK

    beacon(
        "swarm-caller",
        "clinic",
        "CallStarted",
        {
            "clinic": clinic.get("name"),
            "phone": phone,
            "patient": patient.get("name"),
            "language": patient.get("language", "English"),
        },
    )

    # 1 — Place the call (handed off to ElevenLabs Conversational AI
    # via /call → eleven_caller.place_call, which populates the agent's
    # dynamic_variables with the patient context below).
    # caller_name in requirements lets unknown patients (e.g. "Adi") override
    # the demo persona name so the ElevenLabs agent says the right name on the call
    call_name = requirements.get("caller_name") or patient.get("name")

    call_payload = {
        "to": phone,
        "language": patient.get("language", "English"),
        "patient_name": call_name,
        "patient_id": patient.get("patient_id"),
        "specialty": patient.get("specialty"),
        "problem": requirements.get("problem") or _profile_problem(patient),
        "insurance": patient.get("insurance"),
        "tests_needed": requirements.get("tests_needed") or "none",
        "time_pref": requirements.get("time_pref"),
        "clinic_name": clinic.get("name"),
    }
    print(
        f"[swarm-caller] ElevenLabs vars → clinic={clinic.get('name')} "
        f"specialty={call_payload['specialty']!r} "
        f"problem={call_payload['problem']!r} "
        f"patient_name={call_payload['patient_name']!r}"
    )

    try:
        resp = requests.post(
            f"{VOICE_GATEWAY_URL}/call",
            json=call_payload,
            timeout=VOICE_GW_TIMEOUT,
        )
        resp.raise_for_status()
        call_sid = resp.json().get("call_sid", "")
    except Exception as e:
        print(f"[swarm-caller] call to {clinic.get('name')} failed to start: {e!r}")
        with lock:
            out.append(_failed_fingerprint(clinic, f"call could not be placed: {e}"))
        return

    # 2 — Poll /transcript/{call_sid} until the call finishes or we time out
    transcript: list = []
    call_result: dict = {}
    completed = False
    deadline = time.time() + CALL_MAX_WAIT
    while time.time() < deadline:
        try:
            r = requests.get(
                f"{VOICE_GATEWAY_URL}/transcript/{call_sid}",
                timeout=5,
            )
            if r.status_code == 200:
                payload = r.json()
                transcript = payload.get("transcript", [])
                call_result = payload.get("result", {})
                completed = True
                break
            # 202 = still in progress, keep polling
        except Exception:
            pass
        time.sleep(CALL_POLL_INTERVAL)

    # 3 — Fingerprint the call. Skip the LLM for unreachable/timeout cases.
    if not completed:
        fp = _failed_fingerprint(clinic, "call did not complete within timeout")
    elif not transcript:
        fp = _failed_fingerprint(clinic, "call connected but no transcript captured")
    else:
        fp = fingerprint.run(clinic, transcript, requirements)
        if isinstance(call_result, dict):
            fp["result"] = call_result
        # Carry the raw transcript on the fingerprint so the persistence
        # layer can store it alongside the structured facts.
        fp["transcript"] = transcript

    # 4 — Persist to MongoDB so the dashboard /fingerprints/{patient_id}
    # endpoint can surface it later. Non-fatal — if Mongo is down we still
    # return the in-memory fp for the matcher to judge.
    try:
        from common.transcript_store import save_fingerprint
        fp_id = save_fingerprint(
            fp,
            patient_id=patient.get("patient_id"),
            patient_name=patient.get("name"),
            call_sid=call_sid or None,
        )
        fp["fingerprint_id"] = fp_id
    except Exception as e:
        print(f"[swarm-caller] persist failed (non-fatal): {e!r}")

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


def make_booking_call(clinic: dict, patient: dict, requirements: dict, time_slot: str) -> dict:
    """Phase 2: follow-up call to confirm a specific slot at the winning clinic."""
    booking_reqs = dict(requirements)
    booking_reqs["problem"] = (
        f"Following up to confirm the '{time_slot}' appointment slot "
        f"discussed in our earlier call for {patient.get('name')}"
    )
    booking_reqs["time_pref"] = time_slot

    out: list = []
    lock = threading.Lock()
    _call_one(clinic, patient, booking_reqs, out, lock)
    return out[0] if out else _failed_fingerprint(clinic, "booking confirmation call failed")


def call_ranked(ranked_clinics: list[dict], patient: dict, requirements: dict) -> dict:
    """Call ranked clinics in order until one books or fallback attempts are exhausted."""
    attempts = []
    for idx, clinic in enumerate(ranked_clinics[:MAX_FALLBACK_ATTEMPTS], 1):
        phone = clinic.get("phone") or DEMO_PHONE_FALLBACK
        beacon(
            "swarm-caller",
            "clinic",
            "CallAttempt",
            {
                "attempt": idx,
                "clinic": clinic.get("name"),
                "phone": phone,
                "match_score": clinic.get("match_score"),
            },
        )

        out: list[dict] = []
        lock = threading.Lock()
        _call_one(clinic, patient, requirements, out, lock)
        fingerprint_result = (
            out[0]
            if out
            else _failed_fingerprint(clinic, "call ended without a fingerprint")
        )
        attempts.append(fingerprint_result)

        available = fingerprint_result.get("available")
        result = fingerprint_result.get("result", {})
        status = result.get("status") if isinstance(result, dict) else None
        booked = status == "booked" or available is True

        beacon(
            "swarm-caller",
            "swarm-intake",
            "CallAttemptResult",
            {
                "attempt": idx,
                "clinic": clinic.get("name"),
                "booked": booked,
                "available": available,
                "summary": fingerprint_result.get("summary"),
            },
        )

        if booked:
            return {
                "status": "booked",
                "clinic": clinic,
                "fingerprint": fingerprint_result,
                "attempts": attempts,
            }

    return {"status": "exhausted", "attempts": attempts}
