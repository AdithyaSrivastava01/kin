#!/usr/bin/env bash
# setup_omegaclaw.sh — one-shot OmegaClaw + HealthSwarm skill setup
#
# Usage (from kin/):
#   bash scripts/setup_omegaclaw.sh

set -euo pipefail

# Stop Git Bash / MSYS from rewriting in-container paths like /PeTTa
# into Windows host paths like C:/Program Files/Git/PeTTa before
# docker exec sees them. Without this every find inside the container
# silently returns nothing and the skill injection step hangs.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # resolves to kin/
ENV_FILE="$SCRIPT_DIR/.env"
SKILL_PY="$SCRIPT_DIR/healthswarm-omegaclaw-skill/agentverse/healthswarm_skill.py"
OMEGACLAW_IMAGE="singularitynet/omegaclaw:hackathon2604"

# ── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
  set -a; source "$ENV_FILE"; set +a
else
  echo "ERROR: .env not found at $ENV_FILE" >&2; exit 1
fi

: "${ASI_ONE_API_KEY:?ASI_ONE_API_KEY not set in .env}"
: "${TG_BOT_TOKEN:?TG_BOT_TOKEN not set in .env}"

# ── Step 1: pull image ───────────────────────────────────────────────────────
echo ""
echo "==> [1/5] Pulling OmegaClaw image..."
docker pull "$OMEGACLAW_IMAGE"

# ── Step 2: remove stale container ──────────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q '^omegaclaw$'; then
  echo "==> Removing existing omegaclaw container..."
  docker rm -f omegaclaw
  docker volume rm omegaclaw-memory 2>/dev/null || true
fi

# ── Step 3: start container directly (bypass interactive wizard) ─────────────
# The setup script uses /dev/tty which breaks non-interactive use.
# We replicate the exact docker run it would have built.
echo ""
echo "==> [2/5] Starting OmegaClaw container (Telegram + ASI:One)..."

AUTH_SECRET="$(openssl rand -hex 16)"

docker run -d -it \
  --name omegaclaw \
  --init \
  --volume omegaclaw-memory:/PeTTa/repos/OmegaClaw-Core/memory \
  --tmpfs /tmp:size=64m,mode=1777 \
  --tmpfs /run:size=16m,mode=755 \
  --tmpfs /var/tmp:size=64m,mode=1777 \
  -e "ASIONE_API_KEY=${ASI_ONE_API_KEY}" \
  -e "OMEGACLAW_AUTH_SECRET=${AUTH_SECRET}" \
  "$OMEGACLAW_IMAGE" \
  "commchannel=telegram" \
  "provider=ASIOne" \
  "embeddingprovider=Local" \
  "TG_BOT_TOKEN=${TG_BOT_TOKEN}" \
  "TG_POLL_TIMEOUT=20"

# ── Step 4: wait for container to be running ─────────────────────────────────
echo ""
echo "==> Waiting for container to start..."
for i in $(seq 1 30); do
  if docker ps --filter name=omegaclaw --filter status=running -q | grep -q .; then
    echo "    omegaclaw is up."
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: container did not start in 60s" >&2
    docker logs omegaclaw | tail -20
    exit 1
  fi
  sleep 2
done

# give OmegaClaw a few seconds to initialise its Python environment
sleep 5

# ── Step 5: inject skill adapter ─────────────────────────────────────────────
echo ""
echo "==> [3/5] Injecting healthswarm_skill.py..."
AGENTVERSE_DIR=$(docker exec omegaclaw find /PeTTa -name "agentverse.py" 2>/dev/null \
  | head -1 | xargs -I{} dirname {})

if [ -z "$AGENTVERSE_DIR" ]; then
  # fallback search
  AGENTVERSE_DIR=$(docker exec omegaclaw find / -name "agentverse.py" 2>/dev/null \
    | grep -v proc | head -1 | xargs -I{} dirname {})
fi

if [ -z "$AGENTVERSE_DIR" ]; then
  echo "ERROR: could not find agentverse.py inside container" >&2
  docker exec omegaclaw find / -name "*.py" 2>/dev/null | grep -v proc | head -20
  exit 1
fi

echo "    target: omegaclaw:$AGENTVERSE_DIR/healthswarm_skill.py"
# On Git Bash / MSYS the Docker CLI needs a Windows-style host path
# because we disabled MSYS path conversion above. cygpath handles it
# on Windows and is a no-op (graceful fallback) on Linux/macOS.
if command -v cygpath >/dev/null 2>&1; then
  SKILL_PY_HOST="$(cygpath -w "$SKILL_PY")"
else
  SKILL_PY_HOST="$SKILL_PY"
fi
docker cp "$SKILL_PY_HOST" "omegaclaw:$AGENTVERSE_DIR/healthswarm_skill.py"

# ── Step 6: patch skills.metta ───────────────────────────────────────────────
echo ""
echo "==> [4/5] Patching skills.metta..."
SKILLS_METTA=$(docker exec omegaclaw find /PeTTa -name "skills.metta" 2>/dev/null | head -1)

if [ -z "$SKILLS_METTA" ]; then
  SKILLS_METTA=$(docker exec omegaclaw find / -name "skills.metta" 2>/dev/null \
    | grep -v proc | head -1)
fi

if [ -z "$SKILLS_METTA" ]; then
  echo "ERROR: skills.metta not found inside container" >&2; exit 1
fi
echo "    found: $SKILLS_METTA"

# Add bridge function (idempotent)
docker exec omegaclaw bash -c "
  if grep -q 'healthswarm-booking' '$SKILLS_METTA'; then
    echo '    bridge already present, skipping'
  else
    printf '\n;; HealthSwarm booking skill\n(= (healthswarm-booking \$query)\n   (py-call (agentverse.healthswarm_booking \$query)))\n' >> '$SKILLS_METTA'
    echo '    bridge function added'
  fi
"

# Add getSkills entry (idempotent)
docker exec omegaclaw bash -c "
  if grep -q 'HealthSwarm' '$SKILLS_METTA'; then
    echo '    getSkills entry already present, skipping'
  else
    sed -i 's|(tavily-search string_in_quotes)\"|(tavily-search string_in_quotes)\"\n    \"- Book a medical appointment for Maria, Joon, or Rahul using HealthSwarm AI: (healthswarm-booking string_in_quotes)\"|' '$SKILLS_METTA'
    echo '    getSkills entry added'
  fi
"

echo "    verification:"
docker exec omegaclaw grep -n "healthswarm" "$SKILLS_METTA"

# ── Step 6b: append healthswarm_skill function to agentverse.py ──────────────
AGENTVERSE_PY="$(docker exec omegaclaw find /PeTTa -name "agentverse.py" 2>/dev/null | head -1)"
echo ""
echo "==> Patching agentverse.py ($AGENTVERSE_PY)..."
docker exec omegaclaw bash -c "
  if grep -q 'def healthswarm_booking' '$AGENTVERSE_PY'; then
    echo '    healthswarm_booking already in agentverse.py, skipping'
  else
    cat >> '$AGENTVERSE_PY' << 'PYEOF'


# ── HealthSwarm booking skill ────────────────────────────────────────────────
import json as _json

HEALTHSWARM_INTAKE_ADDRESS = (
    \"agent1qw8ycstyjepy0646l8kmwzgzx2msv9ajmu0t5742c2kp2v5vgnehv6z2wsu\"
)

class BookingRequest(Model):
    query: str

class BookingResponse(Model):
    result: str

def healthswarm_booking(query: str, timeout: int = 180) -> str:
    try:
        request = BookingRequest(query=query)
        raw = asyncio.run(_ask_agent(HEALTHSWARM_INTAKE_ADDRESS, request, int(timeout)))
        try:
            data = _json.loads(raw)
            return data.get(\"result\", raw)
        except (ValueError, AttributeError, TypeError):
            return raw
    except Exception as e:
        return f\"error: {e}\"

def healthswarm_skill(query: str, timeout: int = 180) -> str:
    return healthswarm_booking(query, timeout)
PYEOF
    echo '    healthswarm_skill added to agentverse.py'
  fi
"

# ── Step 7: restart to pick up skills.metta changes ─────────────────────────
echo ""
echo "==> [5/5] Restarting OmegaClaw to load skill..."
docker restart omegaclaw
sleep 5

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OmegaClaw is live with the HealthSwarm skill!"
echo ""
echo "  Open Telegram and message your bot:"
echo "    Book a dermatology appointment for Joon"
echo "    Maria needs a Spanish-speaking primary care doctor"
echo "    Rahul wants a cardiologist ASAP"
echo ""
echo "  Make sure healthswarm-intake is running on the host:"
echo "    PYTHONPATH=. .venv/bin/python -m agents.swarm_intake.uagent_runner"
echo ""
echo "  Watch OmegaClaw logs:"
echo "    docker logs -f omegaclaw | grep -v '^(CHARS_SENT'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
