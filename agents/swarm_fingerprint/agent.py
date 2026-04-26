# swarm_fingerprint — call transcript translator + summariser + scorer
#
# Owns translation, structured fact extraction, and match scoring for clinic calls.
# Receptionist transcripts arrive in any language (ElevenLabs Scribe preserves the
# original); this agent translates as it extracts, so swarm-matcher always judges
# English fingerprints.
#
# In-memory conversation store: every completed call's labeled transcript is kept
# in _CONVERSATION_STORE so the matcher and dashboard can inspect it later.
import json
import os
import threading

from common.asi import asi_chat
from common.telemetry import beacon

FINGERPRINT_MAX_TOKENS = int(os.getenv("FINGERPRINT_MAX_TOKENS", "512"))

# ── In-memory conversation store ─────────────────────────────────────────────
# Keyed by clinic name. Each entry holds the labeled transcript
# (receptionist / agent turns) plus the derived fingerprint.
_CONVERSATION_STORE: dict[str, dict] = {}
_STORE_LOCK = threading.Lock()


def get_conversation(clinic_name: str) -> dict | None:
    """Return the stored conversation + fingerprint for a clinic, or None."""
    with _STORE_LOCK:
        return _CONVERSATION_STORE.get(clinic_name)


def get_all_conversations() -> dict:
    """Return a snapshot of all stored conversations."""
    with _STORE_LOCK:
        return dict(_CONVERSATION_STORE)


def clear_conversations():
    """Clear the store (call between booking sessions if needed)."""
    with _STORE_LOCK:
        _CONVERSATION_STORE.clear()


# ── Core fingerprint function ─────────────────────────────────────────────────

def run(clinic: dict, transcript: list[dict], patient_requirements: dict) -> dict:
    """Translate, summarise, and score one clinic call.

    transcript  — list of {"role": "receptionist"|"assistant", "text": "..."}
                  Receptionist lines may be in any language; translated to English
                  in a single ASI:One pass.
    patient_requirements — booking preferences from swarm-intake.

    Returns a fingerprint dict with keys:
      clinic_name, clinic, available, insurance_accepted, wait_time,
      key_facts, summary, language, transcript_en, match_score

    Stores the labeled conversation in _CONVERSATION_STORE for later inspection.
    """
    # Build labeled transcript text (preserving original language for receptionist)
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
            "transcript between an AI booking agent (Agent) and a clinic "
            "receptionist (Receptionist). The receptionist may speak any "
            "language — translate every line to English as you extract facts.\n\n"
            "Reply with ONLY valid JSON in this exact shape — no prose, no markdown:\n"
            '{\n'
            '  "language": "<receptionist language, e.g. English, Korean, Spanish, Hindi, or Unknown>",\n'
            '  "available": true|false|null,\n'
            '  "insurance_accepted": true|false|null,\n'
            '  "wait_time": "<string or null>",\n'
            '  "key_facts": ["<fact1 in English>", "<fact2 in English>", ...],\n'
            '  "summary": "<one English sentence summarising the call>",\n'
            '  "match_score": <integer 0-100 — how well this clinic meets the patient requirements>,\n'
            '  "transcript_en": "<full call transcript translated to English, newline-separated, prefixed Agent: / Receptionist:>"\n'
            '}\n\n'
            "match_score rubric:\n"
            "  100 — available, insurance accepted, meets time/language/accessibility needs\n"
            "   75 — available but minor gaps (e.g. different time slot)\n"
            "   50 — uncertain availability or insurance not confirmed\n"
            "   25 — unavailable but can refer or callback\n"
            "    0 — unreachable, refused, or completely unresponsive"
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
            "language":          "Unknown",
            "available":         None,
            "insurance_accepted": None,
            "wait_time":         None,
            "key_facts":         [],
            "summary":           raw.strip(),
            "match_score":       0,
            "transcript_en":     transcript_text,
        }

    result["clinic_name"] = clinic.get("name")
    result["clinic"]      = clinic

    # Ensure match_score is always an int 0-100
    try:
        result["match_score"] = max(0, min(100, int(result.get("match_score") or 0)))
    except (TypeError, ValueError):
        result["match_score"] = 0

    # ── Store labeled conversation in memory ──────────────────────────────────
    # Keep receptionist/agent turns with original text + English translation
    labeled = [
        {
            "role":     t["role"],          # "receptionist" | "assistant"
            "original": t["text"],
        }
        for t in transcript
    ]
    with _STORE_LOCK:
        _CONVERSATION_STORE[clinic.get("name", "unknown")] = {
            "clinic":       clinic,
            "transcript":   labeled,         # original language, labeled turns
            "transcript_en": result.get("transcript_en", ""),
            "requirements": patient_requirements,
            "fingerprint":  result,
        }

    beacon("swarm-fingerprint", "swarm-matcher", "FingerprintReady", {
        "clinic":             clinic.get("name"),
        "language":           result.get("language"),
        "available":          result.get("available"),
        "insurance_accepted": result.get("insurance_accepted"),
        "match_score":        result.get("match_score"),
        "summary":            result.get("summary"),
    })

    return result
