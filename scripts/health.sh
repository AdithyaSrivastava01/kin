#!/usr/bin/env bash
# Health monitor — run in a tmux pane during demo.
# Checks Gemma GPU server and local voice gateway every 30s.

set -euo pipefail

: "${GEMMA_VULTR_URL:?Set GEMMA_VULTR_URL in .env or export it}"
: "${NGROK_URL:=http://localhost:8000}"

while true; do
  ts=$(date +%T)

  if curl -fsS "${GEMMA_VULTR_URL}/health" > /dev/null 2>&1; then
    echo "${ts} gemma OK"
  else
    echo "${ts} GEMMA DOWN"
  fi

  if curl -fsS "${NGROK_URL}/health" > /dev/null 2>&1; then
    echo "${ts} gateway OK"
  else
    echo "${ts} GATEWAY DOWN"
  fi

  sleep 30
done
