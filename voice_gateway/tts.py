"""ElevenLabs TTS — voice map, filler audio, and booking scripts.

Uses eleven_flash_v2_5 for sub-200ms first-byte latency.
All output is ulaw_8000 for direct Twilio Media Streams playback.
"""

import os

from elevenlabs import ElevenLabs

eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Voice IDs from elevenlabs.io/voice-library — pick multilingual voices
VOICE_MAP: dict[str, str] = {
    "English": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    "Korean": "jBpfuIE2acCO8z3wKNLl",  # Gigi
    "Spanish": "EXAVITQu4vr4xnSDxMaL",  # Bella
    "Hindi": "pNInz6obpgDQGcFmaJgB",  # Adam
    "Marathi": "pNInz6obpgDQGcFmaJgB",  # Adam (supports Marathi)
}

AI_DISCLOSURE = (
    "Hello, this is an AI assistant calling on behalf of a patient "
    "to book a medical appointment. How can I proceed?"
)

FILLER_TEXTS: dict[str, str] = {
    "English": "I'm finding the right clinic for you now, just a moment.",
    "Korean": "지금 맞는 병원을 찾고 있습니다. 잠시만 기다려 주세요.",
    "Spanish": "Estoy buscando la clínica adecuada para usted, un momento por favor.",
    "Hindi": "मैं आपके लिए सही क्लिनिक खोज रहा हूँ, एक पल रुकिए।",
    "Marathi": "मी तुमच्यासाठी योग्य क्लिनिक शोधत आहे, कृपया एक क्षण थांबा.",
}

BOOKING_TEMPLATES: dict[str, str] = {
    "English": (
        "I'm calling on behalf of {patient_name} to book an appointment "
        "with a {specialty}. They have {insurance} insurance. "
        "Do you have any availability {time_pref}?"
    ),
    "Korean": (
        "{patient_name} 환자를 대신해서 {specialty} 예약 전화를 드립니다. "
        "보험은 {insurance}입니다. {time_pref}에 가능한 시간이 있을까요?"
    ),
    "Spanish": (
        "Llamo en nombre de {patient_name} para reservar una cita con "
        "un {specialty}. Tiene seguro {insurance}. "
        "¿Tienen disponibilidad {time_pref}?"
    ),
    "Hindi": (
        "मैं {patient_name} की ओर से {specialty} के साथ अपॉइंटमेंट बुक "
        "करने के लिए कॉल कर रहा हूँ। उनका बीमा {insurance} है। "
        "क्या {time_pref} कोई समय उपलब्ध है?"
    ),
    "Marathi": (
        "मी {patient_name} यांच्या वतीने {specialty} ची अपॉइंटमेंट बुक "
        "करण्यासाठी कॉल करत आहे. त्यांचा विमा {insurance} आहे. "
        "{time_pref} काही वेळ उपलब्ध आहे का?"
    ),
}

# Defaults used when booking context is incomplete
_BOOKING_DEFAULTS: dict[str, str] = {
    "patient_name": "a patient",
    "specialty": "a doctor",
    "insurance": "private",
    "time_pref": "this week",
}


def build_booking_script(
    language: str = "English",
    patient_name: str | None = None,
    specialty: str | None = None,
    insurance: str | None = None,
    time_pref: str | None = None,
) -> str:
    """Fill booking template with context from swarm-matcher payload."""
    template = BOOKING_TEMPLATES.get(language, BOOKING_TEMPLATES["English"])
    return template.format(
        patient_name=patient_name or _BOOKING_DEFAULTS["patient_name"],
        specialty=specialty or _BOOKING_DEFAULTS["specialty"],
        insurance=insurance or _BOOKING_DEFAULTS["insurance"],
        time_pref=time_pref or _BOOKING_DEFAULTS["time_pref"],
    )


def _voice(lang: str) -> str:
    return VOICE_MAP.get(lang, VOICE_MAP["English"])


def stream_disclosure():
    """AI identity disclosure — plays immediately on call connect (English)."""
    return eleven.text_to_speech.stream(
        voice_id=_voice("English"),
        output_format="ulaw_8000",
        text=AI_DISCLOSURE,
        model_id="eleven_flash_v2_5",
    )


def stream_filler(language: str = "English"):
    """Generate filler audio in target language. Output: ulaw_8000 chunks."""
    return eleven.text_to_speech.stream(
        voice_id=_voice(language),
        output_format="ulaw_8000",
        text=FILLER_TEXTS.get(language, FILLER_TEXTS["English"]),
        model_id="eleven_flash_v2_5",
    )


def stream_booking(
    language: str = "English",
    patient_name: str | None = None,
    specialty: str | None = None,
    insurance: str | None = None,
    time_pref: str | None = None,
):
    """Generate booking script audio in target language. Output: ulaw_8000 chunks."""
    script = build_booking_script(
        language, patient_name, specialty, insurance, time_pref
    )
    return eleven.text_to_speech.stream(
        voice_id=_voice(language),
        output_format="ulaw_8000",
        text=script,
        model_id="eleven_flash_v2_5",
    )


def speak_text(text: str, language: str = "English"):
    """Generic TTS for ad-hoc lines during a call."""
    return eleven.text_to_speech.stream(
        voice_id=_voice(language),
        output_format="ulaw_8000",
        text=text,
        model_id="eleven_flash_v2_5",
    )
