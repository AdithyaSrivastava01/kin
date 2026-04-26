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
| healthswarm-fingerprint | Summarises each call transcript into structured facts |
| healthswarm-matcher | LLM judge — ranks clinics and picks the best fit |

The voice gateway places concurrent Twilio calls to all candidate clinics, detects the
receptionist's language on first utterance via Gemma E4B, and switches the ElevenLabs
TTS voice automatically mid-call.

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

## Integrating with OmegaClaw (3-step process)

### Prerequisites

- OmegaClaw running via Docker (`singularitynet/omegaclaw:hackathon2604`)
- Telegram bot token from `@BotFather`
- `ASI_ONE_API_KEY` and `AGENTVERSE_API_KEY`
- healthswarm-intake running locally (`PYTHONPATH=. .venv/bin/python -m agents.swarm_intake.uagent_runner`)

### Step 1 — Copy the Python adapter into OmegaClaw

Copy `agentverse/healthswarm_skill.py` (from this folder) into OmegaClaw's
`agentverse/` directory inside the running container:

```bash
docker cp agentverse/healthswarm_skill.py omegaclaw:/app/agentverse/healthswarm_skill.py
```

Or if using Option 2 (custom Docker), place the file in
`repos/OmegaClaw-Core/agentverse/healthswarm_skill.py` before building.

### Step 2 — Add the MeTTa bridge function

Add the following to `src/skills.metta` in the OmegaClaw container:

```bash
docker exec -it omegaclaw bash
# then edit /app/src/skills.metta
```

Add this function definition:

```metta
(= (healthswarm-booking $query)
   (py-call (agentverse.healthswarm_skill $query)))
```

See `skills.metta.snippet` in this folder for the exact lines to paste.

### Step 3 — Register the skill in getSkills

In the same `src/skills.metta`, find the `getSkills` function and add:

```metta
"- Book a medical appointment for Maria, Joon, or Rahul via HealthSwarm AI: (healthswarm-booking string_in_quotes)"
```

Then restart OmegaClaw: `docker restart omegaclaw`

---

## How it works under the hood

OmegaClaw invokes skills via `py-call` → `healthswarm_booking(query)` in
`healthswarm_skill.py` → `send_sync_message(INTAKE_ADDRESS, BookingRequest(query), timeout=180)`
→ healthswarm-intake runs the full swarm (30–90 s) → returns `BookingResponse(result=...)`
→ formatted text surfaces in your Telegram DM.

The 180-second timeout covers the worst-case concurrent Twilio call polling cycle.

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
- **No ngrok needed:** OmegaClaw polls Telegram outbound; healthswarm-intake is reached
  directly via the Almanac address resolution.
- **All LLM reasoning uses ASI:One** (`asi1` model via `https://api.asi1.ai/v1`).
