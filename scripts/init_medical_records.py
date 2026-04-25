"""Initialize the medical_records collection.

This collection is **deliberately empty** at seed time. Records are
populated on demand by common.medical.generate_medical_record(),
typically when swarm-profiler is queried for a patient.

We just create the collection with the right indexes so the first AI
write doesn't pay an index-build penalty.

    python scripts/init_medical_records.py
"""
from __future__ import annotations

import os
import sys

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


def init():
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set", file=sys.stderr)
        return 1
    db = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)["healthswarm"]
    coll = db["medical_records"]
    # patient_id is the natural key. Records are upserted on regenerate.
    coll.create_index([("patient_id", 1)], unique=True)
    coll.create_index([("generated_at", -1)])
    print(f"medical_records: {coll.count_documents({})} docs (empty by design)")
    return 0


if __name__ == "__main__":
    sys.exit(init())
