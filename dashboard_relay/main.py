"""HealthSwarm dashboard relay — fan-out SSE bus on :3001.

POST /telemetry  — agents/voice_gateway emit beacons here via
                   common.telemetry.beacon(). Body: {src, dst, kind, payload}.
                   We tag with received_at, append to ring buffer, push to
                   every subscriber's queue, return 200.

GET  /stream     — Next.js dashboard subscribes here as an EventSource.
                   On connect we replay buffered history so the war-room
                   isn't blank if the page loads mid-call. Then we stream
                   live events.

GET  /health     — sanity check + counts.

Designed to never block the producer:
- POST returns immediately even if a subscriber's queue is full
  (dropped events would be visible to that client only).
- common.telemetry.beacon already sets a 0.5s timeout and swallows
  errors, so the relay being down does not affect agents.
"""
from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="HealthSwarm Dashboard Relay")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HISTORY_CAP = 1000
SUBSCRIBER_QUEUE_CAP = 500  # drop if dashboard is frozen — never block producer

events: deque[dict[str, Any]] = deque(maxlen=HISTORY_CAP)
subscribers: list[asyncio.Queue] = []


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
    events.append(evt)

    for q in subscribers:
        try:
            q.put_nowait(evt)
        except asyncio.QueueFull:
            # Dashboard client is slow — drop for that subscriber only
            pass

    return {"ok": True, "subscribers": len(subscribers)}


@app.get("/stream")
async def stream(req: Request):
    queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_CAP)
    subscribers.append(queue)

    async def generate():
        try:
            # Replay history so a late-joining dashboard isn't blank
            for evt in list(events):
                yield f"data: {json.dumps(evt)}\n\n"

            # Heartbeat every 15s so reverse proxies don't kill idle connection
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx-style buffering
        },
    )


@app.get("/health")
def health():
    return {
        "ok": True,
        "buffered_events": len(events),
        "subscribers": len(subscribers),
    }
