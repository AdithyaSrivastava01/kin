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


def _resolve_patient(text: str) -> tuple[str, str]:
    """Return (patient_id, request_text).
    Priority: explicit patient_id= token > demo first name > default P001.
    """
    for token in text.split():
        if token.startswith("patient_id="):
            pid = token.split("=", 1)[1]
            return pid, text.replace(token, "").strip()
    lower = text.lower()
    for name, pid in _PERSONA_MAP.items():
        if name in lower:
            return pid, text
    return "P001", text


def _format_reply(result: dict) -> str:
    if "error" in result:
        return f"Sorry, I couldn't complete the booking: {result['error']}"
    lines = [
        f"Booking complete for {result.get('patient_name', 'your patient')}!",
        f"Clinic:    {result.get('clinic', 'N/A')}",
        f"Phone:     {result.get('phone', 'N/A')}",
        f"Language:  {result.get('language', 'English')}",
    ]
    if result.get("rationale"):
        lines.append(f"Why:       {result['rationale']}")
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

        db = MongoClient(os.environ["MONGO_URI"]).get_default_database()
        result = intake_agent.run(db, patient_id=patient_id, request_text=request_text)
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

        db = MongoClient(os.environ["MONGO_URI"]).get_default_database()
        result = intake_agent.run(db, patient_id=patient_id, request_text=request_text)
        reply = _format_reply(result)
    except Exception as exc:
        ctx.logger.exception("swarm-intake OmegaClaw booking error")
        reply = f"Error: {exc}"
    await ctx.send(sender, BookingResponse(result=reply))


if __name__ == "__main__":
    agent.run()
