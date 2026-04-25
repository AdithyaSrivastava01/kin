# swarm_profiler — patient profiling agent
#
# Reads via the patient-view adapter so this agent stays decoupled from
# the v2 collection layout. Adapter joins patients + insurance_companies
# + medical_records into a single flat dict.
from common.patient_view import get_patient_view
from common.telemetry import beacon


def run(db, patient_id: str) -> dict:
    """Load patient profile via the adapter, emit a ProfileLoaded beacon.

    Returns the flat profile dict. Returns {} (and emits a ProfileError beacon)
    if the patient is not found.
    """
    profile = get_patient_view(db, patient_id)
    if not profile:
        beacon("swarm-profiler", "swarm-intake", "ProfileError", {
            "patient_id": patient_id,
            "reason": "not_found",
        })
        return {}

    beacon("swarm-profiler", "swarm-intake", "ProfileLoaded", {
        "name":         profile["name"],
        "language":     profile["language"],
        "insurance":    profile["insurance"],
        "insurance_id": profile["insurance_id"],
        "allergies":    profile["allergies"],
        "medications":  profile["medications"],
        "diagnoses":    profile["diagnoses"],
        "generated_by": profile["generated_by"],
    })

    return profile
