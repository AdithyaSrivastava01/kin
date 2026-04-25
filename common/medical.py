"""On-demand AI-generated medical records.

Called when swarm-profiler is queried for a patient and no record yet
exists. Strict JSON schema in the system prompt so the response is
machine-parseable. Falls back to a deterministic stub if ASI:One is
unreachable, so the demo never blocks.

Usage from another module:

    from common.medical import generate_medical_record
    record = generate_medical_record("joon-001")        # cached
    record = generate_medical_record("joon-001", force=True)   # regenerate
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MODEL_VERSION = "asi1-2026-q1"

SYSTEM_PROMPT = """\
You generate realistic but synthetic medical history for a fictional patient
in a demo healthcare app. NEVER recommend real treatments or claim accuracy.

Return ONLY a single valid JSON object, no prose, no markdown fences.
The JSON must conform exactly to this shape:

{
  "ai_notes": "<2-3 sentence clinical summary>",
  "medications": [
    {
      "name": "<full RxNorm-style name e.g. 'Metformin 500 MG Oral Tablet'>",
      "rxcui": "<best-guess RxCUI as a string of digits, or null>",
      "dosage": "<plain English dosing>",
      "rxcui_verified": false,
      "brand_names": []
    }
  ],
  "allergies": ["<single drug or allergen>"],
  "diagnoses": ["<short diagnosis label>"],
  "last_visits": {
    "<visit-type-key e.g. dermatology|primary_care|cardiology>": "<YYYY-MM-DD>"
  },
  "family_history": ["<short string>"],
  "prior_providers": [
    {
      "doctor": "<Dr. Surname>",
      "clinic": "<Clinic Name>",
      "specialty": "<dermatologist|cardiologist|...>",
      "last_seen": "<YYYY-MM-DD>"
    }
  ]
}

Constraints:
- Match the patient's age/language/insurance hints provided in the user message
- Light histories for young patients, more substantial for older patients
- 0-3 medications, 0-2 allergies, 0-3 diagnoses, 0-2 prior providers
- Dates within the last 3 years from today
- Do not invent contact info or treatment plans
"""


def _stub_record(patient: dict) -> dict:
    """Deterministic fallback when ASI:One is unavailable."""
    age = patient.get("age", 30)
    if age < 40:
        meds, dx, allergies = [], ["Mild Eczema"], []
    elif age < 60:
        meds = [{
            "name":           "Metformin 500 MG Oral Tablet",
            "rxcui":          "861007",
            "dosage":         "500mg twice daily with meals",
            "rxcui_verified": False,
            "brand_names":    [],
        }]
        dx = ["Type 2 Diabetes"]
        allergies = ["Penicillin"]
    else:
        meds = [{
            "name":           "Atorvastatin 20 MG Oral Tablet",
            "rxcui":          "617310",
            "dosage":         "20mg once daily at bedtime",
            "rxcui_verified": False,
            "brand_names":    [],
        }]
        dx = ["Hyperlipidemia", "Hypertension"]
        allergies = ["Sulfa drugs"]

    return {
        "ai_notes": (f"{patient.get('name', 'Patient')} is {age}, "
                     f"{patient.get('primary_language', 'English')}-speaking. "
                     "Stub record generated without LLM access."),
        "medications": meds,
        "allergies": allergies,
        "diagnoses": dx,
        "last_visits": {"primary_care": "2025-08-10"},
        "family_history": [],
        "prior_providers": [],
    }


def _ask_asi1(patient: dict) -> dict | None:
    """Call ASI:One. Returns the parsed record dict or None on any failure."""
    api_key = os.getenv("ASI_ONE_API_KEY")
    if not api_key:
        return None

    try:
        # Lazy import — keeps openai/requests optional for environments
        # that only need the stub fallback.
        from openai import OpenAI
        client = OpenAI(base_url="https://api.asi1.ai/v1", api_key=api_key)
        user_msg = (
            f"Generate a synthetic medical history for:\n"
            f"  name: {patient.get('name')}\n"
            f"  age: {patient.get('age')}\n"
            f"  primary_language: {patient.get('primary_language')}\n"
            f"  insurance: {patient.get('insurance_id')} ({patient.get('insurance_plan')})\n"
        )
        r = client.chat.completions.create(
            model="asi1",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=900,
            temperature=0.4,
        )
        raw = r.choices[0].message.content or ""
    except Exception as e:
        print(f"  [medical] ASI:One call failed: {e!r}")
        return None

    # Strip markdown fences if the model couldn't help itself
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Last-ditch: pull the outermost {...}
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        print(f"  [medical] could not parse ASI:One response as JSON")
        return None


def generate_medical_record(patient_id: str, *, force: bool = False) -> dict[str, Any]:
    """Get-or-generate the medical record for a patient.

    - If a record exists and force=False, returns the cached doc.
    - Otherwise calls ASI:One; on failure falls back to a deterministic stub.
    - Writes the result to the medical_records collection (upsert).
    """
    db = MongoClient(
        os.getenv("MONGO_URI"),
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=8000,
    )["healthswarm"]

    if not force:
        existing = db["medical_records"].find_one({"patient_id": patient_id})
        if existing:
            return existing

    patient = db["patients"].find_one({"patient_id": patient_id})
    if not patient:
        raise ValueError(f"patient {patient_id!r} not found in patients collection")

    body = _ask_asi1(patient)
    generated_by = "asi1"
    if body is None:
        body = _stub_record(patient)
        generated_by = "stub"

    record = {
        "patient_id":    patient_id,
        "generated_by":  generated_by,
        "generated_at":  datetime.now(timezone.utc),
        "model_version": MODEL_VERSION if generated_by == "asi1" else "stub-v1",
        **body,
    }
    db["medical_records"].replace_one(
        {"patient_id": patient_id}, record, upsert=True
    )
    return record


if __name__ == "__main__":
    import sys
    pid = sys.argv[1] if len(sys.argv) > 1 else "joon-001"
    rec = generate_medical_record(pid, force=True)
    print(json.dumps(rec, default=str, indent=2))
