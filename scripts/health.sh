#!/usr/bin/env bash
# Health monitor — run in a tmux pane during demo.
# Pings the voice gateway and dashboard relay every 30s.

set -euo pipefail

: "${NGROK_URL:=http://localhost:8000}"
: "${TELEMETRY_RELAY_URL:=http://localhost:3001/telemetry}"
RELAY_BASE="${TELEMETRY_RELAY_URL%/telemetry}"

while true; do
  ts=$(date +%T)

  if curl -fsS "${NGROK_URL}/health" > /dev/null 2>&1; then
    echo "${ts} gateway OK"
  else
    echo "${ts} GATEWAY DOWN"
  fi

  if curl -fsS "${RELAY_BASE}/health" > /dev/null 2>&1; then
    echo "${ts} relay   OK"
  else
    echo "${ts} RELAY DOWN"
  fi

  sleep 30
done
