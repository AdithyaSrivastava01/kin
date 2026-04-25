"""Read-only inspector for the HealthSwarm MongoDB (schema v2).

    python scripts/inspect_db.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


def main() -> int:
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set", file=sys.stderr)
        return 1

    db = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)["healthswarm"]

    # Patients (slim)
    print("=" * 70)
    print("PATIENTS (slim demographic)")
    print("=" * 70)
    for p in db.patients.find({}, {"_id": 0}):
        loc = p.get("location", {}).get("coordinates", [None, None])
        print(f"  {p['patient_id']:<14} {p['name']:<20} "
              f"{p['primary_language']:<10} "
              f"@ ({loc[1]:.4f}, {loc[0]:.4f})  "
              f"insurance={p.get('insurance_id')} {p.get('insurance_plan', '')}")

    # Insurance companies
    print()
    print("=" * 70)
    print("INSURANCE_COMPANIES")
    print("=" * 70)
    for ins in db.insurance_companies.find({}, {"_id": 0}).sort("insurance_id"):
        states = ",".join(ins.get("service_states", [])[:5])
        more = "…" if len(ins.get("service_states", [])) > 5 else ""
        print(f"  {ins['insurance_id']:<14} {ins['name']:<30} "
              f"plans={ins.get('plan_types')} states={states}{more}")

    # Clinic ↔ insurance acceptance
    print()
    print("=" * 70)
    print("CLINIC_INSURANCE")
    print("=" * 70)
    for row in db.clinic_insurance.find({}, {"_id": 0}).sort("clinic_name"):
        print(f"  {row['clinic_name']:<26} accepts={row['accepts']}")

    # Medical records — key fact: empty unless generated on demand
    print()
    print("=" * 70)
    print("MEDICAL_RECORDS (AI-generated on demand)")
    print("=" * 70)
    n = db.medical_records.count_documents({})
    if n == 0:
        print("  (empty — call common.medical.generate_medical_record(patient_id) "
              "or run profile_patient.py)")
    else:
        for rec in db.medical_records.find({}, {"_id": 0}).sort("generated_at", -1):
            meds = [m["name"] for m in rec.get("medications", [])]
            print(f"  {rec['patient_id']:<14} via={rec.get('generated_by')} "
                  f"meds={meds}  dx={rec.get('diagnoses')}")

    # Clinics counts
    print()
    print("=" * 70)
    print("CLINICS  (specialty × city, from OSM)")
    print("=" * 70)
    pipe = [
        {"$group": {
            "_id": {"city": "$city", "specialty": "$specialty"},
            "count": {"$sum": 1},
        }},
    ]
    counts: dict[str, Counter] = {}
    total = 0
    for row in db.clinics.aggregate(pipe):
        city = row["_id"]["city"]
        specialty = row["_id"]["specialty"]
        counts.setdefault(city, Counter())[specialty] = row["count"]
        total += row["count"]
    if not counts:
        print("  (empty — run scripts/ingest_clinics.py to repopulate)")
    else:
        cities = sorted(counts.keys())
        specialties = sorted({s for c in counts.values() for s in c})
        width = max(len(s) for s in specialties) + 2
        print(f"  {'specialty':<{width}}" + "".join(f"{c:>16}" for c in cities))
        print("  " + "-" * (width + 16 * len(cities)))
        for sp in specialties:
            row = f"  {sp:<{width}}" + "".join(
                f"{counts[c].get(sp, 0):>16}" for c in cities
            )
            print(row)
        print(f"\n  grand total: {total} clinics")

    # Live geo+insurance query — what swarm-finder will actually run
    print()
    print("=" * 70)
    print("LIVE QUERY  (swarm-finder for joon-001 with insurance filter)")
    print("=" * 70)
    joon = db.patients.find_one({"patient_id": "joon-001"})
    if joon:
        cands = list(db.clinics.find({
            "specialty": "dermatologist",
            "location": {"$near": {"$geometry": joon["location"], "$maxDistance": 15_000}},
        }).limit(8))
        accepted_names = {
            row["clinic_name"]
            for row in db.clinic_insurance.find({"accepts": joon["insurance_id"]})
        }
        print(f"  candidates near {joon['name']} (Koreatown), insurance={joon['insurance_id']}:")
        if not cands:
            print("    (no clinics — run scripts/ingest_clinics.py)")
        for c in cands:
            in_network = "✓" if c["name"] in accepted_names else " "
            addr = c.get("address") or "(no address)"
            print(f"    {in_network} {c['name']:<32} {addr[:46]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
