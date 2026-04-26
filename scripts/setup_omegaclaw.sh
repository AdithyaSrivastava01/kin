#!/usr/bin/env bash
# setup_omegaclaw.sh — one-shot OmegaClaw + HealthSwarm skill setup
#
# Usage (from kin/):
#   bash scripts/setup_omegaclaw.sh
#
# What it does:
#   1. Pulls the OmegaClaw Docker image
#   2. Runs the interactive setup wizard non-interactively (Telegram + ASI:One)
#   3. Copies healthswarm_skill.py into the container
#   4. Patches src/skills.metta with the healthswarm-booking bridge + getSkills entry
#   5. Restarts OmegaClaw to pick up the changes
#   6. Prints the Telegram bot link and test prompts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"   # resolves to kin/
ENV_FILE="$SCRIPT_DIR/.env"
SKILL_PY="$SCRIPT_DIR/healthswarm-omegaclaw-skill/agentverse/healthswarm_skill.py"
OMEGACLAW_IMAGE="singularitynet/omegaclaw:hackathon2604"
OMEGACLAW_SETUP_URL="https://raw.githubusercontent.com/asi-alliance/OmegaClaw-Core/refs/tags/hackathon2604/scripts/omegaclaw"

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

# ── Step 2: remove stale container if it exists ──────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q '^omegaclaw$'; then
  echo "==> Removing existing omegaclaw container..."
  docker rm -f omegaclaw
  docker volume rm omegaclaw-memory 2>/dev/null || true
fi

# ── Step 3: run setup wizard non-interactively ───────────────────────────────
# Input sequence: accept → 2 (Telegram) → bot token → 4 (ASI:One) → api key
echo ""
echo "==> [2/5] Running OmegaClaw setup (Telegram + ASI:One)..."
TMP_SETUP=$(mktemp)
curl -fsSL "$OMEGACLAW_SETUP_URL" -o "$TMP_SETUP"
chmod +x "$TMP_SETUP"
printf 'accept\n2\n%s\n4\n%s\n' "$TG_BOT_TOKEN" "$ASI_ONE_API_KEY" \
  | bash "$TMP_SETUP" "$OMEGACLAW_IMAGE"
rm -f "$TMP_SETUP"

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

# ── Step 5: inject skill adapter ─────────────────────────────────────────────
echo ""
echo "==> [3/5] Injecting healthswarm_skill.py..."
AGENTVERSE_DIR=$(docker exec omegaclaw find /app -name "agentverse.py" 2>/dev/null \
  | head -1 | xargs dirname)

if [ -z "$AGENTVERSE_DIR" ]; then
  echo "ERROR: could not find agentverse.py inside container" >&2
  exit 1
fi
echo "    target: omegaclaw:$AGENTVERSE_DIR/healthswarm_skill.py"
docker cp "$SKILL_PY" "omegaclaw:$AGENTVERSE_DIR/healthswarm_skill.py"

# ── Step 6: patch skills.metta ───────────────────────────────────────────────
echo ""
echo "==> [4/5] Patching src/skills.metta..."
SKILLS_METTA=$(docker exec omegaclaw find /app -name "skills.metta" 2>/dev/null | head -1)

if [ -z "$SKILLS_METTA" ]; then
  echo "ERROR: skills.metta not found inside container" >&2
  exit 1
fi
echo "    found: $SKILLS_METTA"

# Add bridge function (idempotent)
docker exec omegaclaw bash -c "
  if grep -q 'healthswarm-booking' '$SKILLS_METTA'; then
    echo '    bridge function already present, skipping'
  else
    printf '\n;; HealthSwarm booking skill\n(= (healthswarm-booking \$query)\n   (py-call (agentverse.healthswarm_skill \$query)))\n' >> '$SKILLS_METTA'
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

# ── Step 7: restart to pick up changes ───────────────────────────────────────
echo ""
echo "==> [5/5] Restarting OmegaClaw..."
docker restart omegaclaw
sleep 3

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  OmegaClaw is live with the HealthSwarm skill."
echo ""
echo "  Open Telegram and message your bot. Try:"
echo "    Book a dermatology appointment for Joon"
echo "    Maria needs a Spanish-speaking primary care doctor"
echo "    Rahul wants a cardiologist ASAP"
echo ""
echo "  IMPORTANT: also start healthswarm-intake in a separate terminal:"
echo "    cd $SCRIPT_DIR"
echo "    PYTHONPATH=. .venv/bin/python -m agents.swarm_intake.uagent_runner"
echo ""
echo "  Watch OmegaClaw logs:"
echo "    docker logs -f omegaclaw | grep -v '^(CHARS_SENT'"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
