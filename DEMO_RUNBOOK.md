# HealthSwarm — Demo Run-Book

What to start, in what order, and what to watch for during the live demo.

## One-time setup (any teammate, any laptop)

```bash
# 1. Python deps
python -m pip install pymongo requests python-dotenv certifi fastapi uvicorn uagents uagents-core openai

# 2. Node deps
cd healthswarm-dashboard && npm install && cd ..

# 3. .env  (copy from .env.example, fill in real values)
cp .env.example .env   # edit MONGO_URI, ELEVENLABS, TWILIO, etc.

# 4. Seed the database (only once, ~90s)
python scripts/migrate_v2.py             # patients + insurance + clinic_insurance + medical_records
python scripts/ingest_clinics.py         # 3,300+ OSM clinics

# 5. (optional) Pre-generate AI medical records — falls back to a stub
#    if ASI_ONE_API_KEY is missing in .env
python scripts/profile_patient.py --all
```

## Live-demo checklist (T-15 minutes)

Open four terminals. Keep this order — relay must be up before the dashboard subscribes.

**Terminal 1 — relay (always running)**
```bash
python -m uvicorn dashboard_relay.main:app --port 3001
```
Verify: `curl http://localhost:3001/health` returns `{"ok": true, ...}`.

**Terminal 2 — dashboard (always running)**
```bash
cd healthswarm-dashboard && npm run dev
```
Open `http://localhost:3000` in a browser. Status badge should flip
`connecting` → `LIVE` (pulsing green) within 1 second.

**Terminal 3 — voice gateway (E2 only, when ready)**

Two options:

*Auto-start ngrok (recommended for dev — one terminal, no copy-paste):*
```bash
pip install pyngrok                                          # one time
# in .env:  NGROK_AUTOSTART=true   NGROK_AUTHTOKEN=<your-token>
python -m uvicorn voice_gateway.main:app --port 8000
```
The gateway opens the tunnel itself, prints the URL, and uses it
automatically. NGROK_URL in .env is ignored when autostart is on.

*Manual ngrok (matches the production layout):*
```bash
ngrok http 8000                                              # in one tab
python -m uvicorn voice_gateway.main:app --port 8000         # in another
```
Set `NGROK_URL` in `.env` to whatever ngrok prints.

**Terminal 4 — demo trigger (the one you use during the talk)**
This is the only one you touch on stage.

**OmegaClaw / Agentverse agents**
```bash
for agent in swarm_intake swarm_profiler swarm_finder swarm_matcher swarm_caller swarm_fingerprint; do
  PYTHONPATH=. .venv/bin/python -m agents.${agent}.uagent_runner >> /tmp/hs-${agent}.log 2>&1 &
done
bash scripts/setup_omegaclaw.sh
```

## Running the demo

### Option A — pure dashboard demo (no real call)

```bash
python scripts/demo_rehearsal.py --patient joon-001
```

Story arc (8 graph events + 3 mocked voice events, ~12 seconds):
1. Patient request lights up the intake node
2. Profiler + finder fan out (parallel green edges)
3. Matcher returns the winning clinic (orange edge with name + address)
4. Caller node activates (red edge)
5. **3-second pause** — judges read the graph
6. CallStarted (red)
7. **🌐 LanguageDetected — amber banner pulses, amber edge to clinic** ← the wow moment
8. BookingResult — outcome appears in feed

Switch personas mid-talk:
```bash
python scripts/demo_rehearsal.py --patient maria-001    # Spanish
python scripts/demo_rehearsal.py --patient rahul-001    # Hindi
```

### Option B — real Twilio call (E2 unblocked)

```bash
python scripts/demo_rehearsal.py --real-call --to +1XXXXXXXXXX --patient joon-001
```

The graph runs first. Then the voice gateway places an actual call.
A teammate on the receiving end answers in Korean. ElevenLabs Scribe
detects the language in ~3s, ElevenLabs TTS switches voice mid-call,
dashboard shows the real `LanguageDetected` beacon (no `mocked: true`
flag). After the call, swarm-fingerprint translates the transcript to
English and swarm-matcher (LLM judge) picks the winning clinic.

### Option C — passive backdrop loop (during Q&A)

```bash
python scripts/sim_swarm.py --loop
```
Cycles through all three patients every ~30s so the dashboard never
goes dark while you're answering questions.

## Inspector / sanity checks

```bash
python scripts/inspect_db.py
```
Prints patient list, clinic counts per city/specialty, and a live
geo-query showing the clinic swarm-finder will pick.

```bash
curl http://localhost:3001/health
```
Counts buffered events and connected dashboard subscribers.

## Visual cue cheat-sheet (talking points)

| What you point at | What's happening underneath |
|---|---|
| Patient → intake (sky blue) | ASI:One parses the natural-language request |
| Intake → profiler (green) | MongoDB lookup of medical history |
| Intake → finder (green, parallel) | OSM-derived clinic search via 2dsphere `$near` |
| Finder → intake CandidatesFound | 5 real LA clinics returned, names from OSM |
| Intake → matcher (green) | Parallel ASI:One scoring of candidate clinics |
| Matcher → intake ClinicRanked (orange) | Ranked clinics + scores; top N go to caller |
| Intake → caller (green) | Parallel booking task handoff (top N clinics) |
| Caller → clinic CallStarted (red) | Twilio dials the top-ranked clinics in parallel |
| **🌐 amber banner + amber edge** | **ElevenLabs Scribe detected non-English; TTS switched voice** |
| Fingerprint → matcher (green) | Per-call transcript translated + structured |
| Matcher → intake ClinicMatched (orange) | LLM judge picks the winning clinic from fingerprints |
| Caller → clinic BookingResult (red) | Appointment confirmed |

## Failure modes & fallbacks

| Symptom | Likely cause | Fallback |
|---|---|---|
| Status badge stuck on `connecting` | Relay not running | Start Terminal 1, refresh browser |
| `disconnected` (red) | Relay crashed | Auto-reconnects every 2s; restart relay |
| Graph runs but no LanguageDetected | --real-call mode but voice gateway down | Re-run without `--real-call` |
| Edges stay forever | TTL expired but state didn't update | Refresh browser |
| Dashboard slow / janky | Too many buffered events | Restart relay (clears buffer) |

If the live call fails on stage, fall back to **Option A** silently —
audience won't notice the difference.

## Devpost deliverables produced

- [ ] Atlas screenshot (Database → Browse Collections → `clinics`)
- [ ] 30-second screen recording of the war-room during a `demo_rehearsal.py` run
- [ ] Optional: backup MP4 of a successful real-call run

Hit cmd+shift+5 (mac) or Win+G (windows) to record. Capture the
browser window only — keep terminals out of frame.
