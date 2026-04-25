import os
import sys
import json
from datetime import datetime, timezone
from uuid import uuid4

import requests as http_requests
from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    TextContent,
    chat_protocol_spec,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from common.asi import asi_chat
from common.telemetry import beacon

load_dotenv()

GEMMA_VULTR_URL = os.getenv("GEMMA_VULTR_URL", "http://localhost:8088/translate")

agent = Agent(
    name="kin-translator",
    seed="kin-translator-seedphrase-CHANGE-ME-2",
    port=8002,
    mailbox=True,
    publish_agent_details=True,
)

protocol = Protocol(spec=chat_protocol_spec)

SYSTEM_PROMPT = (
    "You are a clinical interpreter. Translate the user's text into English. "
    "Preserve medical terms exactly. Do NOT interpret or modify dosages. "
    "If the text is already in English, return it unchanged."
)


def translate_audio(audio_url: str, target_lang: str = "en") -> str:
    """Send audio to the Vultr Gemma E4B endpoint for speech translation."""
    try:
        r = http_requests.post(
            GEMMA_VULTR_URL,
            json={"audio_url": audio_url, "target_lang": target_lang},
            timeout=20,
        )
        r.raise_for_status()
        return r.json().get("text", "[translation failed]")
    except Exception as e:
        return f"[audio translation error: {e}]"


def translate_text(text: str) -> str:
    """Translate text via ASI:One."""
    return asi_chat(SYSTEM_PROMPT, text)


@protocol.on_message(ChatMessage)
async def handle(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    raw = "".join(i.text for i in msg.content if isinstance(i, TextContent))
    ctx.logger.info(f"Received: {raw[:100]}...")

    beacon("kin-triage", "kin-translator", "Received", {"text": raw[:200]})

    # Parse structured task from kin-triage, or handle raw text
    try:
        task = json.loads(raw)
        params = task.get("params", {})
        audio_url = params.get("audio_url")
        text_to_translate = params.get("text", "")
        target_lang = params.get("target_lang", "en")
    except (json.JSONDecodeError, AttributeError):
        audio_url = None
        text_to_translate = raw
        target_lang = "en"

    # Route: audio via Vultr Gemma, text via ASI:One
    if audio_url:
        translated = translate_audio(audio_url, target_lang)
    elif text_to_translate:
        translated = translate_text(text_to_translate)
    else:
        translated = "[no content to translate]"

    beacon("kin-translator", "kin-triage", "Translation", {"translated": translated[:200]})

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=translated),
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
