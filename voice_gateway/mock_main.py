"""Mock voice gateway for demo — no Twilio/ElevenLabs required.

Returns instant 'successful' call results for every clinic so the
swarm can complete end-to-end without real telephony.

Run: uvicorn voice_gateway.mock_main:app --host 0.0.0.0 --port 8000
"""
import uuid
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="HealthSwarm Mock Voice Gateway")

_CALLS: dict[str, dict] = {}


@app.post("/call")
async def place_call(request_data: dict):
    call_sid = f"mock-{uuid.uuid4().hex[:12]}"
    _CALLS[call_sid] = request_data
    return {"call_sid": call_sid, "status": "queued"}


@app.get("/transcript/{call_sid}")
async def get_transcript(call_sid: str):
    call = _CALLS.get(call_sid)
    if not call:
        return JSONResponse({"error": "not found"}, status_code=404)

    clinic_name = call.get("to", "the clinic")
    language = call.get("language", "English")
    patient_name = call.get("patient_name", "the patient")
    specialty = call.get("specialty", "general")
    insurance = call.get("insurance", {})
    insurance_provider = (
        insurance.get("provider", "their insurance") if isinstance(insurance, dict) else str(insurance)
    )

    transcript = [
        {"role": "receptionist", "text": f"Thank you for calling {clinic_name}. How can I help you?"},
        {"role": "assistant", "text": f"Hi, I'm calling to book a {specialty} appointment for {patient_name}."},
        {"role": "receptionist", "text": f"Of course! We accept {insurance_provider}. We have availability this week."},
        {"role": "assistant", "text": "What's the earliest available slot?"},
        {"role": "receptionist", "text": "We have tomorrow at 10 AM or Thursday at 2 PM. Which works?"},
        {"role": "assistant", "text": "Tomorrow at 10 AM works perfectly."},
        {"role": "receptionist", "text": f"Confirmed! I've booked {patient_name} for tomorrow at 10 AM. See you then!"},
    ]

    result = {
        "status": "booked",
        "confirmed": True,
        "appointment_time": "Tomorrow 10:00 AM",
        "insurance_accepted": True,
        "language_match": language,
    }

    return {"transcript": transcript, "result": result, "language_detected": language}


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "mock"}
