import os
import sys
import json
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import load_dotenv
from pymongo import MongoClient
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

# MongoDB — deterministic retrieval only, NO LLM in this agent
mongo = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = mongo["kin"]

agent = Agent(
    name="kin-vault",
    seed="kin-vault-seedphrase-CHANGE-ME-4",
    port=8004,
    mailbox=True,
    publish_agent_details=True,
)

protocol = Protocol(spec=chat_protocol_spec)


def lookup_patient(patient_id: str) -> dict | None:
    return db["patients"].find_one({"patient_id": patient_id}, {"_id": 0})


def lookup_medications(patient_id: str) -> list[dict]:
    return list(db["medications"].find({"patient_id": patient_id}, {"_id": 0}))


def lookup_hospital(name: str) -> dict | None:
    return db["hospitals"].find_one(
        {"name": {"$regex": name, "$options": "i"}}, {"_id": 0}
    )


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

    # Parse structured task or raw query
    try:
        task = json.loads(raw)
        params = task.get("params", {})
        query_type = params.get("type", task.get("action", "patient"))
        patient_id = params.get("patient_id", "")
        hospital_name = params.get("hospital_name", "")
    except (json.JSONDecodeError, AttributeError):
        query_type = "patient"
        patient_id = raw.strip()
        hospital_name = ""

    # DETERMINISTIC lookups — no LLM, no hallucination
    if "medication" in query_type.lower() or "med" in query_type.lower():
        results = lookup_medications(patient_id)
        if results:
            response = json.dumps(results, default=str, indent=2)
        else:
            response = f"No medications found for patient '{patient_id}'"
        beacon("kin-vault", "mongodb", "MedicationLookup", {"patient_id": patient_id, "count": len(results)})

    elif "hospital" in query_type.lower():
        result = lookup_hospital(hospital_name)
        if result:
            response = json.dumps(result, default=str, indent=2)
        else:
            response = f"No hospital found matching '{hospital_name}'"
        beacon("kin-vault", "mongodb", "HospitalLookup", {"hospital_name": hospital_name})

    else:
        # Default: patient record lookup
        record = lookup_patient(patient_id)
        if record:
            # Also fetch their medications
            meds = lookup_medications(patient_id)
            record["medications"] = meds
            response = json.dumps(record, default=str, indent=2)
        else:
            response = f"No patient record found for '{patient_id}'"
        beacon("kin-vault", "mongodb", "PatientLookup", {"patient_id": patient_id})

    beacon("kin-vault", "kin-triage", "Response", {"length": len(response)})

    await ctx.send(
        sender,
        ChatMessage(
            timestamp=datetime.now(timezone.utc),
            msg_id=uuid4(),
            content=[
                TextContent(type="text", text=response),
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
