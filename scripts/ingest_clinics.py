"""Ingest healthcare facilities from OSM Overpass into MongoDB.

Run after MONGO_URI is set in .env. Idempotent — re-running replaces
clinics for each (city, specialty) pair.

Schema per document:
    {
      city, specialty, osm_id, osm_type, name, phone, address,
      website, opening_hours,
      location: { type: "Point", coordinates: [lon, lat] },
      raw_tags: {...},
    }

Geo queries use the 2dsphere index, so swarm-finder can do
$near / $geoWithin on `location`.
"""
from __future__ import annotations

import os
import sys
import time

import certifi
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import BulkWriteError

load_dotenv()

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# (south, west, north, east)
BBOXES = {
    "los_angeles": (33.70, -118.67, 34.34, -118.15),
    "mexico_city": (19.26, -99.30, 19.59, -98.96),
}

# Overpass selectors. Specialist categories filter doctors by speciality
# regex so dermatologist != cardiologist != generic doctor.
SELECTORS = {
    "dentist":       "[amenity=dentist]",
    "optometrist":   "[healthcare=optometrist]",
    "hospital":      "[amenity=hospital]",
    "clinic":        "[amenity=clinic]",
    "pharmacy":      "[amenity=pharmacy]",
    "dermatologist": '[healthcare=doctor]["healthcare:speciality"~"dermatolog|skin",i]',
    "cardiologist":  '[healthcare=doctor]["healthcare:speciality"~"cardiolog|heart",i]',
}


def _build_query(selector: str, bbox: tuple) -> str:
    s, w, n, e = bbox
    return f"""
    [out:json][timeout:25];
    (
      node{selector}({s},{w},{n},{e});
      way{selector}({s},{w},{n},{e});
      relation{selector}({s},{w},{n},{e});
    );
    out center tags;
    """


def _post_overpass(query: str) -> list[dict]:
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(
                url,
                data=query.encode("utf-8"),
                headers={
                    "Content-Type": "text/plain",
                    "User-Agent": "healthswarm/0.1 (LA Hacks 2026)",
                },
                verify=certifi.where(),
                timeout=60,
            )
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as e:
            last_err = e
            print(f"  overpass {url} failed: {e!r} — trying next mirror")
            time.sleep(2)
    raise RuntimeError(f"all overpass endpoints failed: {last_err!r}")


def _to_doc(el: dict, city: str, specialty: str) -> dict | None:
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lon is None:
        return None

    tags = el.get("tags", {})
    name = tags.get("name") or tags.get("operator")
    phone = tags.get("phone") or tags.get("contact:phone")

    # Skip facilities with neither name nor phone — useless for booking
    if not name and not phone:
        return None

    address = ", ".join(
        v for v in (
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:city"),
        ) if v
    ) or tags.get("addr:full")

    return {
        "city": city,
        "specialty": specialty,
        "osm_id": el["id"],
        "osm_type": el["type"],
        "name": name or "Unnamed",
        "phone": phone,
        "address": address,
        "website": tags.get("website") or tags.get("contact:website"),
        "opening_hours": tags.get("opening_hours"),
        "location": {"type": "Point", "coordinates": [lon, lat]},
        "raw_tags": tags,
    }


def ingest():
    uri = os.getenv("MONGO_URI")
    if not uri or "<" in uri:
        print("ERROR: MONGO_URI is not set (or still has placeholder). "
              "Add it to .env and re-run.", file=sys.stderr)
        sys.exit(1)

    db = MongoClient(uri, serverSelectionTimeoutMS=5_000)["healthswarm"]
    clinics = db["clinics"]

    # 2dsphere supports $near / $geoWithin on GeoJSON points
    clinics.create_index([("location", "2dsphere")])
    clinics.create_index([("city", 1), ("specialty", 1)])
    clinics.create_index([("osm_type", 1), ("osm_id", 1)], unique=True)

    total = 0
    for city, bbox in BBOXES.items():
        for specialty, selector in SELECTORS.items():
            print(f"[{city}/{specialty}] querying overpass...")
            try:
                elements = _post_overpass(_build_query(selector, bbox))
            except Exception as e:
                print(f"  giving up on {city}/{specialty}: {e!r}")
                continue

            docs = [d for d in (_to_doc(e, city, specialty) for e in elements) if d]
            if not docs:
                print(f"  0 clinics — skipping")
                continue

            clinics.delete_many({"city": city, "specialty": specialty})
            try:
                clinics.insert_many(docs, ordered=False)
            except BulkWriteError as bwe:
                # Duplicate (osm_type, osm_id) across categories is fine —
                # ordered=False inserts the rest.
                inserted = bwe.details.get("nInserted", 0)
                print(f"  inserted {inserted}/{len(docs)} (some duplicates skipped)")
                total += inserted
                continue

            total += len(docs)
            print(f"  {len(docs)} clinics inserted")
            time.sleep(1)  # be polite to overpass

    print(f"\ndone — {total} clinics across {len(BBOXES)} cities, "
          f"{len(SELECTORS)} specialties")


if __name__ == "__main__":
    ingest()
