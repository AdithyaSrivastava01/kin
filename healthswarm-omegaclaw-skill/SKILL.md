# HealthSwarm — OmegaClaw Skill

**Agent address:** `agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu`
**Protocol:** ASI:One Chat Protocol (uAgents `chat_protocol_spec`)
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

## How to invoke from OmegaClaw

Send any natural-language booking request. Reference a demo persona by first name:

```
Book a dermatology appointment for Joon
Maria needs a Spanish-speaking primary care doctor this week
Rahul wants a cardiologist ASAP
```

Supported demo personas:

| Name | Patient ID | Specialty | Language |
|---|---|---|---|
| Maria | maria-001 | Primary care | Spanish |
| Joon | joon-001 | Dermatology | Korean |
| Rahul | rahul-001 | Cardiology | Hindi |

You can also pass an explicit patient ID:

```
patient_id=P042 Book an ophthalmology appointment, morning preferred
```

## Adding this skill to OmegaClaw

In the OmegaClaw Telegram bot, run:

```
/addskill agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu
```

OmegaClaw will invoke the skill whenever a user's message is routed to this agent
address. The agent responds with a human-readable booking summary (clinic name,
phone, language, rationale).

## Expected response format

```
Booking complete for Joon Park!
Clinic:    Seoul Dermatology Center
Phone:     +1-213-555-0187
Language:  Korean
Why:       Closest dermatologist accepting their insurance; Korean-speaking staff confirmed on call
```

## Technical notes

- The agent implements `chat_protocol_spec` with `publish_manifest=True`; it is
  discoverable by any ASI:One-compatible client including OmegaClaw.
- Booking takes 30–90 seconds (concurrent calls + LLM reasoning). A progress
  message is sent immediately; the final result follows when the swarm completes.
- All LLM reasoning uses ASI:One (`asi1` model via `https://api.asi1.ai/v1`).
