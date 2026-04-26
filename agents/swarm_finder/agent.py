# swarm_finder — clinic/hospital finder agent
import os
from common.telemetry import beacon
from common.geo import eta_from_geojson

FINDER_RADIUS_M = int(os.getenv("FINDER_RADIUS_M", "15000"))
FINDER_LIMIT    = int(os.getenv("FINDER_LIMIT", "5"))


def run(db, patient_location: dict, specialty: str, radius_m: int = FINDER_RADIUS_M) -> list[dict]:
    """Find nearby clinics matching the requested specialty via MongoDB 2dsphere $near.

    Returns a list of up to FINDER_LIMIT clinic dicts, each enriched with a driving ETA.
    Emits a CandidatesFound beacon with the top results.
    """
    cursor = db.clinics.find({
        "specialty": specialty,
        "location": {"$near": {
            "$geometry": patient_location,
            "$maxDistance": radius_m,
        }},
    }).limit(FINDER_LIMIT)

    candidates = []
    for c in cursor:
        eta = eta_from_geojson(patient_location, c["location"])
        candidates.append({
            "name": c["name"],
            "address": c.get("address"),
            "phone": c.get("phone"),
            "specialty": c.get("specialty", specialty),
            "opening_hours": c.get("opening_hours"),
            "raw_tags": c.get("raw_tags", {}),
            "location": c["location"],
            "distance_m": eta["distance_m"],
            "eta_s": eta["duration_s"],
        })

    beacon("swarm-finder", "swarm-intake", "CandidatesFound", {
        "specialty": specialty,
        "count": len(candidates),
        "top": [c["name"] for c in candidates[:3]],
    })

    return candidates
