"""uAgent wrapper for swarm-matcher (LLM clinic ranking judge).

Usage (from kin/):
  ../.venv/bin/python -m agents.swarm_matcher.uagent_runner
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
    name="healthswarm-matcher",
    seed=os.environ["MATCHER_SEED"],
    port=8013,
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

    ctx.logger.info(f"[swarm-matcher] received: {text[:120]}")

    try:
        from agents.swarm_matcher import agent as matcher_agent

        # Expect JSON: {"requirements": {...}, "fingerprints": [...]}
        payload = json.loads(text)
        requirements = payload.get("requirements", {})
        fingerprints = payload.get("fingerprints", [])
        result = matcher_agent.run(requirements, fingerprints)
        reply = json.dumps(result, indent=2)
    except json.JSONDecodeError:
        # Free-text demo: treat entire message as a mock requirement
        try:
            from agents.swarm_matcher import agent as matcher_agent
            mock_fp = [{"clinic_name": "Demo Clinic", "available": True,
                        "insurance_accepted": True, "wait_time": "1 week",
                        "key_facts": [], "summary": "Demo clinic for testing",
                        "clinic": {"name": "Demo Clinic", "phone": "+1-555-0100"}}]
            result = matcher_agent.run({"specialty": text}, mock_fp)
            reply = json.dumps(result, indent=2)
        except Exception as exc:
            reply = f"Error: {exc}"
    except Exception as exc:
        ctx.logger.exception("swarm-matcher error")
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
