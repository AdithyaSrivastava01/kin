"""Seed slim patient demographics.

Schema v2 — patient docs hold demographics + insurance reference only.
Medical history lives in `medical_records` (AI-generated on demand).

    python scripts/seed_patients.py
"""

from __future__ import annotations

import os
import sys

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

PATIENTS = [
    {
        "patient_id": "maria-001",
        "name": "Maria Gonzalez",
        "age": 55,
        "primary_language": "Spanish",
        # Boyle Heights, LA
        "location": {"type": "Point", "coordinates": [-118.2283, 34.0335]},
        "insurance_id": "blue-shield",
        "insurance_plan": "PPO",
        "emergency_contact": {"name": "Carlos Gonzalez", "phone": "+1-213-555-0142"},
    },
    {
        "patient_id": "joon-001",
        "name": "Joon Kim",
        "age": 34,
        "primary_language": "Korean",
        # Koreatown, LA
        "location": {"type": "Point", "coordinates": [-118.3004, 34.0577]},
        "insurance_id": "aetna",
        "insurance_plan": "HMO",
        "emergency_contact": {"name": "Minji Kim", "phone": "+1-213-555-0198"},
    },
    {
        "patient_id": "rahul-001",
        "name": "Rahul Sharma",
        "age": 42,
        "primary_language": "Hindi",
        # Artesia, LA
        "location": {"type": "Point", "coordinates": [-118.0839, 33.8675]},
        "insurance_id": "cigna",
        "insurance_plan": "PPO",
        "emergency_contact": {"name": "Priya Sharma", "phone": "+1-562-555-0167"},
    },
]


def seed():
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set", file=sys.stderr)
        return 1
    db = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)[
        "healthswarm"
    ]
    patients = db["patients"]
    patients.create_index([("patient_id", 1)], unique=True)
    patients.create_index([("location", "2dsphere")])
    patients.create_index([("insurance_id", 1)])

    for p in PATIENTS:
        patients.replace_one({"patient_id": p["patient_id"]}, p, upsert=True)
    print(f"upserted {len(PATIENTS)} patients (slim demographic-only schema)")
    return 0


if __name__ == "__main__":
    sys.exit(seed())
