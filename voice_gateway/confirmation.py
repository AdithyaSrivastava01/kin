"""Extract structured booking confirmation from receptionist speech.

Pipeline: receptionist audio → Gemma /translate → ASI:One structured parse.
Returns: {doctor, date, time, address, instructions} or partial.
"""

import json
import os

import requests

from common.asi import asi_chat

GEMMA_URL = os.getenv("GEMMA_VULTR_URL", "http://localhost:8088")

_EXTRACT_SYSTEM = """\
You are a medical appointment data extractor. Given a transcript of a \
receptionist's response during an appointment booking call, extract any \
confirmed booking details.

Return ONLY valid JSON with these fields (use null if not mentioned):
{
  "status": "booked" | "unavailable" | "callback_needed" | "unclear",
  "doctor_name": string | null,
  "date": string | null,
  "time": string | null,
  "address": string | null,
  "instructions": string | null
}
No markdown. No explanation. Just the JSON object."""


def extract_confirmation(audio_url: str) -> dict:
    """Translate receptionist audio and extract structured booking info."""
    # Step 1: Translate via Gemma
    try:
        r = requests.post(
            f"{GEMMA_URL}/translate",
            json={"audio_url": audio_url, "target_lang": "en"},
            timeout=15,
        )
        transcript = r.json().get("text", "")
    except Exception as e:
        return {"status": "unclear", "error": f"translation failed: {e!r}"}

    if not transcript.strip():
        return {"status": "unclear", "error": "empty transcript"}

    # Step 2: ASI:One structured extraction
    try:
        raw = asi_chat(_EXTRACT_SYSTEM, transcript, max_tokens=256)
        return json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        return {"status": "unclear", "transcript": transcript, "error": str(e)}
