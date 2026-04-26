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


def _resolve_patient(text: str) -> tuple[str, str]:
    """Return (patient_id, request_text).
    Priority: explicit patient_id= token > demo first name >
              specialty keyword fallback > rahul-001 default.
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
            return pid, text
    return "rahul-001", text


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
from http.server import BaseHTTPRequestHandler, HTTPServer

# Pending bookings keyed by patient_id: store winner + fingerprint + requirements
_PENDING_BOOKINGS: dict = {}
_PENDING_LOCK = threading.Lock()

_CONFIRM_KEYWORDS = ("confirm", "yes book", "book it", "book the", "go ahead", "proceed")


def _is_confirmation(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _CONFIRM_KEYWORDS)


def _format_confirmation_prompt(result: dict) -> str:
    """Return a Telegram-friendly message asking the patient to confirm the booking."""
    name = result.get("patient_name", "the patient")
    clinic = result.get("clinic", "N/A")
    phone = result.get("phone", "N/A")
    summary = result.get("call_summary", "")
    key_facts = result.get("winner_key_facts", [])

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

                result = intake_agent.confirm_booking(
                    db,
                    patient_id=patient_id,
                    winner=pending["winner"],
                    winner_fp=pending["winner_fp"],
                    requirements=pending["requirements"],
                )
                reply = _format_booked_reply(result) if not result.get("error") else _format_reply(result)

            else:
                # ── Phase 1: gather availability ──────────────────────────────
                result = intake_agent.run(
                    db, patient_id=patient_id, request_text=request_text
                )

                if result.get("error"):
                    reply = _format_reply(result)
                else:
                    # Save pending state so Phase 2 can use it
                    winner_clinic = {
                        "name": result.get("clinic"),
                        "phone": result.get("phone"),
                        "language": result.get("language"),
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
    server = HTTPServer(("0.0.0.0", port), _BookingHandler)
    print(f"[bridge] Booking bridge listening on :{port}")
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=_start_bridge, daemon=True).start()
    agent.run()
