"""One-shot migration to schema v2.

Drops the v1 collections (whatever survived a manual wipe) and
recreates everything in v2 layout. Idempotent — safe to re-run.

    python scripts/migrate_v2.py

Steps:
  1. drop:  patients, insurance_map, medical_records, clinic_insurance, insurance_companies
            (clinics is preserved — re-run scripts/ingest_clinics.py separately if empty)
  2. seed:  insurance_companies   (reference data)
  3. seed:  patients               (slim demographic)
  4. seed:  clinic_insurance       (FK references)
  5. init:  medical_records        (empty, indexes only — populated on demand)
"""
from __future__ import annotations

import os
import subprocess
import sys

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

DROP = [
    "patients",
    "insurance_map",        # v1 name
    "medical_records",
    "clinic_insurance",
    "insurance_companies",
]

SEED_SCRIPTS = [
    "seed_insurance_companies.py",
    "seed_patients.py",
    "seed_clinic_insurance.py",
    "init_medical_records.py",
]


def run_step(label: str, fn) -> bool:
    print(f"\n--- {label} ---")
    try:
        return fn() == 0
    except SystemExit as e:
        return (e.code or 0) == 0
    except Exception as e:
        print(f"  ERROR: {e!r}")
        return False


def drop_old_collections() -> int:
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set", file=sys.stderr)
        return 1
    db = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)["healthswarm"]

    existing = set(db.list_collection_names())
    for name in DROP:
        if name in existing:
            db[name].drop()
            print(f"  dropped {name}")
        else:
            print(f"  (skip) {name} not present")

    if "clinics" in existing:
        n = db["clinics"].count_documents({})
        print(f"  preserved clinics ({n} docs)")
    else:
        print("  WARN: clinics collection empty/missing — re-run ingest_clinics.py to repopulate")
    return 0


def run_seed(script_filename: str) -> int:
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script_filename)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, script_path],
        cwd=os.path.dirname(os.path.dirname(script_path)),
        env=env,
    )
    return r.returncode


def main():
    if not run_step("DROP v1 collections", drop_old_collections):
        return 1
    for script in SEED_SCRIPTS:
        if not run_step(f"RUN {script}", lambda s=script: run_seed(s)):
            print(f"\n!! migration aborted at {script}")
            return 1

    print("\n=== migration complete ===")
    print("  next: python scripts/inspect_db.py    (view schema state)")
    print("  next: python scripts/profile_patient.py joon-001    (generate medical record)")
    print("  if clinics is empty: python scripts/ingest_clinics.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
