# swarm_matcher — patient-to-provider matching agent
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os

from common.asi import asi_chat
from common.telemetry import beacon

DEMO_PHONE_FALLBACK = os.getenv("DEMO_PHONE_FALLBACK", "+1-555-DEMO")
MATCHER_MAX_TOKENS  = int(os.getenv("MATCHER_MAX_TOKENS", "512"))
MATCHER_WORKERS     = int(os.getenv("MATCHER_WORKERS", "8"))


def _candidate_prompt(profile: dict, requirements: dict, clinic: dict) -> tuple[str, str]:
    patient_block = {
        "name": profile.get("name"),
        "insurance": profile.get("insurance"),
        "language": profile.get("language"),
        "diagnoses": profile.get("diagnoses", []),
        "medications": profile.get("medications", []),
        "prior_providers": profile.get("prior_providers", []),
    }
    clinic_block = {
        "name": clinic.get("name"),
        "specialty": clinic.get("specialty"),
        "address": clinic.get("address"),
        "distance_m": clinic.get("distance_m"),
        "eta_s": clinic.get("eta_s"),
        "opening_hours": clinic.get("opening_hours"),
        "raw_tags": clinic.get("raw_tags", {}),
    }
    system = (
        "You are a clinic matching judge. Score one candidate clinic for a "
        "routine appointment request. Use the rubric: specialty fit and "
        "insurance are must-haves; proximity, language services, continuity "
        "of care, and accessibility are weighted bonuses. Never diagnose or "
        "recommend treatment. Reply with ONLY valid JSON:\n"
        '{"score": 0-100, "disqualified": true|false, '
        '"rationale": "<one sentence>", "flags": ["<short reason>", ...]}'
    )
    user = (
        f"Patient profile:\n{json.dumps(patient_block, default=str)}\n\n"
        f"Booking requirements:\n{json.dumps(requirements, default=str)}\n\n"
        f"Candidate clinic:\n{json.dumps(clinic_block, default=str)}"
    )
    return system, user


def _score_candidate(profile: dict, requirements: dict, clinic: dict) -> dict:
    system, user = _candidate_prompt(profile, requirements, clinic)
    try:
        raw = asi_chat(system, user, max_tokens=256)
        parsed = json.loads(raw)
    except Exception as exc:
        parsed = {
            "score": 0,
            "disqualified": False,
            "rationale": f"Fallback score used because ASI:One scoring failed: {exc}",
            "flags": [],
        }

    scored = dict(clinic)
    scored["match_score"] = int(parsed.get("score") or 0)
    scored["disqualified"] = bool(parsed.get("disqualified", False))
    scored["rationale"] = parsed.get("rationale", "")
    scored["flags"] = parsed.get("flags", [])
    return scored


def rank_candidates(profile: dict, requirements: dict, candidates: list[dict]) -> list[dict]:
    """Evaluate candidate clinics concurrently and return a ranked shortlist."""
    if not candidates:
        beacon("swarm-matcher", "swarm-intake", "ClinicRanked", {"error": "no candidates"})
        return []

    ranked: list[dict] = []
    workers = min(MATCHER_WORKERS, max(1, len(candidates)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_score_candidate, profile, requirements, clinic)
            for clinic in candidates
        ]
        for future in as_completed(futures):
            ranked.append(future.result())

    ranked.sort(
        key=lambda c: (
            bool(c.get("disqualified", False)),
            -int(c.get("match_score", 0)),
            int(c.get("eta_s") or 10**9),
        )
    )

    beacon("swarm-matcher", "swarm-intake", "ClinicRanked", {
        "count": len(ranked),
        "top": [
            {
                "name": c.get("name"),
                "score": c.get("match_score"),
                "disqualified": c.get("disqualified"),
                "rationale": c.get("rationale"),
            }
            for c in ranked[:5]
        ],
    })
    return ranked


def run(patient_requirements: dict, fingerprinted: list[dict]) -> dict:
    """Use an LLM as judge to pick the best clinic from fingerprinted call summaries.

    patient_requirements — booking preferences extracted by swarm-intake
                           (specialty, insurance, time_pref, urgency, ...)
    fingerprinted        — list of fingerprint dicts from swarm-fingerprint,
                           each with: clinic_name, available, insurance_accepted,
                           wait_time, key_facts, summary, clinic (raw dict)

    Returns the winning clinic dict (with rationale injected) and emits
    a ClinicMatched beacon.
    """
    if not fingerprinted:
        beacon("swarm-matcher", "swarm-intake", "ClinicMatched", {"error": "no candidates"})
        return {}

    requirements_text = "\n".join(
        f"- {k}: {v}" for k, v in patient_requirements.items() if v
    ) or "No specific requirements."

    clinics_block = ""
    for i, fp in enumerate(fingerprinted, 1):
        clinics_block += (
            f"\n{i}. {fp.get('clinic_name')}\n"
            f"   Available: {fp.get('available')}\n"
            f"   Insurance accepted: {fp.get('insurance_accepted')}\n"
            f"   Wait time: {fp.get('wait_time')}\n"
            f"   Summary: {fp.get('summary')}\n"
        )
        for fact in fp.get("key_facts", []):
            clinics_block += f"   • {fact}\n"

    raw = asi_chat(
        system=(
            "You are a medical scheduling judge. "
            "Given a patient's requirements and summaries of inquiry calls to clinics, "
            "pick the single best clinic. "
            "Reply with ONLY valid JSON — no prose, no markdown:\n"
            '{"winner": "<exact clinic name>", '
            '"rationale": "<one sentence why>", '
            '"rank": ["<name>", ...]}'
        ),
        user=(
            f"Patient requirements:\n{requirements_text}\n\n"
            f"Clinic call summaries:{clinics_block}\n"
            "Which clinic best matches the patient's needs?"
        ),
        max_tokens=MATCHER_MAX_TOKENS,
    )

    try:
        parsed = json.loads(raw)
        winner_name = parsed.get("winner", "")
        rationale   = parsed.get("rationale", "")
    except (json.JSONDecodeError, ValueError):
        winner_name = fingerprinted[0].get("clinic_name", "")
        rationale   = raw.strip()

    winner_fp = next(
        (fp for fp in fingerprinted if fp.get("clinic_name") == winner_name),
        fingerprinted[0],
    )
    winner = dict(winner_fp.get("clinic", {}))
    winner["rationale"] = rationale

    beacon("swarm-matcher", "swarm-intake", "ClinicMatched", {
        "clinic":   winner.get("name"),
        "address":  winner.get("address"),
        "phone":    winner.get("phone") or DEMO_PHONE_FALLBACK,
        "rationale": rationale,
    })

    return winner
