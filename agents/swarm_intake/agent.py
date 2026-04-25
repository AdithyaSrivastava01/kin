# swarm_intake — orchestrator agent (Engineer 1)
import threading
from common.telemetry import beacon
from common.asi import asi_chat
from agents.swarm_profiler import agent as profiler
from agents.swarm_finder import agent as finder, FINDER_RADIUS_M
from agents.swarm_matcher import agent as matcher
from agents.swarm_caller import agent as caller


def _parse_specialty(request_text: str) -> str:
    """Use ASI:One to extract a clinic specialty keyword from a free-text request."""
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


def run(db, patient_id: str, request_text: str = "", specialty: str | None = None) -> dict:
    """Orchestrate the full booking swarm for a patient.

    1. Emits AppointmentRequest beacon.
    2. Resolves specialty (from arg or LLM parse of request_text).
    3. Fans out to profiler + finder in parallel threads.
    4. Passes combined results to matcher → picks winning clinic.
    5. Hands off to caller → triggers the Twilio call.

    Returns a summary dict of the booking outcome.
    """
    # Step 1 — announce the request
    beacon("patient", "swarm-intake", "AppointmentRequest", {
        "patient_id": patient_id,
        "query": request_text or f"Appointment request for patient {patient_id}",
    })

    # Step 2 — resolve specialty
    if not specialty:
        specialty = _parse_specialty(request_text) if request_text else "clinic"

    # Step 3 — parallel fan-out to profiler and finder
    profile: dict = {}
    candidates: list = []

    def _run_profiler():
        beacon("swarm-intake", "swarm-profiler", "ChatMessage", {"patient_id": patient_id})
        profile.update(profiler.run(db, patient_id))

    def _run_finder():
        # Need patient location — do a minimal fetch so finder can start
        p = db.patients.find_one({"patient_id": patient_id}, {"location": 1})
        if not p:
            return
        beacon("swarm-intake", "swarm-finder", "ChatMessage", {
            "specialty": specialty,
            "radius_km": FINDER_RADIUS_M / 1_000,
        })
        candidates.extend(finder.run(db, p["location"], specialty))

    t_profiler = threading.Thread(target=_run_profiler, daemon=True)
    t_finder = threading.Thread(target=_run_finder, daemon=True)
    t_profiler.start()
    t_finder.start()
    t_profiler.join()
    t_finder.join()

    if not profile:
        return {"error": f"patient {patient_id!r} not found"}

    # Step 4 — match
    beacon("swarm-intake", "swarm-matcher", "ChatMessage", {
        "candidates": [c["name"] for c in candidates[:3]],
        "insurance": profile.get("insurance"),
        "language": profile.get("language"),
    })
    best = matcher.run(db, candidates, profile.get("insurance", ""), profile.get("language", "English"))

    if not best:
        return {"error": "no clinic matched", "profile": profile}

    # Step 5 — call
    beacon("swarm-intake", "swarm-caller", "ChatMessage", {
        "clinic": best.get("name"),
        "phone": best.get("phone"),
        "language": profile.get("language"),
    })
    # Pass specialty + time_pref through patient dict so caller can forward them
    patient_ctx = {**profile, "specialty": specialty, "time_pref": None}
    call_sid = caller.run(best, patient_ctx)

    return {
        "patient_id": patient_id,
        "patient_name": profile.get("name"),
        "clinic": best.get("name"),
        "phone": best.get("phone"),
        "language": profile.get("language"),
        "score": best.get("score"),
        "rationale": best.get("rationale"),
        "call_sid": call_sid,
    }
