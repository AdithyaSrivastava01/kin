# HealthSwarm — Agentverse Agent Registry

All HealthSwarm agents are registered on [Agentverse](https://agentverse.ai) with **Active** status,
**ASI:One** integration, and **Mailbox** enabled.

## Agent Addresses & Profile URLs

| Agent | Role | Address | Profile |
|---|---|---|---|
| healthswarm-intake | Orchestrator — routes patient requests to the swarm | `agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu` | [View](https://agentverse.ai/agents/agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu) |
| healthswarm-profiler | Retrieves patient medical profile from MongoDB | `agent1q0ftk9jz5lslz4l3glp4qa6yt77yxyk9e8ya9rmjzjq8u6zkzr467ksafvu` | [View](https://agentverse.ai/agents/agent1q0ftk9jz5lslz4l3glp4qa6yt77yxyk9e8ya9rmjzjq8u6zkzr467ksafvu) |
| healthswarm-finder | Geospatial clinic search via MongoDB 2dsphere | `agent1qduz7y0f26t0ezgqtj57439w8yw2vrn9gmev79h2lf6n4sx7ymghguwse65` | [View](https://agentverse.ai/agents/agent1qduz7y0f26t0ezgqtj57439w8yw2vrn9gmev79h2lf6n4sx7ymghguwse65) |
| healthswarm-matcher | LLM judge — ranks candidate clinics before calling | `agent1qghpy4860rfxus5ftzagkpwkyvcde8je69kszpz5zm7x02mtxtmlz0j46nc` | [View](https://agentverse.ai/agents/agent1qghpy4860rfxus5ftzagkpwkyvcde8je69kszpz5zm7x02mtxtmlz0j46nc) |
| healthswarm-caller | Calls ranked clinics via Twilio and falls through on failure | Set by `CALLER_SEED` | Publish with `agents.swarm_caller.uagent_runner` |
| healthswarm-fingerprint | Summarises call transcripts into structured facts | `agent1qdyyvylzsymr6w9r8zq7vwyyd2x8q87s3p6qhs063l2txqn4s4jg223yncw` | [View](https://agentverse.ai/agents/agent1qdyyvylzsymr6w9r8zq7vwyyd2x8q87s3p6qhs063l2txqn4s4jg223yncw) |

## Running the Agents Locally

### Prerequisites

```bash
# From kin/
python3 -m venv .venv
.venv/bin/pip install uagents uagents-core python-dotenv openai pymongo
```

Copy `.env.example` to `.env` and fill in:
```
ASI_ONE_API_KEY=...
AGENTVERSE_API_KEY=...
MONGO_URI=mongodb+srv://...
INTAKE_SEED=<any unique passphrase>
PROFILER_SEED=<any unique passphrase>
FINDER_SEED=<any unique passphrase>
MATCHER_SEED=<any unique passphrase>
CALLER_SEED=<any unique passphrase>
FINGERPRINT_SEED=<any unique passphrase>
```

> **Note:** Seeds derive the permanent `agent1q...` address. Use the seeds above (in `.env`)
> to reproduce the same addresses. Ask the team for the shared seed values.

### Start all 5 agents (survives terminal close via tmux)

```bash
tmux new-session -d -s healthswarm
cd /path/to/kin
for agent in swarm_intake swarm_profiler swarm_finder swarm_matcher swarm_caller swarm_fingerprint; do
  PYTHONPATH=. .venv/bin/python -m agents.${agent}.uagent_runner >> /tmp/hs-${agent}.log 2>&1 &
done
```

Or run individually:
```bash
cd kin/
PYTHONPATH=. .venv/bin/python -m agents.swarm_intake.uagent_runner
PYTHONPATH=. .venv/bin/python -m agents.swarm_profiler.uagent_runner
PYTHONPATH=. .venv/bin/python -m agents.swarm_finder.uagent_runner
PYTHONPATH=. .venv/bin/python -m agents.swarm_matcher.uagent_runner
PYTHONPATH=. .venv/bin/python -m agents.swarm_caller.uagent_runner
PYTHONPATH=. .venv/bin/python -m agents.swarm_fingerprint.uagent_runner
```

### Logs

```bash
tail -f /tmp/hs-intake.log
tail -f /tmp/hs-profiler.log
tail -f /tmp/hs-finder.log
tail -f /tmp/hs-matcher.log
tail -f /tmp/hs-fingerprint.log
```

## Architecture

```
User Request
     │
     ▼
swarm-intake  (orchestrator)
  ├──▶ swarm-profiler   (patient profile from MongoDB)
  ├──▶ swarm-finder     (nearby clinics via geospatial query)
  │
  ├──▶ swarm-matcher    (parallel clinic ranking)
  │
  └──▶ swarm-caller     (calls ranked clinics with fallback)
            │
            ▼
       swarm-fingerprint (summarises completed call transcripts)
```

All LLM calls use **ASI:One** (`https://api.asi1.ai/v1`, model `asi1`).
