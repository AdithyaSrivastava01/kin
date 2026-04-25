# swarm_fingerprint — call transcript summariser (Engineer 1)
import json
import os

from common.asi import asi_chat
from common.telemetry import beacon

FINGERPRINT_MAX_TOKENS = int(os.getenv("FINGERPRINT_MAX_TOKENS", "256"))


def run(clinic: dict, transcript: list[dict], patient_requirements: dict) -> dict:
    """Summarise one clinic call into structured facts for the matcher to judge.

    transcript  — list of {"role": "receptionist"|"assistant", "text": "..."}
                  as stored by voice_gateway in _CALL_TRANSCRIPTS.
    patient_requirements — dict of booking preferences extracted by swarm-intake
                           (time_pref, accessibility, urgency, gender_pref, ...).

    Returns a dict with keys:
      clinic_name, clinic, available, insurance_accepted, key_facts, summary
    Emits a FingerprintReady beacon so the dashboard can show progress.
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
            "You are a medical scheduling analyst. Read a call transcript and extract "
            "key facts relevant to the patient's requirements. "
            "Reply with ONLY valid JSON in this exact shape — no prose, no markdown:\n"
            '{"available": true|false|null, '
            '"insurance_accepted": true|false|null, '
            '"wait_time": "<string or null>", '
            '"key_facts": ["<fact1>", "<fact2>", ...], '
            '"summary": "<one sentence>"}'
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
            "available": None,
            "insurance_accepted": None,
            "wait_time": None,
            "key_facts": [],
            "summary": raw.strip(),
        }

    result["clinic_name"] = clinic.get("name")
    result["clinic"] = clinic

    beacon("swarm-fingerprint", "swarm-matcher", "FingerprintReady", {
        "clinic": clinic.get("name"),
        "available": result.get("available"),
        "insurance_accepted": result.get("insurance_accepted"),
        "summary": result.get("summary"),
    })

    return result
