"""uAgent wrapper for swarm-finder (geospatial clinic search).

Usage (from kin/):
  ../.venv/bin/python -m agents.swarm_finder.uagent_runner
"""
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import asyncio

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

asyncio.set_event_loop(asyncio.new_event_loop())

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

agent = Agent(
    name="healthswarm-finder",
    seed=os.environ["FINDER_SEED"],
    port=8012,
    mailbox=True,
    publish_agent_details=True,
)

protocol = Protocol(spec=chat_protocol_spec)


@protocol.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
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

    ctx.logger.info(f"[swarm-finder] received: {text[:120]}")

    try:
        from pymongo import MongoClient
        from agents.swarm_finder import agent as finder_agent

        db = MongoClient(os.environ["MONGO_URI"]).get_default_database()

        # Parse "patient_id=P001 specialty=dermatologist" or free text
        patient_id = "P001"
        specialty = "clinic"
        for token in text.split():
            if token.startswith("patient_id="):
                patient_id = token.split("=", 1)[1]
            elif token.startswith("specialty="):
                specialty = token.split("=", 1)[1]

        p = db.patients.find_one({"patient_id": patient_id}, {"location": 1})
        if not p:
            reply = f"Patient {patient_id!r} not found"
        else:
            candidates = finder_agent.run(db, p["location"], specialty)
            reply = json.dumps(candidates, indent=2)
    except Exception as exc:
        ctx.logger.exception("swarm-finder error")
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
