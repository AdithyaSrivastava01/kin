import os
import sys
import json
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from openai import OpenAI
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from common.telemetry import beacon

load_dotenv()

client = OpenAI(
    base_url="https://api.asi1.ai/v1",
    api_key=os.getenv("ASI_ONE_API_KEY"),
)

# Downstream agent addresses — paste from each agent's startup log
AGENT_ADDRESSES = {
    "kin-translator": os.getenv("KIN_TRANSLATOR_ADDR", ""),
    "kin-doctor": os.getenv("KIN_DOCTOR_ADDR", ""),
    "kin-vault": os.getenv("KIN_VAULT_ADDR", ""),
    "kin-logistics": os.getenv("KIN_LOGISTICS_ADDR", ""),
}

agent = Agent(
    name="kin-triage",
    seed="kin-triage-seedphrase-CHANGE-ME-1",
    port=8001,
    mailbox=True,
    publish_agent_details=True,
)

protocol = Protocol(spec=chat_protocol_spec)

SYSTEM_PROMPT = """\
You are kin-triage, the orchestrator of the Kin family-crisis coordination system.

Given a user's free-text emergency description (e.g. "my dad collapsed in Mumbai"),
respond with TWO parts separated by ---:

PART 1: One calming sentence for the user.

PART 2: A JSON object with this schema:
{
  "tasks": [
    {
      "agent": "kin-translator" | "kin-doctor" | "kin-vault" | "kin-logistics",
      "action": "short description of what to do",
      "params": { ... relevant parameters ... }
    }
  ]
}

Rules:
- Use kin-translator when there's a language barrier or foreign-language text/audio.
- Use kin-doctor when the user needs hospital lookup or medical facility contact.
- Use kin-vault when you need to retrieve patient records or medication info.
- Use kin-logistics when the user needs flights or travel ETAs.
- You may invoke multiple agents. Order them by urgency.
- Do NOT invent medical advice. You are a coordinator, not a doctor.
"""


async def dispatch_to_agents(ctx: Context, plan_json: str, sender: str):
    """Parse the triage plan and forward sub-tasks to downstream agents."""
    try:
        tasks = json.loads(plan_json).get("tasks", [])
    except (json.JSONDecodeError, AttributeError):
        return

    for task in tasks:
        agent_name = task.get("agent", "")
        addr = AGENT_ADDRESSES.get(agent_name, "")
        if not addr:
            ctx.logger.warning(f"No address configured for {agent_name}, skipping")
            continue

        payload_text = json.dumps({
            "action": task.get("action", ""),
            "params": task.get("params", {}),
        })

        beacon("kin-triage", agent_name, "ChatMessage", task)

        await ctx.send(
            addr,
            ChatMessage(
                timestamp=datetime.now(timezone.utc),
                msg_id=uuid4(),
                content=[TextContent(type="text", text=payload_text)],
            ),
        )
        ctx.logger.info(f"Dispatched to {agent_name}")


@protocol.on_message(ChatMessage)
async def handle_message(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    text = "".join(
        item.text for item in msg.content if isinstance(item, TextContent)
    )
    ctx.logger.info(f"Received: {text[:100]}...")

    beacon("user", "kin-triage", "ChatMessage", {"text": text[:200]})

    # Ask ASI:One for a triage plan
    try:
        r = client.chat.completions.create(
            model="asi1",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=2048,
        )
        response = r.choices[0].message.content
    except Exception:
        ctx.logger.exception("ASI:One call failed")
        response = "I am here. Give me one moment to coordinate."

    # Try to extract and dispatch the JSON plan
    if "---" in response:
        parts = response.split("---", 1)
        user_reply = parts[0].strip()
        plan_section = parts[1].strip()

        # Extract JSON from the plan section
        json_start = plan_section.find("{")
        json_end = plan_section.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            await dispatch_to_agents(ctx, plan_section[json_start:json_end], sender)
    else:
        user_reply = response

    beacon("kin-triage", "user", "Response", {"text": user_reply[:200]})

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=user_reply),
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
