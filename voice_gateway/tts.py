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

BOOKING_SCRIPTS: dict[str, str] = {
    "English": (
        "Hello, I'm an AI assistant calling on behalf of a patient to "
        "book an appointment. They need to see a dermatologist. "
        "Do you have any availability this week?"
    ),
    "Korean": (
        "안녕하세요, 환자를 대신해서 예약 전화를 드리는 AI 어시스턴트입니다. "
        "피부과 진료 예약이 필요한데, 이번 주에 가능한 시간이 있을까요?"
    ),
    "Spanish": (
        "Hola, soy un asistente de inteligencia artificial llamando "
        "en nombre de un paciente para reservar una cita. Necesita "
        "ver a un dermatólogo. ¿Tienen disponibilidad esta semana?"
    ),
    "Hindi": (
        "नमस्ते, मैं एक मरीज की ओर से अपॉइंटमेंट बुक करने के लिए कॉल "
        "कर रहा एक AI सहायक हूँ। उन्हें त्वचा विशेषज्ञ को दिखाना है। "
        "क्या इस हफ्ते कोई समय उपलब्ध है?"
    ),
    "Marathi": (
        "नमस्कार, मी एका रुग्णाच्या वतीने अपॉइंटमेंट बुक करण्यासाठी "
        "कॉल करत असलेला AI सहाय्यक आहे. त्यांना त्वचारोग तज्ञांना "
        "भेटायचे आहे. या आठवड्यात काही वेळ उपलब्ध आहे का?"
    ),
}


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


def stream_booking(language: str = "English"):
    """Generate booking script audio in target language. Output: ulaw_8000 chunks."""
    return eleven.text_to_speech.stream(
        voice_id=_voice(language),
        output_format="ulaw_8000",
        text=BOOKING_SCRIPTS.get(language, BOOKING_SCRIPTS["English"]),
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
