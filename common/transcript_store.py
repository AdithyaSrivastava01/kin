"""MongoDB persistence for call transcripts + fingerprints.

Schema (single collection: `fingerprints`):
  _id              ObjectId (auto)
  patient_id       str | None
  patient_name     str | None
  clinic_name      str | None
  call_sid         str | None — Twilio call SID, lets dashboard query by SID
  conversation_id  str | None — ElevenLabs conversation_id
  language         str | None
  available        bool | None
  insurance_accepted bool | None
  wait_time        str | None
  key_facts        list[str]
  summary          str | None
  transcript       list[{role, text}] — original transcript from voice gateway
  transcript_en    str | None — English-translated transcript from swarm-fingerprint
  raw              dict — full fingerprint dict as produced by swarm-fingerprint
  created_at       datetime UTC

Indexed by (patient_id, created_at desc) and call_sid for the
dashboard's three query endpoints.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

import certifi
from bson import ObjectId
from pymongo import DESCENDING, MongoClient

_db_singleton = None
_db_lock = threading.Lock()
_COLLECTION = os.getenv("FINGERPRINT_COLLECTION", "fingerprints")


def _db():
    """Lazy-init MongoDB handle. Creates indexes once."""
    global _db_singleton
    with _db_lock:
        if _db_singleton is None:
            uri = os.getenv("MONGO_URI")
            if not uri:
                raise RuntimeError("MONGO_URI not set")
            client = MongoClient(
                uri,
                tlsCAFile=certifi.where(),
                serverSelectionTimeoutMS=8000,
            )
            db = client.get_default_database()
            db[_COLLECTION].create_index(
                [("patient_id", 1), ("created_at", DESCENDING)]
            )
            db[_COLLECTION].create_index([("call_sid", 1)])
            _db_singleton = db
    return _db_singleton


def _to_jsonable(doc: dict) -> dict:
    """Stringify ObjectId + datetime so the dashboard's JSON serializer is happy."""
    if not doc:
        return doc
    out = dict(doc)
    if "_id" in out:
        out["fingerprint_id"] = str(out.pop("_id"))
    if isinstance(out.get("created_at"), datetime):
        out["created_at"] = out["created_at"].isoformat()
    return out


def save_fingerprint(
    fp: dict,
    patient_id: str | None = None,
    patient_name: str | None = None,
    call_sid: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Persist a fingerprint dict to Mongo. Returns the inserted fingerprint_id."""
    doc = {
        "patient_id": patient_id,
        "patient_name": patient_name,
        "clinic_name": fp.get("clinic_name") or (fp.get("clinic") or {}).get("name"),
        "call_sid": call_sid,
        "conversation_id": conversation_id,
        "language": fp.get("language"),
        "available": fp.get("available"),
        "insurance_accepted": fp.get("insurance_accepted"),
        "wait_time": fp.get("wait_time"),
        "key_facts": fp.get("key_facts") or [],
        "summary": fp.get("summary"),
        "transcript": fp.get("transcript") or [],
        "transcript_en": fp.get("transcript_en"),
        "raw": fp,
        "created_at": datetime.now(timezone.utc),
    }
    result = _db()[_COLLECTION].insert_one(doc)
    return str(result.inserted_id)


def get_fingerprint(fingerprint_id: str) -> dict | None:
    """Fetch one fingerprint by its inserted_id (hex string)."""
    try:
        oid = ObjectId(fingerprint_id)
    except Exception:
        return None
    doc = _db()[_COLLECTION].find_one({"_id": oid})
    return _to_jsonable(doc) if doc else None


def get_fingerprints_by_patient(patient_id: str, limit: int = 50) -> list[dict]:
    """All fingerprints for a patient, newest first."""
    cursor = (
        _db()[_COLLECTION]
        .find({"patient_id": patient_id})
        .sort("created_at", DESCENDING)
        .limit(max(1, min(limit, 200)))
    )
    return [_to_jsonable(d) for d in cursor]


def get_transcript(call_sid: str) -> dict | None:
    """Fetch the fingerprint doc by Twilio call SID. Returns the same shape
    the voice gateway used to expose so the dashboard's /transcript/{sid}
    endpoint keeps working without changes.
    """
    doc = _db()[_COLLECTION].find_one({"call_sid": call_sid})
    return _to_jsonable(doc) if doc else None
