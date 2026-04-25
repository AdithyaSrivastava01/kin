"""uAgent wrapper for swarm-fingerprint (call transcript summariser).

Usage (from kin/):
  ../.venv/bin/python -m agents.swarm_fingerprint.uagent_runner
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
    name="healthswarm-fingerprint",
    seed=os.environ["FINGERPRINT_SEED"],
    port=8014,
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

    ctx.logger.info(f"[swarm-fingerprint] received: {text[:120]}")

    try:
        from agents.swarm_fingerprint import agent as fp_agent

        # Expect JSON: {"clinic": {...}, "transcript": [...], "requirements": {...}}
        payload = json.loads(text)
        clinic = payload.get("clinic", {"name": "Unknown Clinic"})
        transcript = payload.get("transcript", [])
        requirements = payload.get("requirements", {})
        result = fp_agent.run(clinic, transcript, requirements)
        reply = json.dumps(result, indent=2)
    except json.JSONDecodeError:
        # Free-text demo: summarise the message itself as a mock transcript
        try:
            from agents.swarm_fingerprint import agent as fp_agent
            mock_transcript = [{"role": "receptionist", "text": text}]
            result = fp_agent.run(
                {"name": "Demo Clinic"},
                mock_transcript,
                {"specialty": "general"},
            )
            reply = json.dumps(result, indent=2)
        except Exception as exc:
            reply = f"Error: {exc}"
    except Exception as exc:
        ctx.logger.exception("swarm-fingerprint error")
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
