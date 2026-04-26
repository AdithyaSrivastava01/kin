"""OmegaClaw skill adapter for HealthSwarm.

Drop this file into OmegaClaw's agentverse/ directory alongside the existing
agentverse.py. OmegaClaw calls healthswarm_booking() via py-call from MeTTa.

Usage from skills.metta:
    (= (healthswarm-booking $query)
       (py-call (agentverse.healthswarm_skill $query)))
"""
import asyncio
import json

from uagents import Model
from uagents.query import send_sync_message

HEALTHSWARM_INTAKE_ADDRESS = (
    "agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu"
)


class BookingRequest(Model):
    query: str


class BookingResponse(Model):
    result: str


async def _ask_agent(destination: str, request: Model, timeout: int = 60) -> str:
    envelope_or_status = await send_sync_message(
        destination=destination,
        message=request,
        timeout=timeout,
    )
    return str(envelope_or_status)


def healthswarm_booking(query: str, timeout: int = 180) -> str:
    """Book a medical appointment via the HealthSwarm agent swarm.

    Sends a BookingRequest to healthswarm-intake and waits up to 3 minutes
    for the 5-agent swarm (profiler, finder, caller, fingerprint, matcher)
    to complete and return a formatted booking summary.

    Args:
        query: Natural-language booking request, e.g.
               "Book a dermatology appointment for Joon"
               "Maria needs a Spanish-speaking primary care doctor this week"
               "Rahul wants a cardiologist ASAP"
        timeout: Seconds to wait for the swarm to complete (default 180).

    Returns:
        Human-readable booking result string, or "error: ..." on failure.
    """
    try:
        request = BookingRequest(query=query)
        raw = asyncio.run(_ask_agent(HEALTHSWARM_INTAKE_ADDRESS, request, int(timeout)))
        # send_sync_message returns str(envelope). Try to parse the JSON body.
        try:
            data = json.loads(raw)
            return data.get("result", raw)
        except (json.JSONDecodeError, AttributeError, TypeError):
            return raw
    except Exception as e:
        return f"error: {e}"
