"""HealthSwarm dashboard relay — fan-out SSE bus + patient-document uploads on :3001.

POST /telemetry         — agents emit beacons here. Body: {src, dst, kind, payload}.
                          Tagged with received_at, appended to ring buffer,
                          pushed to every SSE subscriber.
GET  /stream            — Next.js dashboard subscribes as an EventSource.
                          Replays history on connect, then streams live.
GET  /health            — sanity check + counts.

GET  /patients          — list of patients (id, name, language, insurance) for UI dropdowns
POST /upload            — multipart: patient_id + file. Stores in GridFS,
                          writes metadata to patient_documents, emits a
                          DocumentUploaded beacon so the dashboard reacts.
GET  /documents/{pid}   — list documents for a patient (metadata only)
GET  /document/{doc_id} — stream the binary back

Designed to never block the producer:
- /telemetry POST returns immediately even if a subscriber's queue is full.
- common.telemetry.beacon sets a 0.5s timeout, so the relay being down
  does not affect agents.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import certifi
from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from gridfs import GridFS
from pymongo import MongoClient

load_dotenv()

app = FastAPI(title="HealthSwarm Dashboard Relay")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HISTORY_CAP = 1000
SUBSCRIBER_QUEUE_CAP = 500
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

events: deque[dict[str, Any]] = deque(maxlen=HISTORY_CAP)
subscribers: list[asyncio.Queue] = []


# ── lazy Mongo handles (don't connect at import time) ─────────────────

_db = None
_fs = None


def _mongo():
    """Return (db, gridfs) lazily, ensuring indexes once."""
    global _db, _fs
    if _db is None:
        client = MongoClient(
            os.getenv("MONGO_URI"),
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=8000,
        )
        _db = client["healthswarm"]
        _fs = GridFS(_db)
        _db["patient_documents"].create_index([("patient_id", 1), ("uploaded_at", -1)])
        _db["outreach_attempts"].create_index([("outreach_id", 1)], unique=True)
        _db["outreach_attempts"].create_index([("started_at", -1)])
        _db["outreach_attempts"].create_index([("patient_id", 1), ("started_at", -1)])
    return _db, _fs


def _broadcast(evt: dict):
    """Push a beacon-shaped event to all SSE subscribers + history."""
    events.append(evt)
    for q in subscribers:
        try:
            q.put_nowait(evt)
        except asyncio.QueueFull:
            pass
    # Persist to outreach_attempts if this beacon belongs to an outreach
    try:
        _correlate_outreach(evt)
    except Exception as e:
        print(f"[outreach] correlation failed (non-fatal): {e!r}")


def _summarize(doc: dict) -> str:
    """Build a one-line human summary from whatever fields we have."""
    parts = []
    if doc.get("clinic_name"):
        parts.append(f"Reached {doc['clinic_name']}")
    if doc.get("language_detected"):
        match = "" if doc.get("language_match") in (None, True) else " (mismatch)"
        parts.append(f"{doc['language_detected']}-speaking{match}")
    outcome = doc.get("outcome")
    if outcome == "booked":
        when = doc.get("booking_when") or "appointment"
        parts.append(f"booked {when}")
    elif outcome == "no_answer":
        parts.append("no answer")
    elif outcome == "language_mismatch":
        parts.append("could not communicate")
    elif outcome == "failed":
        parts.append("call failed")
    elif outcome == "in_progress":
        parts.append("call in progress")
    elif not outcome:
        parts.append("dispatched")
    return " · ".join(parts) if parts else "(no details)"


def _correlate_outreach(evt: dict):
    """Map relevant beacons into the outreach_attempts collection.

    Beacons MUST carry payload.outreach_id for correlation. Beacons
    without it are silently skipped (non-outreach telemetry).
    """
    payload = evt.get("payload") or {}
    oid = payload.get("outreach_id")
    if not oid:
        return

    db, _ = _mongo()
    coll = db["outreach_attempts"]
    kind = evt.get("kind")
    received_at = evt.get("received_at")

    # Always append the raw beacon as a mini-transcript entry
    base_update = {
        "$push": {"events": {"kind": kind, "at": received_at, "payload": payload}}
    }

    if kind == "AppointmentRequest":
        # First touch — create the row.
        # NOTE: don't init "events": [] here; $push below will create
        # the array. Setting + pushing the same path conflicts in Mongo.
        coll.update_one(
            {"outreach_id": oid},
            {
                "$setOnInsert": {
                    "patient_id": payload.get("patient_id"),
                    "patient_name": payload.get("patient_name"),
                    "language_request": payload.get("language"),
                    "specialty": payload.get("specialty"),
                    "started_at": (
                        datetime.fromisoformat(received_at.replace("Z", "+00:00"))
                        if received_at
                        else datetime.now(timezone.utc)
                    ),
                    "outcome": "in_progress",
                },
                **base_update,
            },
            upsert=True,
        )
        return

    if kind == "CandidatesFound":
        coll.update_one(
            {"outreach_id": oid},
            {
                "$set": {"candidates_count": payload.get("count")},
                **base_update,
            },
            upsert=True,
        )
        return

    if kind == "ClinicMatched":
        coll.update_one(
            {"outreach_id": oid},
            {
                "$set": {
                    "clinic_name": payload.get("clinic"),
                    "clinic_address": payload.get("address"),
                    "clinic_phone": payload.get("phone"),
                },
                **base_update,
            },
            upsert=True,
        )
        return

    if kind == "CallStarted":
        coll.update_one(
            {"outreach_id": oid},
            {
                "$set": {"call_sid": payload.get("call_sid")},
                **base_update,
            },
            upsert=True,
        )
        return

    if kind == "LanguageDetected":
        detected = payload.get("language")
        attempt = coll.find_one({"outreach_id": oid}, {"language_request": 1})
        match = (attempt or {}).get("language_request") == detected
        coll.update_one(
            {"outreach_id": oid},
            {
                "$set": {
                    "language_detected": detected,
                    "language_match": match,
                    "language_latency_ms": payload.get("latency_ms"),
                },
                **base_update,
            },
            upsert=True,
        )
        return

    if kind == "BookingResult":
        outcome = payload.get("outcome") or "in_progress"
        update = {
            "$set": {
                "outcome": outcome,
                "ended_at": (
                    datetime.fromisoformat(received_at.replace("Z", "+00:00"))
                    if received_at
                    else datetime.now(timezone.utc)
                ),
                "booking_when": payload.get("when"),
                "booking_notes": payload.get("notes"),
            },
            **base_update,
        }
        coll.update_one({"outreach_id": oid}, update, upsert=True)

        # Recompute the AI summary from the current state
        latest = coll.find_one({"outreach_id": oid})
        if latest:
            coll.update_one(
                {"outreach_id": oid},
                {"$set": {"ai_summary": _summarize(latest)}},
            )


# ── existing telemetry bus ────────────────────────────────────────────


@app.post("/telemetry")
async def telemetry(req: Request):
    body = await req.json()
    evt = {
        "src": body.get("src"),
        "dst": body.get("dst"),
        "kind": body.get("kind"),
        "payload": body.get("payload", {}),
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    _broadcast(evt)
    return {"ok": True, "subscribers": len(subscribers)}


@app.get("/stream")
async def stream(req: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_CAP)
    subscribers.append(queue)

    async def generate():
        try:
            for evt in list(events):
                yield f"data: {json.dumps(evt)}\n\n"
            while True:
                if await req.is_disconnected():
                    break
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(evt)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if queue in subscribers:
                subscribers.remove(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
def health():
    return {
        "ok": True,
        "buffered_events": len(events),
        "subscribers": len(subscribers),
    }


# ── patient roster (for UI dropdowns) ─────────────────────────────────


@app.get("/patients")
def list_patients():
    db, _ = _mongo()
    return [
        {
            "patient_id": p["patient_id"],
            "name": p["name"],
            "primary_language": p.get("primary_language"),
            "insurance_id": p.get("insurance_id"),
        }
        for p in db.patients.find(
            {},
            {
                "_id": 0,
                "patient_id": 1,
                "name": 1,
                "primary_language": 1,
                "insurance_id": 1,
            },
        ).sort("patient_id")
    ]


# ── document uploads ─────────────────────────────────────────────────


@app.post("/upload")
async def upload(
    patient_id: str = Form(...),
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
):
    db, fs = _mongo()

    # Validate patient exists
    patient = db.patients.find_one({"patient_id": patient_id}, {"_id": 0, "name": 1})
    if not patient:
        raise HTTPException(status_code=404, detail=f"patient {patient_id!r} not found")

    # Read body with size cap (don't trust client-side limits)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file too large ({len(data)} bytes; max {MAX_UPLOAD_BYTES})",
        )
    if not data:
        raise HTTPException(status_code=400, detail="empty upload")

    # Store binary in GridFS, metadata in patient_documents
    gridfs_id = fs.put(
        data,
        filename=file.filename,
        contentType=file.content_type or "application/octet-stream",
        patient_id=patient_id,
    )

    meta = {
        "patient_id": patient_id,
        "filename": file.filename,
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes": len(data),
        "description": description,
        "uploaded_at": datetime.now(timezone.utc),
        "gridfs_id": gridfs_id,
    }
    result = db.patient_documents.insert_one(meta)
    doc_id = str(result.inserted_id)

    # Beacon so the war-room dashboard shows the upload in real time
    _broadcast(
        {
            "src": "patient",
            "dst": "swarm-profiler",
            "kind": "DocumentUploaded",
            "payload": {
                "patient_id": patient_id,
                "patient_name": patient["name"],
                "filename": file.filename,
                "size_bytes": len(data),
                "content_type": file.content_type,
                "doc_id": doc_id,
            },
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    return {
        "ok": True,
        "doc_id": doc_id,
        "filename": file.filename,
        "size_bytes": len(data),
    }


@app.get("/documents/{patient_id}")
def list_documents(patient_id: str):
    db, _ = _mongo()
    out = []
    for d in db.patient_documents.find({"patient_id": patient_id}).sort(
        "uploaded_at", -1
    ):
        out.append(
            {
                "doc_id": str(d["_id"]),
                "filename": d["filename"],
                "content_type": d["content_type"],
                "size_bytes": d["size_bytes"],
                "description": d.get("description"),
                "uploaded_at": (
                    d["uploaded_at"].isoformat() if d.get("uploaded_at") else None
                ),
            }
        )
    return out


# ── outreach summary ─────────────────────────────────────────────────


@app.get("/outreach/stats")
def outreach_stats():
    db, _ = _mongo()
    pipe = [{"$group": {"_id": "$outcome", "n": {"$sum": 1}}}]
    by_outcome = {
        row["_id"] or "unknown": row["n"]
        for row in db.outreach_attempts.aggregate(pipe)
    }
    total = db.outreach_attempts.count_documents({})
    return {
        "total": total,
        "booked": by_outcome.get("booked", 0),
        "no_answer": by_outcome.get("no_answer", 0),
        "language_mismatch": by_outcome.get("language_mismatch", 0),
        "failed": by_outcome.get("failed", 0),
        "in_progress": by_outcome.get("in_progress", 0),
        "by_outcome": by_outcome,
    }


@app.get("/outreach")
def outreach_list(limit: int = 50, patient_id: Optional[str] = None):
    db, _ = _mongo()
    q: dict = {}
    if patient_id:
        q["patient_id"] = patient_id
    rows = list(
        db.outreach_attempts.find(q, {"events": 0})
        .sort("started_at", -1)
        .limit(max(1, min(limit, 200)))
    )
    out = []
    for r in rows:
        r["_id"] = str(r["_id"])
        for k in ("started_at", "ended_at"):
            if r.get(k):
                r[k] = r[k].isoformat()
        if not r.get("ai_summary"):
            r["ai_summary"] = _summarize(r)
        out.append(r)
    return out


@app.get("/outreach/{outreach_id}")
def outreach_detail(outreach_id: str):
    db, _ = _mongo()
    r = db.outreach_attempts.find_one({"outreach_id": outreach_id})
    if not r:
        raise HTTPException(status_code=404, detail="outreach not found")
    r["_id"] = str(r["_id"])
    for k in ("started_at", "ended_at"):
        if r.get(k):
            r[k] = r[k].isoformat()
    if not r.get("ai_summary"):
        r["ai_summary"] = _summarize(r)
    return r


@app.get("/document/{doc_id}")
def fetch_document(doc_id: str):
    db, fs = _mongo()
    try:
        oid = ObjectId(doc_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid doc_id")

    meta = db.patient_documents.find_one({"_id": oid})
    if not meta:
        raise HTTPException(status_code=404, detail="document not found")

    grid_out = fs.get(meta["gridfs_id"])
    return StreamingResponse(
        iter([grid_out.read()]),
        media_type=meta["content_type"],
        headers={
            "Content-Disposition": f'inline; filename="{meta["filename"]}"',
            "Content-Length": str(meta["size_bytes"]),
        },
    )


# ── transcript + fingerprint queries ────────────────────────────────


@app.get("/transcript/{call_sid}")
def get_transcript(call_sid: str):
    """Retrieve stored transcript (Agent/User labelled) for a call."""
    from common.transcript_store import get_transcript as _get

    doc = _get(call_sid)
    if not doc:
        raise HTTPException(status_code=404, detail="transcript not found")
    return doc


@app.get("/fingerprints/{patient_id}")
def list_fingerprints(patient_id: str):
    """All conversation fingerprints for a patient, newest first."""
    from common.transcript_store import get_fingerprints_by_patient

    return get_fingerprints_by_patient(patient_id)


@app.get("/fingerprint/{fingerprint_id}")
def get_fingerprint(fingerprint_id: str):
    """Single fingerprint by ID."""
    from common.transcript_store import get_fingerprint as _get

    doc = _get(fingerprint_id)
    if not doc:
        raise HTTPException(status_code=404, detail="fingerprint not found")
    return doc
