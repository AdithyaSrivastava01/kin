# swarm_matcher — patient-to-provider matching agent (Engineer 1)
import os
from common.telemetry import beacon
from common.asi import asi_chat

# Scoring weights — tunable via environment without code changes
SCORE_INSURANCE        = float(os.getenv("SCORE_INSURANCE", "3"))
SCORE_LANGUAGE         = float(os.getenv("SCORE_LANGUAGE", "2"))
SCORE_PROXIMITY_PER_KM = float(os.getenv("SCORE_PROXIMITY_PER_KM", "1"))

DEMO_PHONE_FALLBACK = os.getenv("DEMO_PHONE_FALLBACK", "+1-555-DEMO")
MATCHER_MAX_TOKENS  = int(os.getenv("MATCHER_MAX_TOKENS", "64"))

# Language hints embedded in clinic names — good enough for demo data.
_LANG_KEYWORDS = {
    "Korean":  ["seoul", "korean", "korea", "한"],
    "Spanish": ["hispanic", "latino", "latina", "español", "spanish", "mx"],
    "Hindi":   ["india", "hindi", "ayur"],
    "Marathi": ["india", "hindi", "ayur"],
}


def _language_score(clinic_name: str, patient_language: str) -> float:
    name_lower = clinic_name.lower()
    for kw in _LANG_KEYWORDS.get(patient_language, []):
        if kw in name_lower:
            return SCORE_LANGUAGE
    return 0.0


def run(db, candidates: list[dict], insurance_provider: str, patient_language: str) -> dict:
    """Rank candidates by insurance coverage, language affinity, and proximity.

    Scoring (higher is better):
      +SCORE_INSURANCE        clinic accepts the patient's insurance
      +SCORE_LANGUAGE         clinic name suggests the patient's language
      -SCORE_PROXIMITY_PER_KM per km of road distance (from swarm-finder ETA)

    Emits ClinicMatched beacon and returns the winning clinic dict.
    Returns {} if candidates is empty.
    """
    if not candidates:
        beacon("swarm-matcher", "swarm-intake", "ClinicMatched", {"error": "no candidates"})
        return {}

    scored = []
    for c in candidates:
        score = 0.0

        mapping = db.insurance_map.find_one({"clinic_name": c["name"]})
        if mapping and insurance_provider in mapping.get("accepts", []):
            score += SCORE_INSURANCE

        score += _language_score(c["name"], patient_language)

        score -= c.get("distance_m", 0) / 1_000 * SCORE_PROXIMITY_PER_KM

        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, winner = scored[0]

    rationale = asi_chat(
        system="You are a terse healthcare scheduling assistant. One sentence only.",
        user=(
            f"Why is {winner['name']} the best match for a patient "
            f"with {insurance_provider} insurance who speaks {patient_language}? "
            f"It is {winner.get('distance_m', 0) / 1000:.1f} km away."
        ),
        max_tokens=MATCHER_MAX_TOKENS,
    )

    beacon("swarm-matcher", "swarm-intake", "ClinicMatched", {
        "clinic": winner["name"],
        "address": winner.get("address"),
        "phone": winner.get("phone") or DEMO_PHONE_FALLBACK,
        "score": round(best_score, 2),
        "rationale": rationale,
    })

    winner["score"] = round(best_score, 2)
    winner["rationale"] = rationale
    return winner
