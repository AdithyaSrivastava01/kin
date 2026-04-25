"""Seed clinic_insurance — clinic ↔ insurance acceptance mappings.

Replaces the old insurance_map collection. `accepts` now references
insurance_companies.insurance_id (FK), not free-text plan names.

The clinic_name strings here are demo-curated (not auto-derived from
OSM). swarm-matcher should fall back gracefully if a candidate clinic
from OSM has no entry here.

    python scripts/seed_clinic_insurance.py
"""
from __future__ import annotations

import os
import sys

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MAPPINGS = [
    {"clinic_name": "Seoul Dermatology",    "accepts": ["aetna", "blue-shield", "cigna"]},
    {"clinic_name": "LA Skin Care Center",  "accepts": ["blue-shield", "cigna"]},
    {"clinic_name": "Koreatown Medical",    "accepts": ["aetna", "blue-shield", "kaiser"]},
    {"clinic_name": "Boyle Heights Clinic", "accepts": ["blue-shield", "medi-cal"]},
    {"clinic_name": "Artesia Heart Center", "accepts": ["cigna", "aetna", "blue-shield"]},
    # Real OSM-sourced clinic that swarm-finder regularly returns for Joon
    {"clinic_name": "Your Laser Skin Care", "accepts": ["aetna", "cigna", "blue-shield"]},
]


def seed():
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set", file=sys.stderr)
        return 1
    db = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)["healthswarm"]
    coll = db["clinic_insurance"]
    coll.create_index([("clinic_name", 1)], unique=True)
    coll.create_index([("accepts", 1)])

    for m in MAPPINGS:
        coll.replace_one({"clinic_name": m["clinic_name"]}, m, upsert=True)
    print(f"upserted {len(MAPPINGS)} clinic<->insurance mappings")
    return 0


if __name__ == "__main__":
    sys.exit(seed())
