"""ElevenLabs ClientTools wrappers around existing swarm agents.

Each function accepts a params dict (from the agent) and returns a
JSON-serializable result. These are registered on the Conversation
object so the ElevenLabs agent can call them mid-conversation.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from pymongo.database import Database

from agents.swarm_finder import agent as finder
from agents.swarm_matcher import agent as matcher
from agents.swarm_profiler import agent as profiler
from common.asi import asi_chat
from common.telemetry import beacon

# Shared registry of booking result futures — keyed by call ID.
# book_appointment writes here; report_booking resolves here.
_booking_futures: dict[str, asyncio.Future] = {}
_futures_lock = threading.Lock()


def _parse_specialty(request_text: str) -> str:
    """Use ASI:One to extract a specialty keyword from free text."""
    return (
        asi_chat(
            system=(
                "Extract the medical specialty from the patient request. "
                "Reply with a single lowercase word only — one of: "
                "dermatologist, cardiologist, clinic, dentist, ophthalmologist, orthopedic. "
                "If unclear, reply: clinic"
            ),
            user=request_text,
            max_tokens=10,
        )
        .strip()
        .lower()
    )


def make_lookup_patient(db: Database):
    """Return a ClientTools-compatible handler for patient lookup."""

    def lookup_patient(params: dict[str, Any]) -> dict[str, Any] | str:
        patient_id = params.get("patient_id", "")
        patient_name = params.get("patient_name", "")

        # Try by ID first, fall back to name search
        if patient_id:
            beacon(
                "swarm-intake",
                "swarm-profiler",
                "ChatMessage",
                {"patient_id": patient_id},
            )
            profile = profiler.run(db, patient_id)
        elif patient_name:
            beacon(
                "swarm-intake",
                "swarm-profiler",
                "ChatMessage",
                {"patient_name": patient_name},
            )
            doc = db.patients.find_one(
                {"name": {"$regex": patient_name, "$options": "i"}},
                {"patient_id": 1},
            )
            if doc:
                profile = profiler.run(db, doc["patient_id"])
            else:
                return f"No patient found with name '{patient_name}'."
        else:
            return "Please provide either patient_id or patient_name."

        if not profile:
            return f"Patient '{patient_id or patient_name}' not found."
        return profile

    return lookup_patient


def make_find_clinics(db: Database):
    """Return a ClientTools-compatible handler for clinic search + match."""

    def find_clinics(params: dict[str, Any]) -> dict[str, Any] | str:
        patient_id = params.get("patient_id", "")
        specialty_raw = params.get("specialty", "")

        # Resolve specialty
        specialty = _parse_specialty(specialty_raw) if specialty_raw else "clinic"

        # Need patient location + profile
        patient = db.patients.find_one({"patient_id": patient_id})
        if not patient:
            return f"Patient '{patient_id}' not found."

        profile = profiler.run(db, patient_id)

        # Find nearby clinics
        beacon(
            "swarm-intake",
            "swarm-finder",
            "ChatMessage",
            {
                "specialty": specialty,
                "radius_km": 15,
            },
        )
        candidates = finder.run(db, patient["location"], specialty)

        if not candidates:
            return {"ranked_clinics": [], "message": "No clinics found nearby."}

        # Rank them
        beacon(
            "swarm-intake",
            "swarm-matcher",
            "ChatMessage",
            {
                "candidates": [c["name"] for c in candidates[:3]],
                "insurance": profile.get("insurance"),
                "language": profile.get("language"),
            },
        )
        best = matcher.run(
            db,
            candidates,
            profile.get("insurance", ""),
            profile.get("language", "English"),
        )

        # Build ranked list (best first, then remaining)
        ranked = [best] if best else []
        for c in candidates:
            if c["name"] != (best or {}).get("name"):
                ranked.append(c)

        return {
            "ranked_clinics": ranked[:5],
            "specialty": specialty,
            "patient_context": {
                "patient_id": patient_id,
                "name": profile.get("name", ""),
                "language": profile.get("language", "English"),
                "insurance": profile.get("insurance", ""),
                "insurance_plan": profile.get("insurance_plan", ""),
                "specialty": specialty,
            },
        }

    return find_clinics


def make_book_appointment(db: Database):
    """Return a ClientTools-compatible handler that triggers outbound booking calls.

    This is async — it launches the booking agent and waits for
    report_booking to resolve the Future.
    """
    from voice_gateway.booking_agent import call_clinics_with_fallthrough

    def book_appointment(params: dict[str, Any]) -> dict[str, Any]:
        ranked_clinics = params.get("ranked_clinics", [])
        patient_context = params.get("patient_context", {})

        if not ranked_clinics:
            return {"status": "failed", "reason": "No clinics to call."}

        beacon(
            "swarm-intake",
            "swarm-caller",
            "ChatMessage",
            {
                "clinic": ranked_clinics[0].get("name"),
                "phone": ranked_clinics[0].get("phone"),
                "language": patient_context.get("language"),
            },
        )

        # Run the async fallthrough in a new event loop if needed
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an existing event loop — run in a thread
            result: dict = {}

            def _run():
                new_loop = asyncio.new_event_loop()
                result.update(
                    new_loop.run_until_complete(
                        call_clinics_with_fallthrough(ranked_clinics, patient_context)
                    )
                )
                new_loop.close()

            t = threading.Thread(target=_run, daemon=True)
            t.start()
            t.join(timeout=180)
            return result or {"status": "failed", "reason": "Booking timed out."}
        else:
            return asyncio.run(
                call_clinics_with_fallthrough(ranked_clinics, patient_context)
            )

    return book_appointment


def make_report_booking(call_id: str):
    """Return a ClientTools-compatible handler for the booking agent to report results.

    Resolves the Future that book_appointment is waiting on.
    """

    def report_booking(params: dict[str, Any]) -> str:
        status = params.get("status", "failed")
        result = {
            "status": status,
            "doctor_name": params.get("doctor_name"),
            "date": params.get("date"),
            "time": params.get("time"),
            "address": params.get("address"),
            "instructions": params.get("instructions"),
        }

        beacon(
            "swarm-caller",
            "clinic",
            "BookingResult",
            {
                "status": status,
                "doctor": result.get("doctor_name"),
                "date": result.get("date"),
                "time": result.get("time"),
            },
        )

        with _futures_lock:
            future = _booking_futures.pop(call_id, None)

        if future and not future.done():
            future.get_loop().call_soon_threadsafe(future.set_result, result)

        if status == "booked":
            return "Booking confirmed. You may now end the call politely."
        elif status == "callback_needed":
            return "Noted. Please end the call and we will follow up."
        else:
            return "Understood. You may end the call."

    return report_booking


def register_booking_future(call_id: str, future: asyncio.Future) -> None:
    """Store a Future so report_booking can resolve it."""
    with _futures_lock:
        _booking_futures[call_id] = future


def remove_booking_future(call_id: str) -> None:
    """Clean up a Future after timeout or completion."""
    with _futures_lock:
        _booking_futures.pop(call_id, None)
