"""Seed demo patients + insurance map into MongoDB.

Idempotent — uses upsert keyed by patient_id and clinic_name.

Patient location is GeoJSON Point so swarm-finder can run
$near queries against clinics.location directly.
"""

import os
import sys

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
        "insurance": {"provider": "Blue Shield", "plan": "PPO"},
        "medications": [
            {"name": "Metformin 500 MG Oral Tablet", "rxcui": "860974", "dosage": "500mg 2x daily"},
            {"name": "Lisinopril 10 MG Oral Tablet", "rxcui": "314076", "dosage": "10mg 1x daily"},
        ],
        "allergies": ["Penicillin"],
        "diagnoses": ["Type 2 Diabetes", "Hypertension"],
        "last_visits": {
            "primary_care": "2025-11-15",
            "eye_exam":     "2025-02-20",
            "dental":       "2025-08-10",
        },
        "emergency_contact": {"name": "Carlos Gonzalez", "phone": "+1-213-555-0142"},
    },
    {
        "patient_id": "joon-001",
        "name": "Joon Kim",
        "age": 34,
        "primary_language": "Korean",
        # Koreatown, LA
        "location": {"type": "Point", "coordinates": [-118.3004, 34.0577]},
        "insurance": {"provider": "Aetna", "plan": "HMO"},
        "medications": [],
        "allergies": [],
        "diagnoses": ["Mild Eczema"],
        "last_visits": {
            "dermatology":  "2024-09-05",
            "primary_care": "2025-06-20",
        },
        "prior_providers": [
            {
                "doctor": "Dr. Park",
                "clinic": "Seoul Dermatology",
                "specialty": "dermatologist",
                "last_seen": "2024-09-05",
            },
        ],
        "emergency_contact": {"name": "Minji Kim", "phone": "+1-213-555-0198"},
    },
    {
        "patient_id": "rahul-001",
        "name": "Rahul Sharma",
        "age": 42,
        "primary_language": "Hindi",
        # Artesia, LA
        "location": {"type": "Point", "coordinates": [-118.0839, 33.8675]},
        "insurance": {"provider": "Cigna", "plan": "PPO"},
        "medications": [
            {"name": "Atorvastatin 20 MG Oral Tablet", "rxcui": "617311", "dosage": "20mg 1x daily"},
        ],
        "allergies": ["Sulfa drugs"],
        "diagnoses": ["Hyperlipidemia"],
        "family_history": ["Cardiac disease (father)", "Type 2 Diabetes (mother)"],
        "last_visits": {
            "cardiology":         "2025-08-14",
            "primary_care":       "2026-01-10",
            "cholesterol_panel":  "2025-08-14",
        },
        "emergency_contact": {"name": "Priya Sharma", "phone": "+1-562-555-0167"},
    },
]

INSURANCE_MAP = [
    {"clinic_name": "Seoul Dermatology",   "accepts": ["Aetna", "Blue Shield", "Cigna"]},
    {"clinic_name": "LA Skin Care Center", "accepts": ["Blue Shield", "Cigna"]},
    {"clinic_name": "Koreatown Medical",   "accepts": ["Aetna", "Blue Shield"]},
    {"clinic_name": "Boyle Heights Clinic","accepts": ["Blue Shield", "Medi-Cal"]},
    {"clinic_name": "Artesia Heart Center","accepts": ["Cigna", "Aetna", "Blue Shield"]},
]


def seed():
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI is not set (or still has placeholder). "
              "Add it to .env and re-run.", file=sys.stderr)
        sys.exit(1)

    db = MongoClient(uri, serverSelectionTimeoutMS=5_000)["healthswarm"]

    patients = db["patients"]
    patients.create_index([("patient_id", 1)], unique=True)
    patients.create_index([("location", "2dsphere")])
    for p in PATIENTS:
        patients.replace_one({"patient_id": p["patient_id"]}, p, upsert=True)
    print(f"upserted {len(PATIENTS)} patients")

    insurance = db["insurance_map"]
    insurance.create_index([("clinic_name", 1)], unique=True)
    for row in INSURANCE_MAP:
        insurance.replace_one({"clinic_name": row["clinic_name"]}, row, upsert=True)
    print(f"upserted {len(INSURANCE_MAP)} insurance mappings")


if __name__ == "__main__":
    seed()
