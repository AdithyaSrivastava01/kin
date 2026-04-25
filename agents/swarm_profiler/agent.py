# swarm_profiler — patient profiling agent
from common.telemetry import beacon


def run(db, patient_id: str) -> dict:
    """Load patient profile from MongoDB and emit a ProfileLoaded beacon.

    Returns a flat dict with the fields downstream agents need.
    Returns {} if the patient is not found.
    """
    p = db.patients.find_one({"patient_id": patient_id})
    if not p:
        beacon("swarm-profiler", "swarm-intake", "ProfileError", {
            "patient_id": patient_id,
            "reason": "not_found",
        })
        return {}

    profile = {
        "patient_id": patient_id,
        "name": p["name"],
        "language": p.get("primary_language", "English"),
        "insurance": p["insurance"]["provider"],
        "insurance_plan": p["insurance"].get("plan"),
        "location": p["location"],
        "allergies": p.get("allergies", []),
        "medications": [m["name"] for m in p.get("medications", [])],
        "diagnoses": p.get("diagnoses", []),
    }

    beacon("swarm-profiler", "swarm-intake", "ProfileLoaded", {
        "name": profile["name"],
        "language": profile["language"],
        "insurance": profile["insurance"],
        "allergies": profile["allergies"],
        "medications": profile["medications"],
    })

    return profile
