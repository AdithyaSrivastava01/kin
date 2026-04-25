"""Voice gateway — FastAPI server handling Twilio WebSocket streams,
language detection via Gemma, and ElevenLabs TTS voice switching.

Run: uvicorn voice_gateway.main:app --host 0.0.0.0 --port 8000
Then: ngrok http 8000
"""

import asyncio
import base64
import json
import os
import time
import uuid

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse
from twilio.rest import Client as TwilioClient

from common.audio_prep import mulaw_8k_to_pcm_16k, validate_wav
from common.telemetry import beacon
from voice_gateway.tts import stream_booking, stream_filler

load_dotenv()

app = FastAPI(title="HealthSwarm Voice Gateway")

twilio_client = TwilioClient(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN"),
)

GEMMA_URL = os.getenv("GEMMA_VULTR_URL", "http://localhost:8088")
NGROK_URL = os.getenv("NGROK_URL", "http://localhost:8000").rstrip("/")
CLIPS_DIR = "/tmp/healthswarm_clips"
os.makedirs(CLIPS_DIR, exist_ok=True)

# Pre-warmed filler audio cache — populated at startup
_FILLER_CACHE: dict[str, bytes] = {}


@app.on_event("startup")
async def _prewarm():
    for lang in ["English", "Korean", "Spanish", "Hindi"]:
        try:
            _FILLER_CACHE[lang] = b"".join(stream_filler(lang))
            print(f"[prewarm] filler/{lang}: {len(_FILLER_CACHE[lang])} bytes")
        except Exception as e:
            print(f"[prewarm] filler/{lang} failed: {e!r}")


# ── Outbound call trigger (called by swarm-caller agent) ────────────


def initiate_call(to_number: str, patient_lang: str = "English") -> str:
    """Place an outbound call via Twilio. Returns the call SID."""
    ngrok_host = NGROK_URL.replace("https://", "").replace("http://", "")
    twiml = (
        "<Response>"
        "<Connect>"
        f'<Stream url="wss://{ngrok_host}/ws/call">'
        f'<Parameter name="patient_lang" value="{patient_lang}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )
    call = twilio_client.calls.create(
        to=to_number,
        from_=os.getenv("TWILIO_PHONE_NUMBER"),
        twiml=twiml,
    )
    return call.sid


# ── REST endpoint: initiate call via HTTP ────────────────────────────


@app.post("/call")
async def call_endpoint(req: Request):
    """HTTP trigger for placing outbound calls."""
    body = await req.json()
    to_number = body["to"]
    patient_lang = body.get("language", "English")
    sid = initiate_call(to_number, patient_lang)
    return {"call_sid": sid, "status": "initiated"}


# ── Public clip route (Gemma fetches audio from here) ────────────────


@app.get("/clips/{clip_id}.wav")
def serve_clip(clip_id: str):
    path = os.path.join(CLIPS_DIR, f"{clip_id}.wav")
    if not os.path.exists(path):
        return {"error": "not found"}, 404
    return FileResponse(path, media_type="audio/wav")


# ── Twilio WebSocket handler ─────────────────────────────────────────


@app.websocket("/ws/call")
async def call_ws(ws: WebSocket):
    await ws.accept()
    stream_sid: str | None = None
    mulaw_buffer = bytearray()
    language_detected: str | None = None
    detection_in_flight = False
    DETECT_AFTER_BYTES = 24_000  # ~3s of μ-law 8kHz (8000 bytes/s)

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            evt = msg.get("event")

            if evt == "start":
                stream_sid = msg["start"]["streamSid"]
                print(f"[ws] start streamSid={stream_sid}")

            elif evt == "media" and not language_detected:
                payload_b64 = msg["media"]["payload"]
                mulaw_buffer.extend(base64.b64decode(payload_b64))

                if len(mulaw_buffer) >= DETECT_AFTER_BYTES and not detection_in_flight:
                    detection_in_flight = True
                    asyncio.create_task(
                        _detect_and_respond(ws, stream_sid, bytes(mulaw_buffer))
                    )

            elif evt == "stop":
                print("[ws] stop")
                break

    except Exception as e:
        print(f"[ws] error: {e!r}")


async def _detect_and_respond(ws: WebSocket, stream_sid: str, mulaw: bytes) -> None:
    """The demo moment: convert → upload → detect → switch voice → speak."""
    t0 = time.perf_counter()
    clip_id = uuid.uuid4().hex
    wav_path = os.path.join(CLIPS_DIR, f"{clip_id}.wav")

    # 1. Convert μ-law 8kHz → PCM 16kHz mono WAV
    mulaw_8k_to_pcm_16k(mulaw, wav_path)
    info = validate_wav(wav_path)
    if not info["ok"]:
        print(f"[detect] WAV validation failed: {info}")
        await _speak_to_call(ws, stream_sid, stream_booking("English"))
        return

    # 2. Public URL Gemma can fetch
    audio_url = f"{NGROK_URL}/clips/{clip_id}.wav"

    # 3. Hit Gemma for language detection
    try:
        r = requests.post(
            f"{GEMMA_URL}/detect-language",
            json={"audio_url": audio_url},
            timeout=8,
        )
        language = r.json().get("language", "English")
    except Exception as e:
        print(f"[detect] gemma failed: {e!r} → fallback English")
        language = "English"

    dt = (time.perf_counter() - t0) * 1000
    print(f"[detect] language={language} latency={dt:.0f}ms")

    # 4. Telemetry → dashboard lights up
    try:
        beacon(
            "swarm-caller",
            "clinic",
            "LanguageDetected",
            {"language": language, "latency_ms": int(dt)},
        )
    except Exception as e:
        print(f"[telemetry] beacon failed (non-fatal): {e!r}")

    # 5. Speak booking script in detected language
    await _speak_to_call(ws, stream_sid, stream_booking(language))


async def _speak_to_call(ws: WebSocket, stream_sid: str, audio_iter) -> None:
    """Stream ulaw_8000 chunks back to Twilio."""
    for chunk in audio_iter:
        await ws.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
            )
        )


# ── Patient-facing filler (called by swarm-intake) ──────────────────


@app.post("/filler")
async def play_filler(req: Request):
    """Return pre-cached filler audio bytes for a given language. <100ms."""
    body = await req.json()
    lang = body.get("language", "English")
    audio = _FILLER_CACHE.get(lang, _FILLER_CACHE.get("English", b""))
    return {
        "audio_b64": base64.b64encode(audio).decode("ascii"),
        "format": "ulaw_8000",
        "language": lang,
    }


# ── Health check ─────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {
        "ok": True,
        "filler_cached": list(_FILLER_CACHE.keys()),
        "gemma_url": GEMMA_URL,
    }
