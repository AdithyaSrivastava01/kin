"""ElevenLabs Conversational AI outbound caller.

Replaces the WebSocket-based call path in voice_gateway/main.py.
ElevenLabs runs the agent server-side (streaming STT, streaming LLM,
streaming TTS, native barge-in, telephony-tuned VAD) — we just kick
off the call and poll the conversation API for the transcript and the
agent's report_booking tool result.

Required env vars:
  BOOKING_AGENT_ID            — agent created at elevenlabs.io/app/conversational-ai
  ELEVENLABS_PHONE_NUMBER_ID  — phone number assigned to that agent
  ELEVENLABS_API_KEY          — needs the convai_write + convai_read scopes
"""

from __future__ import annotations

import json
import os
import threading
import time

from elevenlabs import ElevenLabs
from elevenlabs.types.conversation_initiation_client_data_request_input import (
    ConversationInitiationClientDataRequestInput,
)


_BOOKING_AGENT_ID = lambda: os.getenv("BOOKING_AGENT_ID", "")
_PHONE_NUMBER_ID = lambda: os.getenv("ELEVENLABS_PHONE_NUMBER_ID", "")
_REPORT_TOOL_NAME = os.getenv("REPORT_BOOKING_TOOL_NAME", "report_booking")

_client_singleton: ElevenLabs | None = None
_client_lock = threading.Lock()


def _client() -> ElevenLabs:
    """Lazy-init the SDK client so the API key is read AFTER load_dotenv()."""
    global _client_singleton
    with _client_lock:
        if _client_singleton is None:
            api_key = os.getenv("ELEVENLABS_API_KEY")
            if not api_key:
                raise RuntimeError("ELEVENLABS_API_KEY not set")
            _client_singleton = ElevenLabs(api_key=api_key)
    return _client_singleton


# In-memory call registry. Maps the Twilio call SID (so swarm-caller's
# existing /transcript/{call_sid} polling keeps working) to the
# ElevenLabs conversation_id and any cached final result.
#
# Entries are cleaned up by the gateway's existing _cleanup_clips_loop
# heartbeat, which deletes stale entries past CLIP_MAX_AGE_S.
_CALLS: dict[str, dict] = {}
_CALLS_LOCK = threading.Lock()


def _build_dynamic_variables(patient_context: dict) -> dict:
    """Map our patient_context dict onto the {{var}} placeholders the
    booking agent's dashboard system prompt expects."""
    return {
        "patient_name": str(patient_context.get("patient_name") or "the patient"),
        "specialty": str(patient_context.get("specialty") or "a doctor"),
        "problem": str(patient_context.get("problem") or "a routine consultation"),
        "insurance": str(patient_context.get("insurance") or "private insurance"),
        "tests_needed": str(patient_context.get("tests_needed") or "none"),
        "time_pref": str(patient_context.get("time_pref") or "this week"),
        "language": str(patient_context.get("language") or "English"),
    }


def place_call(to_number: str, patient_context: dict) -> dict:
    """Initiate an outbound ElevenLabs Conversational AI call.

    Returns {"call_sid", "conversation_id", "success", "message"}.
    Raises RuntimeError if BOOKING_AGENT_ID / ELEVENLABS_PHONE_NUMBER_ID
    aren't configured, or if the SDK call fails.
    """
    from elevenlabs.core.api_error import ApiError

    agent_id = _BOOKING_AGENT_ID()
    phone_number_id = _PHONE_NUMBER_ID()
    if not (agent_id and phone_number_id):
        raise RuntimeError(
            "BOOKING_AGENT_ID and ELEVENLABS_PHONE_NUMBER_ID must be set in .env"
        )

    cid = ConversationInitiationClientDataRequestInput(
        dynamic_variables=_build_dynamic_variables(patient_context),
    )
    try:
        resp = _client().conversational_ai.twilio.outbound_call(
            agent_id=agent_id,
            agent_phone_number_id=phone_number_id,
            to_number=to_number,
            conversation_initiation_client_data=cid,
        )
    except ApiError as e:
        status = getattr(e, "status_code", None)
        body = getattr(e, "body", None)
        raise RuntimeError(
            f"ElevenLabs outbound_call failed: status={status} body={body}"
        ) from e

    call_sid = resp.call_sid or ""
    conv_id = resp.conversation_id or ""
    if not call_sid or not conv_id:
        raise RuntimeError(
            f"ElevenLabs returned empty IDs (success={resp.success} message={resp.message!r})"
        )

    with _CALLS_LOCK:
        _CALLS[call_sid] = {
            "conversation_id": conv_id,
            "patient_context": patient_context,
            "started_at": time.time(),
            "result": None,  # populated once status is terminal
        }

    return {
        "call_sid": call_sid,
        "conversation_id": conv_id,
        "success": bool(resp.success),
        "message": resp.message or "",
    }


def _serialize_transcript(conv) -> tuple[list[dict], dict | None]:
    """Flatten the SDK transcript into the simple list-of-dicts shape the
    swarm-fingerprint agent already understands, and surface any
    report_booking tool call params.
    """
    out: list[dict] = []
    booking_result: dict | None = None
    for entry in (conv.transcript or []):
        # ElevenLabs role is "user" (receptionist) or "agent" (our bot).
        # swarm-fingerprint's prompt expects "receptionist"/"assistant".
        role_in = getattr(entry, "role", "user")
        role_out = "receptionist" if role_in == "user" else "assistant"
        text = (getattr(entry, "message", None) or "").strip()
        if text:
            out.append({"role": role_out, "text": text})

        for tc in (getattr(entry, "tool_calls", None) or []):
            if getattr(tc, "tool_name", None) != _REPORT_TOOL_NAME:
                continue
            try:
                booking_result = json.loads(getattr(tc, "params_as_json", "") or "{}")
            except (json.JSONDecodeError, ValueError):
                booking_result = {"raw": getattr(tc, "params_as_json", "")}
    return out, booking_result


def _is_terminal(status: str) -> bool:
    return status in ("done", "failed")


def fetch_call_state(call_sid: str) -> dict | None:
    """Return the current state of a call, querying ElevenLabs if needed.

    Caches the result once the conversation reaches a terminal status
    so subsequent polls are instant.

    Returns None if call_sid is unknown.
    Returns {"status": "pending", ...} while ElevenLabs is still working.
    Returns the full result dict once terminal.
    """
    with _CALLS_LOCK:
        entry = _CALLS.get(call_sid)
        if entry is None:
            return None
        if entry["result"] is not None:
            return entry["result"]
        conv_id = entry["conversation_id"]

    try:
        conv = _client().conversational_ai.conversations.get(conv_id)
    except Exception as e:
        return {
            "call_sid": call_sid,
            "conversation_id": conv_id,
            "status": "pending",
            "poll_error": repr(e),
        }

    status = str(getattr(conv, "status", "") or "")
    if not _is_terminal(status):
        return {
            "call_sid": call_sid,
            "conversation_id": conv_id,
            "status": status or "pending",
        }

    transcript, booking_result = _serialize_transcript(conv)
    analysis = getattr(conv, "analysis", None)
    summary = getattr(analysis, "transcript_summary", None) if analysis else None
    call_successful = (
        str(getattr(analysis, "call_successful", "unknown")) if analysis else "unknown"
    )

    result = {
        "call_sid": call_sid,
        "conversation_id": conv_id,
        "status": status,
        "transcript": transcript,
        "booking_result": booking_result,
        "summary": summary,
        "call_successful": call_successful,
    }
    with _CALLS_LOCK:
        if call_sid in _CALLS:
            _CALLS[call_sid]["result"] = result
    return result


def evict_old_calls(max_age_s: float) -> int:
    """Drop call entries older than max_age_s. Returns the count removed."""
    cutoff = time.time() - max_age_s
    removed = 0
    with _CALLS_LOCK:
        for sid in list(_CALLS):
            if _CALLS[sid]["started_at"] < cutoff:
                _CALLS.pop(sid, None)
                removed += 1
    return removed
