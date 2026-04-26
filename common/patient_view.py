"""Patient-view adapter — assemble a flat v1-style profile from v2 storage.

Storage is normalized across `patients`, `insurance_companies`, and
`medical_records`. Most agent code wants a single flat dict with
`name`, `language`, `insurance`, `allergies`, `medications`, etc.

This adapter does that join in one place so individual agents don't
need to know about the v2 collection layout. swarm-profiler is the
primary caller; any other agent that needs patient-level data should
also go through here rather than reading collections directly.

Returned shape (superset of v1; extra fields are ignored by v1 callers):

    {
      patient_id, name, age, language,                    # demographic
      insurance, insurance_id, insurance_plan, insurer,   # insurance (insurer = full doc)
      location,                                           # GeoJSON Point
      allergies, medications, diagnoses,                  # flat lists
      ai_notes, generated_by, model_version,              # AI provenance
    }

Returns {} if the patient isn't found (caller decides how to react).
"""
from __future__ import annotations

from common.medical import generate_medical_record


def get_patient_view(db, patient_id: str) -> dict:
    p = db.patients.find_one({"patient_id": patient_id})
    if not p:
        return {}

    legacy_insurance = p.get("insurance") or {}
    insurance_id = p.get("insurance_id")
    if not insurance_id and legacy_insurance.get("provider"):
        insurance_id = legacy_insurance["provider"].lower().replace(" ", "-")
    insurer = db.insurance_companies.find_one({"insurance_id": insurance_id}) or {}

    # Get-or-generate the AI medical record. Cached after first call.
    try:
        med = generate_medical_record(patient_id)
    except Exception:
        med = {}

    return {
        "patient_id":     patient_id,
        "name":           p["name"],
        "age":            p.get("age"),
        "language":       p.get("primary_language", "English"),
        "insurance_id":   insurance_id,
        "insurance":      insurer.get("name") or legacy_insurance.get("provider") or insurance_id,
        "insurance_plan": p.get("insurance_plan") or legacy_insurance.get("plan"),
        "insurer":        insurer,                                # full doc for callers that want copay, states, prior_auth
        "location":       p["location"],
        "allergies":      med.get("allergies") or p.get("allergies", []),
        "medications":    [m["name"] if isinstance(m, dict) else m for m in (med.get("medications") or p.get("medications", []))],
        "diagnoses":      med.get("diagnoses") or p.get("diagnoses", []),
        "prior_providers": med.get("prior_providers") or p.get("prior_providers", []),
        "ai_notes":       (med.get("ai_notes") or "")[:200],
        "generated_by":   med.get("generated_by"),
        "model_version":  med.get("model_version"),
    }
