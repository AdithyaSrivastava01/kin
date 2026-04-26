"""OmegaClaw skill adapter for HealthSwarm.

Drop this file into OmegaClaw's agentverse/ directory alongside the existing
agentverse.py. OmegaClaw calls healthswarm_booking() via py-call from MeTTa.

Usage from skills.metta:
    (= (healthswarm-booking $query)
       (py-call (agentverse.healthswarm_booking $query)))

Talks to the local healthswarm-intake runner over its HTTP bridge instead
of via Agentverse mailbox routing. This avoids hardcoding any uAgent
address — OmegaClaw's container reaches the host through Docker's
host.docker.internal hostname, which Docker Desktop maps automatically.

Override INTAKE_BRIDGE_URL via env var if running OmegaClaw in a
different network topology.
"""
import json
import os
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

INTAKE_BRIDGE_URL = os.environ.get(
    "INTAKE_BRIDGE_URL", "http://host.docker.internal:8015/book"
)


def healthswarm_booking(query: str, timeout: int = 180) -> str:
    """Book a medical appointment via the HealthSwarm agent swarm.

    Posts the query to the intake runner's /book bridge and waits up to
    `timeout` seconds for the 5-agent swarm to complete and return a
    formatted booking summary.

    Args:
        query: Natural-language booking request, e.g.
               "Book a dermatology appointment for Joon"
               "Maria needs a Spanish-speaking primary care doctor this week"
               "Rahul wants a cardiologist ASAP"
        timeout: Seconds to wait for the swarm to complete (default 180).

    Returns:
        Human-readable booking result string, or "error: ..." on failure.
    """
    payload = json.dumps({"query": query}).encode("utf-8")
    req = urlrequest.Request(
        INTAKE_BRIDGE_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=int(timeout)) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", str(e))
        except Exception:
            err = str(e)
        return f"error: intake bridge returned {e.code}: {err}"
    except URLError as e:
        return (
            f"error: cannot reach intake bridge at {INTAKE_BRIDGE_URL} ({e.reason}). "
            "Ensure the runner is up: PYTHONPATH=. python -m agents.swarm_intake.uagent_runner"
        )
    except Exception as e:
        return f"error: {e!r}"

    try:
        return json.loads(body).get("result", body)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return body


def healthswarm_skill(query: str, timeout: int = 180) -> str:
    """Backward-compatible alias for older skills.metta snippets."""
    return healthswarm_booking(query, timeout)
