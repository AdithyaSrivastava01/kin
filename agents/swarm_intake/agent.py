# swarm_intake — orchestrator agent
import json
import os
import threading

from common.asi import asi_chat
from common.telemetry import beacon
from agents.swarm_profiler import agent as profiler
from agents.swarm_finder import agent as finder
from agents.swarm_finder.agent import FINDER_RADIUS_M
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
            '"problem": "<one short phrase describing the symptom or '
            'reason for the visit, e.g. \'recurring headaches\', '
            '\'annual check-up\', \'persistent rash\'|or null>", '
            '"tests_needed": "<comma-separated list of any specific '
            'tests, scans or labs the patient asked for, e.g. '
            '\'blood work, MRI\'|or null>", '
            '"time_pref": "<morning|afternoon|evening|weekend|ASAP|or null>", '
            '"urgency": "<ASAP|this week|this month|flexible|or null>", '
            '"gender_pref": "<male|female|no preference|or null>", '
            '"accessibility": "<wheelchair|parking|elevator|or null>", '
            '"other": "<any other requirement as a short string|or null>"}'
        ),
        user=request_text or f"Appointment for {profile.get('name', 'patient')}",
        max_tokens=192,
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


CALL_TOP_N = int(os.getenv("CALL_TOP_N", "3"))


def run(db, patient_id: str, request_text: str = "", specialty: str | None = None) -> dict:
    """Orchestrate the full booking swarm for a patient.

    Flow:
      1. Announce request (AppointmentRequest beacon).
      2. Fan out to profiler + finder in parallel threads.
      3. Parse per-conversation requirements from request_text via LLM.
      4. swarm-matcher.rank_candidates ranks clinics by metadata; we take
         the top N to actually call.
      5. swarm-caller calls those N clinics in PARALLEL; each call's
         transcript is translated + fingerprinted by swarm-fingerprint.
      6. swarm-matcher.run (LLM judge) picks the best clinic from the
         resulting fingerprints — this is the canonical decision point.

    Returns a summary dict of the booking outcome.
    """
    beacon("patient", "swarm-intake", "AppointmentRequest", {
        "patient_id": patient_id,
        "query": request_text or f"Appointment request for patient {patient_id}",
    })

    # Resolve specialty early so finder can use it
    if not specialty:
        specialty = _parse_specialty(request_text) if request_text else "clinic"

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

    if not profile or profile.get("error") == "PROFILE_NOT_FOUND":
        return {"error": f"patient {patient_id!r} not found"}

    profile["specialty"] = specialty
    requirements = _parse_requirements(request_text, profile)

    beacon("swarm-intake", "swarm-matcher", "ChatMessage", {
        "candidates": len(candidates),
        "language":    requirements.get("language"),
        "requirements": requirements,
    })
    ranked = matcher.rank_candidates(profile, requirements, candidates)

    if not ranked:
        return {"error": "no clinic candidates found", "profile": profile}

    to_call = [c for c in ranked if not c.get("disqualified")][:CALL_TOP_N]
    if not to_call:
        return {"error": "all clinic candidates disqualified", "profile": profile, "ranked": ranked[:5]}

    beacon("swarm-intake", "swarm-caller", "ChatMessage", {
        "clinics": [c["name"] for c in to_call],
        "requirements": requirements,
    })
    fingerprints = caller.run(to_call, profile, requirements)

    if not fingerprints:
        return {"error": "no calls produced fingerprints", "profile": profile, "ranked": to_call}

    beacon("swarm-intake", "swarm-matcher", "ChatMessage", {
        "stage": "judge_fingerprints",
        "fingerprints": [fp.get("clinic_name") for fp in fingerprints],
    })
    winner = matcher.run(requirements, fingerprints)

    if not winner:
        return {
            "error": "matcher could not pick a winner from fingerprints",
            "profile": profile,
            "fingerprints": fingerprints,
        }

    winner_fp = next(
        (fp for fp in fingerprints if fp.get("clinic_name") == winner.get("name")),
        fingerprints[0],
    )

    return {
        "patient_id":   patient_id,
        "patient_name": profile.get("name"),
        "clinic":       winner.get("name"),
        "phone":        winner.get("phone"),
        "language":     winner_fp.get("language") or profile.get("language"),
        "rationale":    winner.get("rationale") or winner_fp.get("summary"),
        "available":    winner_fp.get("available"),
        "wait_time":    winner_fp.get("wait_time"),
        "attempts":     len(fingerprints),
        "call_summary": winner_fp.get("summary"),
        "transcript_en": winner_fp.get("transcript_en"),
        "requirements": requirements,
    }
