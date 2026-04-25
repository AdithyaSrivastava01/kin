"""Voice gateway — FastAPI server handling Twilio WebSocket streams,
language detection via Gemma, and ElevenLabs TTS voice switching.

Run: uvicorn voice_gateway.main:app --host 0.0.0.0 --port 8000
Then: ngrok http 8000
"""

import asyncio
import base64
import glob
import json
import os
import re
import time
import uuid
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from twilio.rest import Client as TwilioClient

from common.audio_prep import mulaw_8k_to_pcm_16k, validate_wav
from common.telemetry import beacon
from voice_gateway.confirmation import extract_confirmation
from voice_gateway.conversation import ConversationState
from voice_gateway.tts import (
    speak_text,
    stream_booking,
    stream_disclosure,
    stream_filler,
)

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

SUPPORTED_LANGUAGES = {"English", "Korean", "Spanish", "Hindi", "Marathi"}
CLIP_MAX_AGE_S = 300  # delete WAV clips older than 5 minutes
CLIP_CLEANUP_INTERVAL_S = 60  # run cleanup every 60 seconds

# Pre-warmed filler audio cache — populated at startup
_FILLER_CACHE: dict[str, bytes] = {}

# Booking context passed from /call endpoint to WebSocket session
# Keyed by call SID, consumed once the WS connects
_CALL_CONTEXT: dict[str, dict] = {}

# Call outcome tracking — set by WS handler, read by fallthrough logic
# Values: asyncio.Future resolving to {"status": "booked"|"failed"|"no_answer", ...}
_CALL_OUTCOMES: dict[str, asyncio.Future] = {}

MAX_FALLTHROUGH_ATTEMPTS = 3


async def _cleanup_clips_loop() -> None:
    """Periodically delete WAV clips older than CLIP_MAX_AGE_S."""
    while True:
        await asyncio.sleep(CLIP_CLEANUP_INTERVAL_S)
        now = time.time()
        removed = 0
        for path in glob.glob(os.path.join(CLIPS_DIR, "*.wav")):
            try:
                if now - os.path.getmtime(path) > CLIP_MAX_AGE_S:
                    os.unlink(path)
                    removed += 1
            except OSError:
                pass
        if removed:
            print(f"[cleanup] removed {removed} stale clips")


@app.on_event("startup")
async def _prewarm():
    asyncio.create_task(_cleanup_clips_loop())
    loop = asyncio.get_event_loop()
    for lang in SUPPORTED_LANGUAGES:
        try:
            raw = await loop.run_in_executor(
                None, lambda l=lang: b"".join(stream_filler(l))
            )
            _FILLER_CACHE[lang] = raw
            print(f"[prewarm] filler/{lang}: {len(raw)} bytes")
        except Exception as e:
            print(f"[prewarm] filler/{lang} failed: {e!r}")


# ── Outbound call trigger (called by swarm-caller agent) ────────────


def initiate_call(
    to_number: str,
    patient_lang: str = "English",
    patient_name: str | None = None,
    specialty: str | None = None,
    insurance: str | None = None,
    time_pref: str | None = None,
) -> str:
    """Place an outbound call via Twilio. Returns the call SID."""
    # Sanitize patient_lang to prevent TwiML injection — allow only letters/spaces
    safe_lang = re.sub(r"[^a-zA-Z ]", "", patient_lang) or "English"
    ngrok_host = NGROK_URL.replace("https://", "").replace("http://", "")
    twiml = (
        "<Response>"
        "<Connect>"
        f'<Stream url="wss://{ngrok_host}/ws/call">'
        f'<Parameter name="patient_lang" value="{safe_lang}" />'
        "</Stream>"
        "</Connect>"
        "</Response>"
    )
    call = twilio_client.calls.create(
        to=to_number,
        from_=os.getenv("TWILIO_PHONE_NUMBER"),
        twiml=twiml,
    )
    # Store booking context so the WS handler can build a dynamic script
    _CALL_CONTEXT[call.sid] = {
        "patient_name": patient_name,
        "specialty": specialty,
        "insurance": insurance,
        "time_pref": time_pref,
    }
    return call.sid


async def call_with_fallthrough(
    ranked_clinics: list[dict],
    patient_lang: str = "English",
    patient_name: str | None = None,
    specialty: str | None = None,
    insurance: str | None = None,
    time_pref: str | None = None,
) -> dict:
    """Try calling ranked clinics in order until one succeeds or attempts exhausted.

    Each clinic dict must have at minimum {"phone": str, "name": str}.
    Returns {"status": "booked"|"exhausted", "clinic": ..., "attempts": int}.
    """
    attempts = min(len(ranked_clinics), MAX_FALLTHROUGH_ATTEMPTS)
    for i in range(attempts):
        clinic = ranked_clinics[i]
        phone = clinic["phone"]
        clinic_name = clinic.get("name", phone)

        print(f"[fallthrough] attempt {i + 1}/{attempts}: {clinic_name}")

        outcome_future: asyncio.Future = asyncio.get_event_loop().create_future()
        sid = initiate_call(
            to_number=phone,
            patient_lang=patient_lang,
            patient_name=patient_name,
            specialty=specialty,
            insurance=insurance,
            time_pref=time_pref,
        )
        _CALL_OUTCOMES[sid] = outcome_future

        try:
            result = await asyncio.wait_for(outcome_future, timeout=120)
        except asyncio.TimeoutError:
            result = {"status": "no_answer"}
        finally:
            _CALL_OUTCOMES.pop(sid, None)

        beacon(
            "swarm-caller",
            "clinic",
            "CallAttempt",
            {
                "clinic": clinic_name,
                "attempt": i + 1,
                "outcome": result.get("status", "unknown"),
            },
        )

        if result.get("status") == "booked":
            return {"status": "booked", "clinic": clinic, "attempts": i + 1, **result}

        print(f"[fallthrough] {clinic_name} → {result.get('status')}, trying next")

    return {"status": "exhausted", "attempts": attempts}


def report_call_outcome(call_sid: str, outcome: dict) -> None:
    """Called by WS handler or external hook to report how a call ended."""
    future = _CALL_OUTCOMES.get(call_sid)
    if future and not future.done():
        future.set_result(outcome)


# ── REST endpoint: initiate call via HTTP ────────────────────────────


@app.post("/call")
async def call_endpoint(req: Request):
    """HTTP trigger for placing outbound calls."""
    body = await req.json()
    sid = initiate_call(
        to_number=body["to"],
        patient_lang=body.get("language", "English"),
        patient_name=body.get("patient_name"),
        specialty=body.get("specialty"),
        insurance=body.get("insurance"),
        time_pref=body.get("time_pref"),
    )
    return {"call_sid": sid, "status": "initiated"}


@app.post("/call/fallthrough")
async def call_fallthrough_endpoint(req: Request):
    """Try ranked clinics in order until booking succeeds or attempts exhausted."""
    body = await req.json()
    result = await call_with_fallthrough(
        ranked_clinics=body["clinics"],
        patient_lang=body.get("language", "English"),
        patient_name=body.get("patient_name"),
        specialty=body.get("specialty"),
        insurance=body.get("insurance"),
        time_pref=body.get("time_pref"),
    )
    return result


# ── Public clip route (Gemma fetches audio from here) ────────────────


@app.get("/clips/{clip_id}.wav")
def serve_clip(clip_id: str):
    # Prevent path traversal — clip_id must be alphanumeric (hex uuid)
    if not clip_id.isalnum():
        return JSONResponse({"error": "invalid clip id"}, status_code=400)
    path = os.path.join(CLIPS_DIR, f"{clip_id}.wav")
    if not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, media_type="audio/wav")


# ── Twilio WebSocket handler ─────────────────────────────────────────


CONVO_TURN_BYTES = 24_000  # ~3s of μ-law 8kHz — one conversational turn buffer
CONVO_SILENCE_TIMEOUT_S = 5.0  # if no new audio for 5s, process what we have


@app.websocket("/ws/call")
async def call_ws(ws: WebSocket):
    await ws.accept()
    stream_sid: str | None = None
    mulaw_buffer = bytearray()
    state: dict = {
        "language_detected": None,
        "detection_in_flight": False,
        "phase": "detecting",  # detecting → conversing → done
        "speaking": False,  # True while TTS is playing (don't buffer our own echo)
    }
    booking_ctx: dict = {}
    convo_buffer = bytearray()
    last_media_ts: float = 0.0
    DETECT_AFTER_BYTES = 24_000

    call_sid = ""
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            evt = msg.get("event")

            if evt == "start":
                stream_sid = msg["start"]["streamSid"]
                call_sid = msg["start"].get("callSid", "")
                print(f"[ws] start streamSid={stream_sid} callSid={call_sid}")
                booking_ctx = _CALL_CONTEXT.pop(call_sid, {})
                asyncio.create_task(
                    _speak_to_call(ws, stream_sid, "English", stream_disclosure)
                )

            elif evt == "media":
                payload_b64 = msg["media"]["payload"]
                audio_bytes = base64.b64decode(payload_b64)
                last_media_ts = time.time()

                # Phase 1: language detection
                if state["phase"] == "detecting":
                    mulaw_buffer.extend(audio_bytes)
                    if (
                        len(mulaw_buffer) >= DETECT_AFTER_BYTES
                        and not state["detection_in_flight"]
                    ):
                        state["detection_in_flight"] = True
                        asyncio.create_task(
                            _detect_and_respond(
                                ws,
                                stream_sid,
                                bytes(mulaw_buffer),
                                state,
                                booking_ctx,
                            )
                        )

                # Phase 2: multi-turn conversation
                elif state["phase"] == "conversing" and not state["speaking"]:
                    convo_buffer.extend(audio_bytes)
                    if len(convo_buffer) >= CONVO_TURN_BYTES:
                        buf = bytes(convo_buffer)
                        convo_buffer.clear()
                        asyncio.create_task(
                            _conversation_turn(ws, stream_sid, buf, state)
                        )

            elif evt == "stop":
                print("[ws] stop")
                outcome = state.get("call_outcome", {"status": "completed"})
                convo = state.get("convo")
                if convo:
                    outcome["booking_status"] = convo.booking_status
                    outcome["turns"] = convo.turns
                report_call_outcome(call_sid, outcome)
                break

    except Exception as e:
        print(f"[ws] error: {e!r}")
        report_call_outcome(call_sid, {"status": "failed", "error": str(e)})


async def _detect_and_respond(
    ws: WebSocket,
    stream_sid: str,
    mulaw: bytes,
    state: dict,
    booking_ctx: dict | None = None,
) -> None:
    """The demo moment: convert → upload → detect → switch voice → speak."""
    loop = asyncio.get_event_loop()
    t0 = time.perf_counter()
    clip_id = uuid.uuid4().hex
    wav_path = os.path.join(CLIPS_DIR, f"{clip_id}.wav")

    # 1. Convert μ-law 8kHz → PCM 16kHz mono WAV (run in thread — subprocess)
    await loop.run_in_executor(None, mulaw_8k_to_pcm_16k, mulaw, wav_path)
    info = await loop.run_in_executor(None, validate_wav, wav_path)
    if not info["ok"]:
        print(f"[detect] WAV validation failed: {info}")
        await _speak_to_call(ws, stream_sid, "English")
        state["language_detected"] = "English"
        return

    # 2. Public URL Gemma can fetch
    audio_url = f"{NGROK_URL}/clips/{clip_id}.wav"

    # 3. Hit Gemma for language detection (run in thread — blocking HTTP)
    def _call_gemma() -> str:
        try:
            r = requests.post(
                f"{GEMMA_URL}/detect-language",
                json={"audio_url": audio_url},
                timeout=8,
            )
            return r.json().get("language", "English")
        except Exception as e:
            print(f"[detect] gemma failed: {e!r} → fallback English")
            return "English"

    language = await loop.run_in_executor(None, _call_gemma)

    # 3b. Normalize unsupported language → English fallback
    if language not in SUPPORTED_LANGUAGES:
        print(f"[detect] unsupported language '{language}' → fallback English")
        language = "English"

    dt = (time.perf_counter() - t0) * 1000
    print(f"[detect] language={language} latency={dt:.0f}ms")

    # 4. Mark detection complete so WS loop stops buffering
    state["language_detected"] = language

    # 5. Telemetry → dashboard lights up
    try:
        beacon(
            "swarm-caller",
            "clinic",
            "LanguageDetected",
            {"language": language, "latency_ms": int(dt)},
        )
    except Exception as e:
        print(f"[telemetry] beacon failed (non-fatal): {e!r}")

    # 6. Speak booking script in detected language with dynamic context
    ctx = booking_ctx or {}
    state["speaking"] = True
    await _speak_to_call(
        ws,
        stream_sid,
        language,
        tts_source=lambda: stream_booking(
            language=language,
            patient_name=ctx.get("patient_name"),
            specialty=ctx.get("specialty"),
            insurance=ctx.get("insurance"),
            time_pref=ctx.get("time_pref"),
        ),
    )
    state["speaking"] = False

    # 7. Transition to multi-turn conversation phase
    state["convo"] = ConversationState(
        patient_name=ctx.get("patient_name", "the patient"),
        specialty=ctx.get("specialty", "a doctor"),
        insurance=ctx.get("insurance", "private"),
        time_pref=ctx.get("time_pref", "this week"),
    )
    state["phase"] = "conversing"
    print(f"[convo] entering conversation loop (lang={language})")


async def _conversation_turn(
    ws: WebSocket,
    stream_sid: str,
    mulaw: bytes,
    state: dict,
) -> None:
    """One turn of the conversation loop: translate → LLM → TTS."""
    convo: ConversationState = state["convo"]
    language = state["language_detected"]
    loop = asyncio.get_event_loop()

    if convo.is_terminal or convo.turns >= ConversationState.MAX_TURNS:
        state["phase"] = "done"
        state["call_outcome"] = {"status": convo.booking_status}
        print(f"[convo] terminal after {convo.turns} turns: {convo.booking_status}")
        return

    # 1. Convert buffered audio to WAV
    clip_id = uuid.uuid4().hex
    wav_path = os.path.join(CLIPS_DIR, f"{clip_id}.wav")
    await loop.run_in_executor(None, mulaw_8k_to_pcm_16k, mulaw, wav_path)
    audio_url = f"{NGROK_URL}/clips/{clip_id}.wav"

    # 2. Translate receptionist speech via Gemma
    def _translate() -> str:
        try:
            r = requests.post(
                f"{GEMMA_URL}/translate",
                json={"audio_url": audio_url, "target_lang": "en"},
                timeout=15,
            )
            return r.json().get("text", "")
        except Exception as e:
            print(f"[convo] translate failed: {e!r}")
            return ""

    transcript = await loop.run_in_executor(None, _translate)
    if not transcript.strip():
        print("[convo] empty transcript, skipping turn")
        return

    print(f"[convo] receptionist said: {transcript[:100]}")

    # 3. Generate next response via ASI:One
    response_text = await loop.run_in_executor(None, convo.next_response, transcript)
    print(f"[convo] responding: {response_text[:100]} (status={convo.booking_status})")

    # 4. Speak response back
    state["speaking"] = True
    await _speak_to_call(
        ws,
        stream_sid,
        language,
        tts_source=lambda: speak_text(response_text, language),
    )
    state["speaking"] = False

    # 5. Check terminal state
    if convo.is_terminal:
        state["phase"] = "done"
        state["call_outcome"] = {"status": convo.booking_status}
        beacon(
            "swarm-caller",
            "clinic",
            "BookingResult",
            {"status": convo.booking_status, "turns": convo.turns},
        )


async def _speak_to_call(
    ws: WebSocket,
    stream_sid: str,
    language: str,
    tts_source=None,
) -> None:
    """Stream TTS ulaw_8000 chunks back to Twilio without blocking event loop."""
    loop = asyncio.get_event_loop()

    # Collect TTS chunks in a thread (ElevenLabs SDK is sync)
    def _collect() -> list[bytes]:
        source = tts_source if tts_source else lambda: stream_booking(language)
        return list(source())

    chunks = await loop.run_in_executor(None, _collect)
    for chunk in chunks:
        await ws.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
            )
        )


# ── Booking confirmation extraction ─────────────────────────────────


@app.post("/extract-confirmation")
async def extract_confirmation_endpoint(req: Request):
    """Extract structured booking details from receptionist audio."""
    body = await req.json()
    audio_url = body.get("audio_url")
    if not audio_url:
        return JSONResponse({"error": "audio_url required"}, status_code=400)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, extract_confirmation, audio_url)
    return result


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
