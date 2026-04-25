import requests

DASH = "http://localhost:3001/telemetry"


def beacon(src: str, dst: str, kind: str, payload: dict):
    """Emit a telemetry event to the dashboard relay. Never blocks the agent."""
    try:
        requests.post(
            DASH,
            json={"src": src, "dst": dst, "kind": kind, "payload": payload},
            timeout=0.5,
        )
    except Exception:
        pass
