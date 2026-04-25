# swarm_matcher — patient-to-provider matching agent (Engineer 1)
from common.telemetry import beacon
from common.asi import asi_chat


# Language hints embedded in clinic names — good enough for demo data.
_LANG_KEYWORDS = {
    "Korean":  ["seoul", "korean", "korea", "한"],
    "Spanish": ["hispanic", "latino", "latina", "español", "spanish", "mx"],
    "Hindi":   ["india", "hindi", "ayur"],
    "Marathi": ["india", "hindi", "ayur"],
}


def _language_score(clinic_name: str, patient_language: str) -> int:
    name_lower = clinic_name.lower()
    for kw in _LANG_KEYWORDS.get(patient_language, []):
        if kw in name_lower:
            return 2
    return 0


def run(db, candidates: list[dict], insurance_provider: str, patient_language: str) -> dict:
    """Rank candidates by insurance coverage, language affinity, and proximity.

    Scoring (higher is better):
      +3  clinic accepts the patient's insurance
      +2  clinic name suggests the patient's language
      -1  per km of road distance (from swarm-finder ETA)

    Emits ClinicMatched beacon and returns the winning clinic dict.
    Returns {} if candidates is empty.
    """
    if not candidates:
        beacon("swarm-matcher", "swarm-intake", "ClinicMatched", {"error": "no candidates"})
        return {}

    scored = []
    for c in candidates:
        score = 0.0

        # Insurance check
        mapping = db.insurance_map.find_one({"clinic_name": c["name"]})
        if mapping and insurance_provider in mapping.get("accepts", []):
            score += 3

        # Language affinity
        score += _language_score(c["name"], patient_language)

        # Proximity penalty (-1 per km)
        score -= c.get("distance_m", 0) / 1_000

        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, winner = scored[0]

    # Ask the LLM for a one-line human-readable rationale
    rationale = asi_chat(
        system="You are a terse healthcare scheduling assistant. One sentence only.",
        user=(
            f"Why is {winner['name']} the best match for a patient "
            f"with {insurance_provider} insurance who speaks {patient_language}? "
            f"It is {winner.get('distance_m', 0) / 1000:.1f} km away."
        ),
        max_tokens=64,
    )

    beacon("swarm-matcher", "swarm-intake", "ClinicMatched", {
        "clinic": winner["name"],
        "address": winner.get("address"),
        "phone": winner.get("phone") or "+1-555-DEMO",
        "score": round(best_score, 2),
        "rationale": rationale,
    })

    winner["score"] = round(best_score, 2)
    winner["rationale"] = rationale
    return winner
