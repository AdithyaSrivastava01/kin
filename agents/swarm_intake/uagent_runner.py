"""uAgent wrapper for swarm-intake (orchestrator).
Exposes the intake agent via ASI:One Chat Protocol so it can be
discovered and messaged through Agentverse / ASI:One.

Usage (from kin/):
  ../.venv/bin/python -m agents.swarm_intake.uagent_runner
"""
import json
import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import asyncio

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# Python 3.10+ no longer auto-creates an event loop; uagents needs one up-front
asyncio.set_event_loop(asyncio.new_event_loop())

from uagents import Agent, Context, Protocol
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

    try:
        from pymongo import MongoClient
        from agents.swarm_intake import agent as intake_agent

        db = MongoClient(os.environ["MONGO_URI"]).get_default_database()
        # Accept "patient_id=P001 ..." or fall back to demo patient
        patient_id = "P001"
        request_text = text
        for token in text.split():
            if token.startswith("patient_id="):
                patient_id = token.split("=", 1)[1]
                request_text = text.replace(token, "").strip()
                break

        result = intake_agent.run(db, patient_id=patient_id, request_text=request_text)
        reply = json.dumps(result, indent=2)
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

if __name__ == "__main__":
    agent.run()
