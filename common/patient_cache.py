"""In-memory patient profile cache.

swarm-profiler writes here after loading a profile.
Anything running in the same process (intake, caller) can read without
another MongoDB round-trip.

For the voice gateway (separate process), the caller pushes the full
profile fields in the /call HTTP request body — this cache is the source
of truth on the intake side.

Thread-safe — profiler and caller run in different threads.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_store: dict[str, dict] = {}


def put(patient_id: str, profile: dict) -> None:
    with _lock:
        _store[patient_id] = dict(profile)


def get(patient_id: str) -> dict | None:
    with _lock:
        entry = _store.get(patient_id)
        return dict(entry) if entry else None


def all_ids() -> list[str]:
    with _lock:
        return list(_store.keys())
