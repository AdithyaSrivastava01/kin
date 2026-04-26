"""Voice gateway — FastAPI service that fronts ElevenLabs Conversational AI.

All call audio (STT, LLM, TTS, turn-taking, barge-in) is handled by the
ElevenLabs agent server-side; this gateway is a thin shim:

    POST /call               -> initiate an outbound call via the agent
    GET  /transcript/{sid}   -> poll the agent's conversation for outcome
    GET  /health             -> liveness + config check

swarm-caller talks to these two endpoints; the rest of the swarm is
unaware that ElevenLabs runs the dialogue.
"""

import asyncio
import os
import re

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from voice_gateway import eleven_caller

load_dotenv()

app = FastAPI(title="HealthSwarm Voice Gateway")


@app.post("/call")
async def call_endpoint(req: Request):
    """Initiate an outbound call via the ElevenLabs Conversational AI agent.

    Body fields are forwarded into the agent's dynamic_variables so the
    dashboard prompt can reference {{patient_name}}, {{specialty}},
    {{problem}}, {{insurance}}, {{tests_needed}}, {{time_pref}},
    {{language}} verbatim.
    """
    body = await req.json()
    patient_context = {
        "patient_name": body.get("patient_name"),
        "specialty": body.get("specialty"),
        "problem": body.get("problem"),
        "insurance": body.get("insurance"),
        "tests_needed": body.get("tests_needed"),
        "time_pref": body.get("time_pref"),
        "language": body.get("language", "English"),
    }
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: eleven_caller.place_call(body["to"], patient_context),
        )
    except Exception as e:
        return JSONResponse(
            {"error": f"failed to place call: {e!r}"}, status_code=502
        )
    return {
        "call_sid": result["call_sid"],
        "conversation_id": result["conversation_id"],
        "status": "initiated",
    }


@app.get("/transcript/{call_sid}")
async def get_transcript(call_sid: str):
    """Return the transcript + result for a completed call.

    Returns 202 while the agent's conversation is still in progress,
    200 with the transcript + booking outcome once it ends.
    """
    if not re.fullmatch(r"CA[A-Za-z0-9]{32}", call_sid):
        return JSONResponse({"error": "invalid call_sid"}, status_code=400)

    loop = asyncio.get_event_loop()
    state = await loop.run_in_executor(
        None, lambda: eleven_caller.fetch_call_state(call_sid)
    )
    if state is None:
        return JSONResponse({"error": "unknown call_sid"}, status_code=404)
    if state.get("status") not in ("done", "failed"):
        return JSONResponse(
            {"status": state.get("status", "pending")}, status_code=202
        )
    return {
        "call_sid": call_sid,
        "transcript": state.get("transcript", []),
        "result": {
            "status": "completed" if state.get("status") == "done" else state.get("status"),
            "booking_status": _derive_booking_status(state),
            "booking_result": state.get("booking_result"),
            "summary": state.get("summary"),
            "call_successful": state.get("call_successful"),
        },
    }


def _derive_booking_status(state: dict) -> str:
    """Map the agent's report_booking output (or absence thereof) onto
    the in_progress / booked / failed / callback_needed enum that
    swarm-fingerprint and swarm-matcher already understand.
    """
    br = state.get("booking_result") or {}
    s = str(br.get("status", "")).lower()
    if s in ("booked", "failed", "callback_needed"):
        return s
    if state.get("call_successful") == "success":
        return "booked"
    if state.get("status") == "failed":
        return "failed"
    return "in_progress"


@app.get("/health")
def health():
    return {
        "ok": True,
        "call_path": "elevenlabs:conversational_ai",
        "agent_id_set": bool(os.getenv("BOOKING_AGENT_ID")),
        "phone_number_id_set": bool(os.getenv("ELEVENLABS_PHONE_NUMBER_ID")),
    }
