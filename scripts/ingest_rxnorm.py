"""Verify and enrich patient medications against the NLM RxNorm API.

For each medication on each patient document, looks up the drug name
in https://rxnav.nlm.nih.gov/REST/rxcui.json and:
  - confirms the existing rxcui matches (or finds the canonical one)
  - fetches the FDA generic + brand names
  - writes back rxcui_verified + rxnorm_canonical_name + brand_names

Public API, no key required. Run after seed_patients.py.

    python scripts/ingest_rxnorm.py
"""
from __future__ import annotations

import os
import sys
import time

import certifi
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

RXNAV = "https://rxnav.nlm.nih.gov/REST"
HTTP = requests.Session()


def lookup_rxcui(name: str) -> str | None:
    """Find the RxCUI (RxNorm concept unique ID) for a drug name."""
    r = HTTP.get(
        f"{RXNAV}/rxcui.json",
        params={"name": name, "search": 2},  # 2 = approximate match if needed
        verify=certifi.where(),
        timeout=10,
    )
    r.raise_for_status()
    ids = r.json().get("idGroup", {}).get("rxnormId", [])
    return ids[0] if ids else None


def lookup_canonical_name(rxcui: str) -> str | None:
    """Get the canonical RxNorm name for an RxCUI."""
    r = HTTP.get(
        f"{RXNAV}/rxcui/{rxcui}/property.json",
        params={"propName": "RxNorm Name"},
        verify=certifi.where(),
        timeout=10,
    )
    r.raise_for_status()
    props = r.json().get("propConceptGroup", {}).get("propConcept", [])
    return props[0]["propValue"] if props else None


def lookup_brands(rxcui: str) -> list[str]:
    """Get brand-name equivalents for a generic RxCUI."""
    r = HTTP.get(
        f"{RXNAV}/rxcui/{rxcui}/related.json",
        params={"tty": "BN"},  # Brand Name
        verify=certifi.where(),
        timeout=10,
    )
    r.raise_for_status()
    groups = r.json().get("relatedGroup", {}).get("conceptGroup", [])
    out: list[str] = []
    for g in groups:
        for c in g.get("conceptProperties", []) or []:
            if c.get("name"):
                out.append(c["name"])
    # de-dup, keep first-seen order
    seen = set()
    return [b for b in out if not (b in seen or seen.add(b))]


def enrich():
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI is not set", file=sys.stderr)
        return 1

    db = MongoClient(uri, serverSelectionTimeoutMS=5_000)["healthswarm"]
    patients = db["patients"]

    total_meds = 0
    verified = 0
    mismatched = []

    for p in patients.find({}):
        meds = p.get("medications", [])
        if not meds:
            continue
        print(f"\n{p['name']} ({p['patient_id']}):")
        updated_meds = []
        for med in meds:
            total_meds += 1
            name = med["name"]
            expected = med.get("rxcui")
            found = lookup_rxcui(name)
            time.sleep(0.2)  # be polite to NLM

            if not found:
                print(f"  ✗ {name!r} — no rxcui found")
                med["rxcui_verified"] = False
                updated_meds.append(med)
                continue

            canonical = lookup_canonical_name(found)
            time.sleep(0.2)
            brands = lookup_brands(found)
            time.sleep(0.2)

            match = (expected == found)
            if match:
                verified += 1
                print(f"  ok {name}  rxcui={found}  brands={brands[:3] or ['(none)']}")
            else:
                mismatched.append((p["patient_id"], name, expected, found))
                print(f"  WARN {name}  expected rxcui={expected} got {found} ({canonical})")

            med["rxcui"] = found
            med["rxcui_verified"] = True
            med["rxnorm_canonical_name"] = canonical
            med["brand_names"] = brands[:5]  # cap to keep doc size reasonable
            updated_meds.append(med)

        patients.update_one(
            {"_id": p["_id"]},
            {"$set": {"medications": updated_meds}},
        )

    print(f"\n--- summary ---")
    print(f"  meds checked: {total_meds}")
    print(f"  verified:     {verified}")
    if mismatched:
        print(f"  mismatched:   {len(mismatched)}")
        for pid, n, exp, got in mismatched:
            print(f"    {pid:<12} {n:<40} expected={exp} got={got}")
    return 0


if __name__ == "__main__":
    sys.exit(enrich())
