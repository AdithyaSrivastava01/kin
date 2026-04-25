# swarm_finder — clinic/hospital finder agent (Engineer 1)
from common.telemetry import beacon
from common.geo import eta_from_geojson


def run(db, patient_location: dict, specialty: str, radius_m: int = 15_000) -> list[dict]:
    """Find nearby clinics matching the requested specialty via MongoDB 2dsphere $near.

    Returns a list of up to 5 clinic dicts, each enriched with a driving ETA.
    Emits a CandidatesFound beacon with the top results.
    """
    cursor = db.clinics.find({
        "specialty": specialty,
        "location": {"$near": {
            "$geometry": patient_location,
            "$maxDistance": radius_m,
        }},
    }).limit(5)

    candidates = []
    for c in cursor:
        eta = eta_from_geojson(patient_location, c["location"])
        candidates.append({
            "name": c["name"],
            "address": c.get("address"),
            "phone": c.get("phone"),
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
