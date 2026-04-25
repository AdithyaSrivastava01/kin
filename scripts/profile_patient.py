"""CLI wrapper for on-the-go medical-record generation.

Calls common.medical.generate_medical_record() and prints the result.
Useful for previewing what swarm-profiler will see.

    python scripts/profile_patient.py joon-001
    python scripts/profile_patient.py joon-001 --force      # regenerate
    python scripts/profile_patient.py --all                  # all patients
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

# Make `common` importable when running this script directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.medical import generate_medical_record  # noqa: E402

load_dotenv()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patient_id", nargs="?", help="patient_id (e.g. joon-001)")
    ap.add_argument("--all", action="store_true", help="generate for every patient")
    ap.add_argument("--force", action="store_true", help="regenerate even if cached")
    args = ap.parse_args()

    if not args.patient_id and not args.all:
        ap.error("provide a patient_id or --all")

    db = MongoClient(
        os.getenv("MONGO_URI"),
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=8000,
    )["healthswarm"]

    targets = (
        [p["patient_id"] for p in db["patients"].find({}, {"patient_id": 1})]
        if args.all
        else [args.patient_id]
    )

    for pid in targets:
        print(f"\n=== {pid} ===")
        rec = generate_medical_record(pid, force=args.force)
        print(f"  generated_by:  {rec['generated_by']}")
        print(f"  generated_at:  {rec['generated_at']}")
        print(f"  ai_notes:      {rec.get('ai_notes', '')[:120]}")
        print(f"  medications:   {[m['name'] for m in rec.get('medications', [])]}")
        print(f"  diagnoses:     {rec.get('diagnoses', [])}")
        print(f"  allergies:     {rec.get('allergies', [])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
