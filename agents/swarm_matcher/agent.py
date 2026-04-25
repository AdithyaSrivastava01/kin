# swarm_matcher — patient-to-provider matching agent (Engineer 1)
import json
import os

from common.asi import asi_chat
from common.telemetry import beacon

DEMO_PHONE_FALLBACK = os.getenv("DEMO_PHONE_FALLBACK", "+1-555-DEMO")
MATCHER_MAX_TOKENS  = int(os.getenv("MATCHER_MAX_TOKENS", "512"))


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
