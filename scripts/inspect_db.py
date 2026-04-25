"""Quick read-only inspector for the HealthSwarm MongoDB.

Run any time to confirm the data layer is healthy and see what
swarm-finder will be searching against.

    python scripts/inspect_db.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


def main() -> int:
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set in .env", file=sys.stderr)
        return 1

    db = MongoClient(uri, serverSelectionTimeoutMS=5_000)["healthswarm"]

    # Patients
    print("=" * 60)
    print("PATIENTS")
    print("=" * 60)
    for p in db.patients.find({}, {"_id": 0}):
        loc = p.get("location", {}).get("coordinates", [None, None])
        ins = p.get("insurance", {})
        print(f"  {p['patient_id']:<14} {p['name']:<20} "
              f"{p['primary_language']:<10} "
              f"@ ({loc[1]:.4f}, {loc[0]:.4f})  "
              f"{ins.get('provider', '?')} {ins.get('plan', '')}")

    # Clinics summary
    print()
    print("=" * 60)
    print("CLINICS  (specialty × city)")
    print("=" * 60)
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

    cities = sorted(counts.keys())
    specialties = sorted({s for c in counts.values() for s in c})
    width = max(len(s) for s in specialties) + 2
    header = f"  {'specialty':<{width}}" + "".join(f"{c:>16}" for c in cities)
    print(header)
    print("  " + "-" * (width + 16 * len(cities)))
    for sp in specialties:
        row = f"  {sp:<{width}}" + "".join(
            f"{counts[c].get(sp, 0):>16}" for c in cities
        )
        print(row)
    print("  " + "-" * (width + 16 * len(cities)))
    print(f"  {'TOTAL':<{width}}" + "".join(
        f"{sum(counts[c].values()):>16}" for c in cities
    ))
    print(f"\n  grand total: {total} clinics")

    # Insurance map
    print()
    print("=" * 60)
    print("INSURANCE  (clinic → accepted plans)")
    print("=" * 60)
    for row in db.insurance_map.find({}, {"_id": 0}).sort("clinic_name"):
        print(f"  {row['clinic_name']:<26} {', '.join(row['accepts'])}")

    # Live geo-query sanity check
    print()
    print("=" * 60)
    print("LIVE GEO QUERY  (what swarm-finder will run for Joon)")
    print("=" * 60)
    joon = db.patients.find_one({"patient_id": "joon-001"})
    if joon:
        near = list(db.clinics.find({
            "specialty": "dermatologist",
            "location": {"$near": {
                "$geometry": joon["location"],
                "$maxDistance": 10_000,
            }},
        }).limit(5))
        print(f"  dermatologists within 10 km of {joon['name']} "
              f"({joon['primary_language']}):")
        if not near:
            print("    (none) — fall back to broader 'doctor' or 'clinic'")
        for c in near:
            addr = c.get("address") or "(no address)"
            print(f"    • {c['name']:<32} {addr}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
