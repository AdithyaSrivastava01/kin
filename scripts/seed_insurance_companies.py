"""Seed the insurance_companies reference collection.

Five real US insurers with publicly-known phone/website. The remaining
fields (plan_types, service_states, prior_auth_specialties, copay) are
representative — accurate enough for a demo, not authoritative.

    python scripts/seed_insurance_companies.py
"""
from __future__ import annotations

import os
import sys

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

INSURERS = [
    {
        "insurance_id":           "aetna",
        "name":                   "Aetna",
        "phone":                  "+1-800-872-3862",
        "website":                "https://www.aetna.com",
        "plan_types":             ["HMO", "PPO", "EPO", "POS"],
        "service_states":         ["CA", "NY", "TX", "FL", "IL", "PA", "GA", "OH", "NC", "NJ"],
        "prior_auth_specialties": ["dermatologist", "cardiologist", "neurologist"],
        "avg_copay_usd":          25,
        "formulary_url":          "https://www.aetna.com/individuals-families/find-a-medication.html",
    },
    {
        "insurance_id":           "blue-shield",
        "name":                   "Blue Shield of California",
        "phone":                  "+1-800-393-6130",
        "website":                "https://www.blueshieldca.com",
        "plan_types":             ["HMO", "PPO", "EPO"],
        "service_states":         ["CA"],
        "prior_auth_specialties": ["cardiologist", "oncologist"],
        "avg_copay_usd":          30,
        "formulary_url":          "https://www.blueshieldca.com/bsca/bsc/public/member/mp/contentpages/!ut/p/z0/drug-search",
    },
    {
        "insurance_id":           "cigna",
        "name":                   "Cigna Healthcare",
        "phone":                  "+1-800-244-6224",
        "website":                "https://www.cigna.com",
        "plan_types":             ["HMO", "PPO", "EPO", "HDHP"],
        "service_states":         ["CA", "AZ", "CO", "TX", "FL", "IL", "NY", "NC", "TN", "GA"],
        "prior_auth_specialties": ["dermatologist", "endocrinologist"],
        "avg_copay_usd":          20,
        "formulary_url":          "https://www.cigna.com/individuals-families/member-resources/prescription/drug-list",
    },
    {
        "insurance_id":           "kaiser",
        "name":                   "Kaiser Permanente",
        "phone":                  "+1-800-464-4000",
        "website":                "https://healthy.kaiserpermanente.org",
        "plan_types":             ["HMO"],
        "service_states":         ["CA", "CO", "GA", "HI", "MD", "OR", "VA", "WA", "DC"],
        "prior_auth_specialties": [],  # Kaiser is integrated, fewer external prior-auths
        "avg_copay_usd":          15,
        "formulary_url":          "https://healthy.kaiserpermanente.org/health-wellness/drug-formulary",
    },
    {
        "insurance_id":           "medi-cal",
        "name":                   "Medi-Cal",
        "phone":                  "+1-800-541-5555",
        "website":                "https://www.dhcs.ca.gov/services/medi-cal",
        "plan_types":             ["Medicaid"],
        "service_states":         ["CA"],
        "prior_auth_specialties": ["dermatologist", "cardiologist", "psychiatrist"],
        "avg_copay_usd":          0,
        "formulary_url":          "https://medi-calrx.dhcs.ca.gov/provider/pharmacy/contract-drugs-list/",
    },
]


def seed():
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI not set", file=sys.stderr)
        return 1
    db = MongoClient(uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)["healthswarm"]
    coll = db["insurance_companies"]
    coll.create_index([("insurance_id", 1)], unique=True)
    coll.create_index([("service_states", 1)])

    for ins in INSURERS:
        coll.replace_one({"insurance_id": ins["insurance_id"]}, ins, upsert=True)
    print(f"upserted {len(INSURERS)} insurance companies")
    return 0


if __name__ == "__main__":
    sys.exit(seed())
