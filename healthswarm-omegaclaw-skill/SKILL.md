# HealthSwarm — OmegaClaw Skill

**Agent address:** `agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu`
**Protocol:** BookingRequest/BookingResponse (uAgents Model) + ASI:One Chat Protocol
**Agentverse profile:** https://agentverse.ai/agents/agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu

## What it does

Books medical appointments by dispatching a 5-agent swarm:

| Agent | Role |
|---|---|
| healthswarm-intake | Orchestrator — routes requests, coordinates swarm |
| healthswarm-profiler | Retrieves patient medical history from MongoDB |
| healthswarm-finder | Geospatial clinic search (MongoDB 2dsphere, 15 km radius) |
| healthswarm-matcher | LLM judge — ranks clinics by metadata, then judges fingerprints to pick the winner |
| healthswarm-caller | Calls the top-ranked clinics in parallel |
| healthswarm-fingerprint | Translates and structures each call transcript |

The voice gateway places parallel calls to the top-ranked clinics. Receptionist
audio is transcribed by ElevenLabs Scribe (which also returns the detected
language), and the ElevenLabs TTS voice switches to match. Each call's
transcript is handed to swarm-fingerprint, which translates it to English
and extracts structured facts. swarm-matcher then judges those fingerprints
to pick the final winning clinic.

## Supported demo personas

| Name | Patient ID | Specialty | Language |
|---|---|---|---|
| Maria | maria-001 | Primary care | Spanish |
| Joon | joon-001 | Dermatology | Korean |
| Rahul | rahul-001 | Cardiology | Hindi |

Example queries from OmegaClaw/Telegram:
```
Book a dermatology appointment for Joon
Maria needs a Spanish-speaking primary care doctor this week
Rahul wants a cardiologist ASAP
```

---

## Integrating with OmegaClaw (one command)

```bash
bash scripts/setup_omegaclaw.sh
```

This script starts the OmegaClaw Docker container, injects the HTTP bridge
function into `agentverse.py`, registers the skill in `skills.metta`, and
restarts the container. Run it once from the `kin/` directory with `.env`
populated.

### Prerequisites

- Docker running
- `.env` with `ASI_ONE_API_KEY` and `TG_BOT_TOKEN` set
- healthswarm-intake running on the host (`PYTHONPATH=. .venv/bin/python -m agents.swarm_intake.uagent_runner`)

---

## How it works under the hood

OmegaClaw invokes skills via `py-call` → `healthswarm_skill(query)` appended
to `agentverse.py` inside the container → **HTTP POST to
`http://host.docker.internal:8015/book`** (the bridge server embedded in
`uagent_runner.py`) → healthswarm-intake runs the full swarm (30–90 s) →
returns `{"result": "..."}` → formatted text surfaces in your Telegram DM.

The HTTP bridge bypasses uAgents envelope version incompatibilities between
the Docker container and the host Python environment.

## Expected Telegram response

```
Booking complete for Joon Park!
Clinic:    Seoul Dermatology Center
Phone:     +1-213-555-0187
Language:  Korean
Why:       Closest dermatologist accepting their insurance; Korean-speaking staff confirmed on call
```

## Technical notes

- **Two protocols on one agent:** healthswarm-intake handles `BookingRequest` (OmegaClaw)
  and `ChatMessage` via Chat Protocol (ASI:One direct chat) on the same port 8010.
- **HTTP bridge on port 8015:** OmegaClaw Docker → `host.docker.internal:8015/book`
  → intake agent on host. Set `OMEGACLAW_BRIDGE_PORT` in `.env` to override.
- **All LLM reasoning uses ASI:One** (`asi1` model via `https://api.asi1.ai/v1`).
