![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

# Kin — Multilingual Multi-Agent Family-Crisis Coordination System

Kin is the emergency operations room for families separated by oceans and languages. When your father collapses in Mumbai and the hospital dispatcher only speaks Marathi, Kin spins up a coordinated multi-agent system that translates, locates hospitals, finds flights, and retrieves medical records — all in real time.

## Architecture

```
asi1.ai/chat → kin-triage (orchestrator)
                  ├── kin-translator  (Gemma E4B on Vultr GPU)
                  ├── kin-doctor      (OSM Overpass + Twilio)
                  ├── kin-vault       (MongoDB Atlas — deterministic)
                  └── kin-logistics   (Duffel + Google Maps Routes)
```

All 5 agents are registered on [Agentverse](https://agentverse.ai), powered by [ASI:One](https://asi1.ai), and communicate via the Fetch.ai Chat Protocol.

## Tracks

- **Fetch.ai Track 1** — ASI:One Multi-Agent (5 registered agents)
- **Fetch.ai Track 2** — OmegaClaw Skill
- **Arista "Connect the Dots"** — Live React Flow war-room dashboard
- **Vultr Cloud GPU** — Gemma E4B speech translation
- **MongoDB** — Patient records, hospital data, medication normalization
- **ElevenLabs** — Sub-100ms conversational filler
- **Health** — Family medical emergency coordination

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # fill in your API keys
```

## Running Agents

```bash
# Each in a separate terminal:
python agents/kin_triage/agent.py
python agents/kin_translator/agent.py
python agents/kin_doctor/agent.py
python agents/kin_vault/agent.py
python agents/kin_logistics/agent.py
```

## Dashboard

```bash
# SSE relay
python dashboard_relay/main.py

# Next.js dashboard
cd kin-dashboard && npm run dev
```

## Agent Addresses

| Agent | Agentverse Profile |
|---|---|
| kin-triage | `https://agentverse.ai/agents/details/<address>/profile` |
| kin-translator | `https://agentverse.ai/agents/details/<address>/profile` |
| kin-doctor | `https://agentverse.ai/agents/details/<address>/profile` |
| kin-vault | `https://agentverse.ai/agents/details/<address>/profile` |
| kin-logistics | `https://agentverse.ai/agents/details/<address>/profile` |

## Shared Chat

`https://asi1.ai/shared-chat/<uuid>`
