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
    result = asi_chat(
        system=(
            "Extract the medical specialty from the patient request. "
            "Reply with a single lowercase word only — one of: "
            "dermatologist, cardiologist, clinic, dentist, ophthalmologist, orthopedic. "
            "If unclear, reply: clinic"
        ),
        user=request_text,
        max_tokens=10,
    ).strip().lower()
    print(f"[swarm-intake] _parse_specialty({request_text[:60]!r}) → {result!r}")
    return result


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

    # If the LLM didn't extract a specific problem, fall back to the raw
    # request text so the caller never uses stored diagnoses as the reason.
    if not reqs.get("problem") and request_text:
        reqs["problem"] = request_text[:120].strip()

    # If the request mentions a name that differs from the profile name,
    # preserve it so swarm-caller uses it on the phone (not the demo persona name).
    if profile.get("_caller_name"):
        reqs["caller_name"] = profile["_caller_name"]

    # Drop null/empty values so prompts stay clean
    return {k: v for k, v in reqs.items() if v}


CALL_TOP_N = int(os.getenv("CALL_TOP_N", "3"))


def confirm_booking(db, patient_id: str, winner: dict, winner_fp: dict, requirements: dict) -> dict:
    """Phase 2 orchestration: call the winning clinic to confirm the agreed slot.

    winner      — clinic dict returned by swarm-matcher
    winner_fp   — fingerprint of the winning clinic's Phase 1 call
    requirements — original booking requirements (specialty, insurance, etc.)
    """
    profile = profiler.run(db, patient_id)
    if not profile or profile.get("error") == "PROFILE_NOT_FOUND":
        return {"error": f"patient {patient_id!r} not found for booking confirmation"}

    # Use the explicitly stored Phase 1 specialty (from _parse_specialty, not the
    # LLM requirements which may extract a different specialist name).
    profile["specialty"] = winner.get("specialty") or requirements.get("specialty") or "clinic"

    # Extract the best available time slot from the Phase 1 fingerprint
    key_facts = winner_fp.get("key_facts", [])
    time_slot = requirements.get("time_pref") or "the earliest available slot"
    for fact in key_facts:
        fl = fact.lower()
        if any(w in fl for w in ("monday", "tuesday", "wednesday", "thursday",
                                  "friday", "am", "pm", "morning", "afternoon",
                                  "tomorrow", "week")):
            time_slot = fact
            break

    beacon("swarm-intake", "swarm-caller", "BookingConfirmation", {
        "clinic": winner.get("name"),
        "time_slot": time_slot,
        "patient": profile.get("name"),
    })

    fp = caller.make_booking_call(winner, profile, requirements, time_slot)

    available = fp.get("available")
    summary = fp.get("summary", "")

    return {
        "patient_id":   patient_id,
        "patient_name": profile.get("name"),
        "clinic":       winner.get("name"),
        "phone":        winner.get("phone"),
        "language":     fp.get("language") or profile.get("language"),
        "available":    "booked" if available else "callback_needed",
        "time_slot":    time_slot,
        "rationale":    "Appointment confirmed at requested slot" if available else "Clinic could not confirm slot on this call",
        "call_summary": summary,
        "requirements": requirements,
    }


def run(db, patient_id: str, request_text: str = "", specialty: str | None = None) -> dict:
    # Extract caller_name= override injected by _resolve_patient for unknown patients
    caller_name = None
    clean_text = request_text
    for token in request_text.split():
        if token.startswith("caller_name="):
            caller_name = token.split("=", 1)[1]
            clean_text = request_text.replace(token, "").strip()
    request_text = clean_text
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
    if caller_name:
        profile["_caller_name"] = caller_name
    requirements = _parse_requirements(request_text, profile)

    beacon("swarm-intake", "swarm-matcher", "ChatMessage", {
        "candidates": len(candidates),
        "language":    requirements.get("language"),
        "requirements": requirements,
    })
    ranked = matcher.rank_candidates(profile, requirements, candidates)

    if not ranked:
        return {"error": "no clinic candidates found", "profile": profile}

    # Deduplicate by phone number so we never call the same line twice
    _seen_phones: set = set()
    to_call: list = []
    for c in ranked:
        if c.get("disqualified"):
            continue
        phone = c.get("phone") or "unknown"
        if phone not in _seen_phones:
            _seen_phones.add(phone)
            to_call.append(c)
        if len(to_call) >= CALL_TOP_N:
            break
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
        "patient_id":      patient_id,
        "patient_name":    profile.get("name"),
        "clinic":          winner.get("name"),
        "phone":           winner.get("phone"),
        "language":        winner_fp.get("language") or profile.get("language"),
        "rationale":       winner.get("rationale") or winner_fp.get("summary"),
        "available":       winner_fp.get("available"),
        "wait_time":       winner_fp.get("wait_time"),
        "attempts":        len(fingerprints),
        "call_summary":    winner_fp.get("summary"),
        "winner_key_facts": winner_fp.get("key_facts", []),
        "transcript_en":   winner_fp.get("transcript_en"),
        "match_score":     winner_fp.get("match_score", 0),
        "judge_score":     winner.get("judge_score", 0),
        "all_scores":      winner.get("all_scores", []),
        "requirements":    requirements,
        "specialty":       specialty,
    }
