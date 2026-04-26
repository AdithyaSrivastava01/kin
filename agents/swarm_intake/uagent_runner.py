"""uAgent wrapper for swarm-intake (orchestrator).
Exposes the intake agent via ASI:One Chat Protocol so it can be
discovered and messaged through Agentverse / ASI:One.

Usage (from kin/):
  ../.venv/bin/python -m agents.swarm_intake.uagent_runner
"""
import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncio

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Python 3.10+ no longer auto-creates an event loop; uagents needs one up-front
asyncio.set_event_loop(asyncio.new_event_loop())

from uagents import Agent, Context, Model, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

# ── Agentverse registration ──────────────────────────────────────────────────
agent = Agent(
    name="healthswarm-intake",
    seed=os.environ["INTAKE_SEED"],
    port=8010,
    mailbox=True,
    publish_agent_details=True,
)

protocol = Protocol(spec=chat_protocol_spec)

_PERSONA_MAP = {
    "maria": "maria-001",
    "joon":  "joon-001",
    "rahul": "rahul-001",
}

# Specialty keywords → fallback demo patient when no name is recognised
_SPECIALTY_FALLBACK = [
    (["cardiol", "heart", "chest pain", "cardiac"], "rahul-001"),
    (["dermat", "skin", "rash", "acne"],            "joon-001"),
    (["primary care", "general", "family", "spanish", "gyno", "obgyn"], "maria-001"),
]


def _extract_caller_name(text: str) -> str | None:
    """Best-effort extraction of the caller's first name from free text.
    Used when no demo persona is matched so the ElevenLabs agent uses the
    real name on the call instead of the fallback persona name.
    """
    import re
    # OmegaClaw prepends Telegram username: "Adi: Hi I am having..."
    m = re.match(r"^([A-Z][a-z]+):\s", text)
    if m:
        return m.group(1)
    # Look for "for <Name>" or "I am <Name>" or "my name is <Name>"
    patterns = [
        r"\bfor\s+([A-Z][a-z]+)\b",
        r"\bI(?:'m| am)\s+([A-Z][a-z]+)\b",
        r"\bmy name is\s+([A-Z][a-z]+)\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    # First capitalised word that isn't a common English word
    common = {"Book", "Find", "Need", "Want", "Male", "Female", "The", "Please", "Help", "Hi", "Hello", "Hey"}
    for word in text.split():
        clean = re.sub(r"[^A-Za-z]", "", word)
        if clean and clean[0].isupper() and clean not in common and len(clean) > 2:
            return clean
    return None


def _resolve_patient(text: str) -> tuple[str, str]:
    """Return (patient_id, request_text).
    Priority: explicit patient_id= token > demo first name >
              specialty keyword fallback > rahul-001 default.
    Appends caller_name= token when the real caller isn't a demo persona.
    """
    for token in text.split():
        if token.startswith("patient_id="):
            pid = token.split("=", 1)[1]
            return pid, text.replace(token, "").strip()
    lower = text.lower()
    for name, pid in _PERSONA_MAP.items():
        if name in lower:
            return pid, text
    for keywords, pid in _SPECIALTY_FALLBACK:
        if any(kw in lower for kw in keywords):
            caller = _extract_caller_name(text)
            enriched = f"{text} caller_name={caller}" if caller else text
            return pid, enriched
    caller = _extract_caller_name(text)
    enriched = f"{text} caller_name={caller}" if caller else text
    return "rahul-001", enriched


def _format_reply(result: dict) -> str:
    if "error" in result:
        return f"Sorry, I couldn't complete the booking: {result['error']}"

    available = result.get("available")
    booking_status = str(available).lower() if available else "callback_needed"

    if booking_status == "booked":
        header = f"Appointment confirmed for {result.get('patient_name', 'your patient')}!"
    elif booking_status == "callback_needed":
        header = f"Availability gathered for {result.get('patient_name', 'your patient')} — call the clinic to confirm the slot."
    elif booking_status == "failed":
        header = f"Could not reach a clinic for {result.get('patient_name', 'your patient')}."
    else:
        header = f"Booking attempt complete for {result.get('patient_name', 'your patient')}."

    lines = [
        header,
        f"Clinic:    {result.get('clinic', 'N/A')}",
        f"Phone:     {result.get('phone', 'N/A')}",
        f"Language:  {result.get('language', 'English')}",
    ]
    if result.get("rationale"):
        rationale = result["rationale"]
        if rationale.startswith("```") or rationale.startswith("{"):
            rationale = "Best match based on availability and insurance"
        lines.append(f"Why:       {rationale}")
    if result.get("attempts"):
        lines.append(f"Attempts:  {result['attempts']}")
    call_summary = result.get("call_summary", "")
    if call_summary and not call_summary.startswith("{") and not call_summary.startswith("```"):
        lines.append(f"Call:      {call_summary}")
    reqs = result.get("requirements", {})
    if reqs.get("time_pref"):
        lines.append(f"Time pref: {reqs['time_pref']}")
    return "\n".join(lines)


@protocol.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    # Acknowledge immediately
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    text = " ".join(
        item.text for item in msg.content if isinstance(item, TextContent)
    ).strip()

    ctx.logger.info(f"[swarm-intake] received: {text[:120]}")

    patient_id, request_text = _resolve_patient(text)

    # Send a progress message before the 30-90s blocking swarm run
    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[TextContent(
                type="text",
                text=(
                    f"Dispatching HealthSwarm agents for patient {patient_id} "
                    "(profiler, finder, caller, matcher)... "
                    "This takes 30-90 seconds."
                ),
            )],
        ),
    )

    try:
        from pymongo import MongoClient
        from agents.swarm_intake import agent as intake_agent
        import concurrent.futures as _cf

        def _run_swarm():
            db = MongoClient(os.environ["MONGO_URI"]).get_default_database()
            return intake_agent.run(db, patient_id=patient_id, request_text=request_text)

        loop = asyncio.get_event_loop()
        with _cf.ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, _run_swarm)
        reply = _format_reply(result)
    except Exception as exc:
        ctx.logger.exception("swarm-intake error")
        reply = f"Error: {exc}"

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=reply),
                EndSessionContent(type="end-session"),
            ],
        ),
    )


@protocol.on_message(ChatAcknowledgement)
async def handle_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


agent.include(protocol, publish_manifest=True)


# ── OmegaClaw direct-call protocol ──────────────────────────────────────────
# OmegaClaw uses send_sync_message which returns on the first reply. The Chat
# Protocol handler above sends an ACK + progress message before the result,
# which would be captured instead. This separate request/response pair gives
# OmegaClaw a clean single round-trip with a long timeout.

class BookingRequest(Model):
    query: str

class BookingResponse(Model):
    result: str

@agent.on_message(BookingRequest, replies={BookingResponse})
async def handle_booking_request(ctx: Context, sender: str, msg: BookingRequest):
    patient_id, request_text = _resolve_patient(msg.query)
    ctx.logger.info(f"[swarm-intake] OmegaClaw booking: patient={patient_id}")
    try:
        from pymongo import MongoClient
        from agents.swarm_intake import agent as intake_agent
        import concurrent.futures as _cf

        def _run_swarm():
            db = MongoClient(os.environ["MONGO_URI"]).get_default_database()
            return intake_agent.run(db, patient_id=patient_id, request_text=request_text)

        loop = asyncio.get_event_loop()
        with _cf.ThreadPoolExecutor(max_workers=1) as pool:
            result = await loop.run_in_executor(pool, _run_swarm)
        reply = _format_reply(result)
    except Exception as exc:
        ctx.logger.exception("swarm-intake OmegaClaw booking error")
        reply = f"Error: {exc}"
    await ctx.send(sender, BookingResponse(result=reply))


# ── HTTP booking bridge ─────────────────────────────────────────────────────
# Docker containers reach this via http://host.docker.internal:$PORT/book.
# Two-phase flow:
#   Phase 1 (/book)   — gather availability, store pending state, ask patient to confirm
#   Phase 2 (/book)   — detect "confirm" in query, make booking call to winning clinic

import json as _json
import threading
import urllib.request as _urlreq
import urllib.parse as _urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """HTTP bridge that handles each request in its own thread so a long
    swarm run (30-150s) never blocks the next incoming message."""
    daemon_threads = True

# Pending bookings keyed by patient_id: store winner + fingerprint + requirements
_PENDING_BOOKINGS: dict = {}
_PENDING_LOCK = threading.Lock()

# Hardcoded clinics — only these two phone numbers will be called.
_HARDCODED_CLINICS = [
    {
        "name": "Kindred Hospital Paramount",
        "phone": "+1-213-272-3426",
        "specialty": "clinic",
        "address": "Los Angeles, CA",
        "raw_tags": {},
    },
    {
        "name": "Da Vita Nephron Medical Center",
        "phone": "+1-213-477-5422",
        "specialty": "clinic",
        "address": "Los Angeles, CA",
        "raw_tags": {},
    },
]

# Telegram chat_id cache (looked up via getUpdates on first call)
_TG_CHAT_ID: int | None = None
_TG_CHAT_LOCK = threading.Lock()


def _tg_token() -> str | None:
    return os.environ.get("TG_BOT_TOKEN")


def _resolve_chat_id() -> int | None:
    """Find the most recent Telegram chat_id by calling getUpdates."""
    global _TG_CHAT_ID
    with _TG_CHAT_LOCK:
        if _TG_CHAT_ID is not None:
            return _TG_CHAT_ID
        token = _tg_token()
        if not token:
            return None
        try:
            with _urlreq.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=5) as r:
                data = _json.loads(r.read())
            for upd in reversed(data.get("result", [])):
                msg = upd.get("message") or upd.get("edited_message") or {}
                cid = (msg.get("chat") or {}).get("id")
                if cid:
                    _TG_CHAT_ID = cid
                    return cid
        except Exception as e:
            print(f"[bridge] Telegram getUpdates failed: {e!r}")
        return None


def tg_push(text: str) -> None:
    """Push a status update to the active Telegram chat (best-effort)."""
    token = _tg_token()
    if not token:
        return
    cid = _resolve_chat_id()
    if not cid:
        return
    try:
        body = _urlparse.urlencode({"chat_id": cid, "text": text, "parse_mode": "Markdown"}).encode()
        _urlreq.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=5)
    except Exception as e:
        print(f"[bridge] tg_push failed: {e!r}")


# Confirmation requires an explicit short phrase — NOT just any query containing "book"
_CONFIRM_KEYWORDS = ("confirm", "yes book it", "book it", "go ahead and book", "proceed with booking", "yes confirm", "please book")


def _is_confirmation(text: str) -> bool:
    lower = text.lower().strip()
    # Single-word or very short confirmations
    if lower in ("confirm", "yes", "ok", "okay", "proceed", "go ahead", "book it", "do it"):
        return True
    return any(kw in lower for kw in _CONFIRM_KEYWORDS)


def _format_confirmation_prompt(result: dict) -> str:
    """Return a Telegram-friendly message asking the patient to confirm the booking."""
    name = result.get("patient_name", "the patient")
    clinic = result.get("clinic", "N/A")
    phone = result.get("phone", "N/A")
    summary = result.get("call_summary", "")
    key_facts = result.get("winner_key_facts", [])
    reqs = result.get("requirements", {})

    lines = [
        f"Availability found for {name}!",
        f"Clinic:  {clinic}",
        f"Phone:   {phone}",
    ]
    if summary:
        lines.append(f"Summary: {summary}")
    if key_facts:
        lines.append("Available slots:")
        for f in key_facts[:3]:
            lines.append(f"  • {f}")

    # Show the context that was passed to the ElevenLabs calling agent
    ctx_lines = []
    if result.get("specialty"):
        ctx_lines.append(f"  Specialty:  {result['specialty']}")
    if reqs.get("problem"):
        ctx_lines.append(f"  Problem:    {reqs['problem']}")
    if reqs.get("insurance"):
        ctx_lines.append(f"  Insurance:  {reqs['insurance']}")
    if reqs.get("language") and reqs["language"].lower() != "english":
        ctx_lines.append(f"  Language:   {reqs['language']}")
    if reqs.get("tests_needed") and reqs["tests_needed"].lower() != "none":
        ctx_lines.append(f"  Tests:      {reqs['tests_needed']}")
    if reqs.get("time_pref"):
        ctx_lines.append(f"  Time pref:  {reqs['time_pref']}")
    if ctx_lines:
        lines.append("")
        lines.append("Context sent to the clinic:")
        lines.extend(ctx_lines)

    # Show match scores for all clinics called
    all_scores = result.get("all_scores", [])
    if all_scores:
        lines.append("")
        lines.append("Clinic match scores:")
        for s in all_scores:
            marker = "★" if s.get("clinic") == result.get("clinic") else " "
            score = s.get("judge_score") or s.get("match_score", 0)
            avail = "✓" if s.get("available") else ("?" if s.get("available") is None else "✗")
            lines.append(f"  {marker} {s['clinic']}: {score}/100 {avail}")

    lines.append("")
    lines.append("Reply 'confirm' to book this appointment, or ask for a different clinic.")
    return "\n".join(lines)


def _format_booked_reply(result: dict) -> str:
    name = result.get("patient_name", "the patient")
    clinic = result.get("clinic", "N/A")
    phone = result.get("phone", "N/A")
    time_slot = result.get("time_slot", "")
    summary = result.get("call_summary", "")

    lines = [f"Appointment confirmed for {name}!"]
    if time_slot:
        lines.append(f"Slot:    {time_slot}")
    lines += [
        f"Clinic:  {clinic}",
        f"Phone:   {phone}",
    ]
    if summary:
        lines.append(f"Summary: {summary}")
    return "\n".join(lines)


class _BookingHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence access log
        pass

    def do_POST(self):
        if self.path != "/book":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            payload = _json.loads(body)
            query = payload.get("query", "")

            # ── /reset — flush all pending state ──────────────────────────────
            if query.strip().lower() in ("/reset", "reset"):
                with _PENDING_LOCK:
                    _PENDING_BOOKINGS.clear()
                global _TG_CHAT_ID
                with _TG_CHAT_LOCK:
                    _TG_CHAT_ID = None
                reply = "✅ State flushed. Send your booking request when ready."
                response = _json.dumps({"result": reply}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response)
                return

            patient_id, request_text = _resolve_patient(query)

            from pymongo import MongoClient
            from agents.swarm_intake import agent as intake_agent

            db = MongoClient(os.environ["MONGO_URI"]).get_default_database()

            # ── Phase 2: patient confirmed — make the booking call ────────────
            with _PENDING_LOCK:
                pending = _PENDING_BOOKINGS.get(patient_id)

            if _is_confirmation(query) and pending:
                with _PENDING_LOCK:
                    _PENDING_BOOKINGS.pop(patient_id, None)

                tg_push(f"📞 Calling *{pending['winner'].get('name')}* to confirm your slot...")
                result = intake_agent.confirm_booking(
                    db,
                    patient_id=patient_id,
                    winner=pending["winner"],
                    winner_fp=pending["winner_fp"],
                    requirements=pending["requirements"],
                )
                reply = _format_booked_reply(result) if not result.get("error") else _format_reply(result)

            else:
                # ── Phase 1: gather availability with hardcoded 2 clinics ─────
                tg_push(f"🚀 Dispatching HealthSwarm for: _{request_text[:120]}_")
                result = intake_agent.run(
                    db,
                    patient_id=patient_id,
                    request_text=request_text,
                    candidates_override=_HARDCODED_CLINICS,
                    progress_cb=tg_push,
                )

                if result.get("error"):
                    reply = _format_reply(result)
                else:
                    # Save pending state so Phase 2 can use it
                    # Include specialty from Phase 1 (_parse_specialty result) so
                    # confirm_booking uses the same specialty for the booking call.
                    winner_clinic = {
                        "name":      result.get("clinic"),
                        "phone":     result.get("phone"),
                        "language":  result.get("language"),
                        "specialty": result.get("specialty"),
                    }
                    winner_fp = {
                        "key_facts": result.get("winner_key_facts", []),
                        "summary": result.get("call_summary", ""),
                        "language": result.get("language"),
                        "available": result.get("available"),
                    }
                    with _PENDING_LOCK:
                        _PENDING_BOOKINGS[patient_id] = {
                            "winner": winner_clinic,
                            "winner_fp": winner_fp,
                            "requirements": result.get("requirements", {}),
                        }
                    reply = _format_confirmation_prompt(result)

            response = _json.dumps({"result": reply}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)
        except Exception as exc:
            err = _json.dumps({"error": str(exc)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(err)


def _start_bridge():
    port = int(os.getenv("OMEGACLAW_BRIDGE_PORT", "8015"))
    server = _ThreadingHTTPServer(("0.0.0.0", port), _BookingHandler)
    print(f"[bridge] Booking bridge listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=_start_bridge, daemon=True).start()
    agent.run()
