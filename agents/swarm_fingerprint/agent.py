# swarm_fingerprint — call transcript translator + summariser
#
# Owns BOTH translation and structured fact extraction for clinic calls.
# Receptionist transcripts arrive in any language (ElevenLabs Scribe
# preserves the original); this agent's ASI:One prompt translates as it
# extracts, so swarm-matcher always judges English fingerprints.
import json
import os

from common.asi import asi_chat
from common.telemetry import beacon

FINGERPRINT_MAX_TOKENS = int(os.getenv("FINGERPRINT_MAX_TOKENS", "384"))


def run(clinic: dict, transcript: list[dict], patient_requirements: dict) -> dict:
    """Translate + summarise one clinic call into structured facts.

    transcript  — list of {"role": "receptionist"|"assistant", "text": "..."}
                  as captured by voice_gateway. Receptionist lines may be
                  in any language; this agent translates to English while
                  extracting facts in a single ASI:One pass.
    patient_requirements — dict of booking preferences extracted by
                           swarm-intake (time_pref, accessibility, urgency,
                           gender_pref, language, ...).

    Returns a dict with keys:
      clinic_name, clinic, available, insurance_accepted, wait_time,
      key_facts, summary, language, transcript_en
    Emits a FingerprintReady beacon so the dashboard reflects progress.
    """
    transcript_text = "\n".join(
        f"{'Agent' if t['role'] == 'assistant' else 'Receptionist'}: {t['text']}"
        for t in transcript
    ) or "No transcript captured — call did not connect or no audio received."

    requirements_text = "\n".join(
        f"- {k}: {v}" for k, v in patient_requirements.items() if v
    ) or "No specific requirements."

    raw = asi_chat(
        system=(
            "You are a medical scheduling analyst. Read a phone-call "
            "transcript between an AI booking agent and a clinic "
            "receptionist. The receptionist may be speaking any "
            "language — translate to English as you extract facts.\n"
            "Reply with ONLY valid JSON in this exact shape — no prose, "
            "no markdown:\n"
            '{"language": "<receptionist language, e.g. English, Korean, '
            'Spanish, Hindi, Marathi, or Unknown>", '
            '"available": true|false|null, '
            '"insurance_accepted": true|false|null, '
            '"wait_time": "<string or null>", '
            '"key_facts": ["<fact1 in English>", "<fact2 in English>", ...], '
            '"summary": "<one English sentence>", '
            '"transcript_en": "<full call transcript translated to English, '
            'newline-separated, prefixed with Agent: / Receptionist:>"}'
        ),
        user=(
            f"Clinic: {clinic.get('name')}\n\n"
            f"Patient requirements:\n{requirements_text}\n\n"
            f"Call transcript:\n{transcript_text}"
        ),
        max_tokens=FINGERPRINT_MAX_TOKENS,
    )

    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        result = {
            "language": "Unknown",
            "available": None,
            "insurance_accepted": None,
            "wait_time": None,
            "key_facts": [],
            "summary": raw.strip(),
            "transcript_en": transcript_text,
        }

    result["clinic_name"] = clinic.get("name")
    result["clinic"] = clinic

    beacon("swarm-fingerprint", "swarm-matcher", "FingerprintReady", {
        "clinic": clinic.get("name"),
        "language": result.get("language"),
        "available": result.get("available"),
        "insurance_accepted": result.get("insurance_accepted"),
        "summary": result.get("summary"),
    })

    return result
