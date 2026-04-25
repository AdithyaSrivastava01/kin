# swarm_intake — orchestrator agent (Engineer 1)
import json
import threading

from common.asi import asi_chat
from common.telemetry import beacon
from agents.swarm_profiler import agent as profiler
from agents.swarm_finder import agent as finder, FINDER_RADIUS_M
from agents.swarm_matcher import agent as matcher
from agents.swarm_caller import agent as caller


def _parse_specialty(request_text: str) -> str:
    """Extract a clinic specialty keyword from a free-text request via ASI:One."""
    return asi_chat(
        system=(
            "Extract the medical specialty from the patient request. "
            "Reply with a single lowercase word only — one of: "
            "dermatologist, cardiologist, clinic, dentist, ophthalmologist, orthopedic. "
            "If unclear, reply: clinic"
        ),
        user=request_text,
        max_tokens=10,
    ).strip().lower()


def _parse_requirements(request_text: str, profile: dict) -> dict:
    """Extract per-conversation booking requirements from the patient's request.

    These are the preferences the patient states for THIS booking — separate from
    the permanent medical profile stored in MongoDB.

    Returns a flat dict of requirements, e.g.:
      {"specialty": "dermatologist", "time_pref": "morning",
       "urgency": "this week", "gender_pref": "female",
       "accessibility": "wheelchair", "insurance": "Aetna", "language": "Korean"}
    """
    raw = asi_chat(
        system=(
            "You are a medical scheduling assistant. "
            "Extract the patient's booking requirements from their request. "
            "Reply with ONLY valid JSON — no prose, no markdown:\n"
            '{"specialty": "<or null>", '
            '"time_pref": "<morning|afternoon|evening|weekend|ASAP|or null>", '
            '"urgency": "<ASAP|this week|this month|flexible|or null>", '
            '"gender_pref": "<male|female|no preference|or null>", '
            '"accessibility": "<wheelchair|parking|elevator|or null>", '
            '"other": "<any other requirement as a short string|or null>"}'
        ),
        user=request_text or f"Appointment for {profile.get('name', 'patient')}",
        max_tokens=128,
    )
    try:
        reqs = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        reqs = {}

    # Always inject insurance + language from the patient profile so
    # downstream agents have the full picture in one place.
    reqs["insurance"] = profile.get("insurance")
    reqs["language"]  = profile.get("language", "English")

    # Drop null/empty values so prompts stay clean
    return {k: v for k, v in reqs.items() if v}


def run(db, patient_id: str, request_text: str = "", specialty: str | None = None) -> dict:
    """Orchestrate the full booking swarm for a patient.

    Flow:
      1. Announce request (AppointmentRequest beacon).
      2. Fan out to profiler + finder in parallel threads.
      3. Parse per-conversation requirements from request_text via LLM.
      4. swarm-caller calls ALL candidate clinics concurrently.
         → After each call, swarm-fingerprint summarises the transcript.
      5. swarm-matcher (LLM judge) picks the best clinic from fingerprints.

    Returns a summary dict of the booking outcome.
    """
    beacon("patient", "swarm-intake", "AppointmentRequest", {
        "patient_id": patient_id,
        "query": request_text or f"Appointment request for patient {patient_id}",
    })

    # Resolve specialty early so finder can use it
    if not specialty:
        specialty = _parse_specialty(request_text) if request_text else "clinic"

    # ── Parallel fan-out: profiler + finder ─────────────────────────────
    profile: dict    = {}
    candidates: list = []

    def _run_profiler():
        beacon("swarm-intake", "swarm-profiler", "ChatMessage", {"patient_id": patient_id})
        profile.update(profiler.run(db, patient_id))

    def _run_finder():
        p = db.patients.find_one({"patient_id": patient_id}, {"location": 1})
        if not p:
            return
        beacon("swarm-intake", "swarm-finder", "ChatMessage", {
            "specialty": specialty,
            "radius_km": FINDER_RADIUS_M / 1_000,
        })
        candidates.extend(finder.run(db, p["location"], specialty))

    t_profiler = threading.Thread(target=_run_profiler, daemon=True)
    t_finder   = threading.Thread(target=_run_finder,   daemon=True)
    t_profiler.start()
    t_finder.start()
    t_profiler.join()
    t_finder.join()

    if not profile:
        return {"error": f"patient {patient_id!r} not found"}

    # ── Extract per-conversation requirements ────────────────────────────
    profile["specialty"] = specialty
    requirements = _parse_requirements(request_text, profile)

    # ── Concurrent calls to all candidates → fingerprints ────────────────
    beacon("swarm-intake", "swarm-caller", "ChatMessage", {
        "clinics":     [c["name"] for c in candidates[:3]],
        "language":    requirements.get("language"),
        "requirements": requirements,
    })
    fingerprints = caller.run(candidates, profile, requirements)

    if not fingerprints:
        return {"error": "no clinics reachable", "profile": profile}

    # ── LLM judge picks the winner ───────────────────────────────────────
    beacon("swarm-intake", "swarm-matcher", "ChatMessage", {
        "fingerprints": len(fingerprints),
        "requirements": requirements,
    })
    best = matcher.run(requirements, fingerprints)

    if not best:
        return {"error": "no clinic matched", "profile": profile}

    return {
        "patient_id":   patient_id,
        "patient_name": profile.get("name"),
        "clinic":       best.get("name"),
        "phone":        best.get("phone"),
        "language":     profile.get("language"),
        "rationale":    best.get("rationale"),
        "requirements": requirements,
    }
