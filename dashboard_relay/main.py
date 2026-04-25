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
    return _db, _fs


def _broadcast(evt: dict):
    """Push a beacon-shaped event to all SSE subscribers + history."""
    events.append(evt)
    for q in subscribers:
        try:
            q.put_nowait(evt)
        except asyncio.QueueFull:
            pass


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
            "patient_id":       p["patient_id"],
            "name":             p["name"],
            "primary_language": p.get("primary_language"),
            "insurance_id":     p.get("insurance_id"),
        }
        for p in db.patients.find(
            {},
            {"_id": 0, "patient_id": 1, "name": 1, "primary_language": 1, "insurance_id": 1},
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
        "patient_id":   patient_id,
        "filename":     file.filename,
        "content_type": file.content_type or "application/octet-stream",
        "size_bytes":   len(data),
        "description":  description,
        "uploaded_at":  datetime.now(timezone.utc),
        "gridfs_id":    gridfs_id,
    }
    result = db.patient_documents.insert_one(meta)
    doc_id = str(result.inserted_id)

    # Beacon so the war-room dashboard shows the upload in real time
    _broadcast({
        "src": "patient",
        "dst": "swarm-profiler",
        "kind": "DocumentUploaded",
        "payload": {
            "patient_id":   patient_id,
            "patient_name": patient["name"],
            "filename":     file.filename,
            "size_bytes":   len(data),
            "content_type": file.content_type,
            "doc_id":       doc_id,
        },
        "received_at": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "ok":         True,
        "doc_id":     doc_id,
        "filename":   file.filename,
        "size_bytes": len(data),
    }


@app.get("/documents/{patient_id}")
def list_documents(patient_id: str):
    db, _ = _mongo()
    out = []
    for d in db.patient_documents.find({"patient_id": patient_id}).sort("uploaded_at", -1):
        out.append({
            "doc_id":       str(d["_id"]),
            "filename":     d["filename"],
            "content_type": d["content_type"],
            "size_bytes":   d["size_bytes"],
            "description":  d.get("description"),
            "uploaded_at":  d["uploaded_at"].isoformat() if d.get("uploaded_at") else None,
        })
    return out


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
            "Content-Length":      str(meta["size_bytes"]),
        },
    )
