"""Booking agent — makes outbound calls to clinics via ElevenLabs Conversational AI.

Creates an ElevenLabs agent session per clinic call, registers the
report_booking tool, and waits for the agent to resolve the booking.
Handles fallthrough: tries ranked clinics in order until one succeeds.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from elevenlabs import ElevenLabs
from elevenlabs.conversational_ai.conversation import ClientTools, Conversation
from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface

from common.telemetry import beacon
from voice_gateway.agent_config import (
    BOOKING_AGENT_ID,
    BOOKING_CALL_TIMEOUT_S,
    MAX_FALLTHROUGH_ATTEMPTS,
    build_booking_prompt,
)
from voice_gateway.tools import (
    make_report_booking,
    register_booking_future,
    remove_booking_future,
)

_eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))


async def call_single_clinic(
    clinic: dict,
    patient_context: dict,
) -> dict:
    """Place one outbound call to a clinic and wait for the booking result.

    Returns {"status": "booked"|"failed"|"callback_needed"|"no_answer", ...}.
    """
    phone = clinic.get("phone", "")
    clinic_name = clinic.get("name", phone)
    call_id = uuid.uuid4().hex

    loop = asyncio.get_event_loop()
    result_future: asyncio.Future = loop.create_future()
    register_booking_future(call_id, result_future)

    beacon(
        "swarm-caller",
        "clinic",
        "CallStarted",
        {
            "clinic": clinic_name,
            "phone": phone,
            "patient": patient_context.get("name"),
            "language": patient_context.get("language", "English"),
            "call_id": call_id,
        },
    )

    # Register the report_booking tool for this specific call
    tools = ClientTools()
    tools.register("report_booking", make_report_booking(call_id), is_async=False)

    try:
        # Initiate outbound call via ElevenLabs Conversational AI
        # The agent_id must be pre-configured on ElevenLabs with the
        # booking system prompt. Dynamic patient context is passed
        # via conversation_config_override or first_message.
        prompt = build_booking_prompt(
            patient_name=patient_context.get("name", "a patient"),
            specialty=patient_context.get("specialty", "a doctor"),
            insurance=patient_context.get("insurance", "private"),
            time_pref=patient_context.get("time_pref", "this week"),
        )

        # Use the phone call API for outbound calling
        agent_id = BOOKING_AGENT_ID or os.getenv("BOOKING_AGENT_ID", "")

        def _run_call():
            """Run the outbound call in a blocking thread."""
            try:
                call = _eleven.conversational_ai.twilio.phone_call.create(
                    agent_id=agent_id,
                    agent_phone_number_id=os.getenv("ELEVENLABS_PHONE_NUMBER_ID", ""),
                    to_number=phone,
                    conversation_config_override={
                        "agent": {
                            "prompt": {"prompt": prompt},
                        },
                        "tts": {
                            "voice_id": os.getenv(
                                "BOOKING_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"
                            ),
                        },
                    },
                    client_tools=tools,
                )
                print(f"[booking] call initiated to {clinic_name}: {call}")
            except Exception as e:
                print(f"[booking] failed to initiate call to {clinic_name}: {e!r}")
                if not result_future.done():
                    loop.call_soon_threadsafe(
                        result_future.set_result,
                        {"status": "failed", "error": str(e)},
                    )

        # Run call initiation in thread (ElevenLabs SDK may block)
        await loop.run_in_executor(None, _run_call)

        # Wait for the booking agent to call report_booking
        result = await asyncio.wait_for(result_future, timeout=BOOKING_CALL_TIMEOUT_S)

    except asyncio.TimeoutError:
        print(f"[booking] timeout waiting for {clinic_name}")
        result = {"status": "no_answer"}
    except Exception as e:
        print(f"[booking] error calling {clinic_name}: {e!r}")
        result = {"status": "failed", "error": str(e)}
    finally:
        remove_booking_future(call_id)

    return result


async def call_clinics_with_fallthrough(
    ranked_clinics: list[dict],
    patient_context: dict,
) -> dict:
    """Try calling ranked clinics until one succeeds or attempts exhausted.

    Returns {"status": "booked"|"exhausted", "clinic": ..., "attempts": N, ...}.
    """
    attempts = min(len(ranked_clinics), MAX_FALLTHROUGH_ATTEMPTS)

    for i in range(attempts):
        clinic = ranked_clinics[i]
        clinic_name = clinic.get("name", clinic.get("phone", "unknown"))
        print(f"[fallthrough] attempt {i + 1}/{attempts}: {clinic_name}")

        result = await call_single_clinic(clinic, patient_context)

        beacon(
            "swarm-caller",
            "clinic",
            "CallAttempt",
            {
                "clinic": clinic_name,
                "attempt": i + 1,
                "outcome": result.get("status", "unknown"),
            },
        )

        if result.get("status") == "booked":
            return {
                "status": "booked",
                "clinic": clinic_name,
                "clinic_address": clinic.get("address"),
                "attempts": i + 1,
                **result,
            }

        print(f"[fallthrough] {clinic_name} -> {result.get('status')}, trying next")

    return {"status": "exhausted", "attempts": attempts}
