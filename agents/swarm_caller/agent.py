# swarm_caller — telephony/outreach agent (Engineer 1)
import os
import requests
from common.telemetry import beacon

VOICE_GATEWAY_URL   = os.getenv("VOICE_GATEWAY_URL", "http://localhost:8000")
DEMO_PHONE_FALLBACK = os.getenv("DEMO_PHONE_FALLBACK", "+1-555-DEMO")
VOICE_GW_TIMEOUT    = float(os.getenv("VOICE_GW_TIMEOUT", "10"))


def run(clinic: dict, patient: dict) -> str:
    """Trigger an outbound call to the clinic via the voice gateway.

    clinic  — winner dict from swarm-matcher (name, phone, address, ...)
    patient — profile dict from swarm-profiler (name, language, insurance, ...)

    Emits a CallStarted beacon then hands off to voice_gateway/main.py which
    handles the full Twilio → Gemma → ElevenLabs pipeline from there.

    Returns the Twilio call SID, or '' on failure.
    """
    phone = clinic.get("phone") or DEMO_PHONE_FALLBACK

    beacon("swarm-caller", "clinic", "CallStarted", {
        "clinic": clinic.get("name"),
        "phone": phone,
        "patient": patient.get("name"),
        "language": patient.get("language", "English"),
    })

    try:
        resp = requests.post(
            f"{VOICE_GATEWAY_URL}/call",
            json={
                "to": phone,
                "language": patient.get("language", "English"),
                "patient_name": patient.get("name"),
                "specialty": patient.get("specialty"),
                "insurance": patient.get("insurance"),
                "time_pref": patient.get("time_pref"),
            },
            timeout=VOICE_GW_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("call_sid", "")
    except Exception as e:
        print(f"[swarm-caller] voice gateway error: {e!r}")
        return ""
