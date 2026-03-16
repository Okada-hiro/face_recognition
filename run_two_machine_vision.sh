#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
RECEPTION_PORT="${RECEPTION_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-8005}"

: "${RECOGNITION_VOICE_TALK_NOTIFY_BASE:?Set RECOGNITION_VOICE_TALK_NOTIFY_BASE to the voice machine HTTP base, e.g. https://voice-host-8002.proxy.runpod.net}"
: "${RECEPTION_BROWSER_VOICE_WS_URL:?Set RECEPTION_BROWSER_VOICE_WS_URL to the browser-facing voice websocket URL, e.g. wss://voice-host-8002.proxy.runpod.net/ws}"

cd "$REPO_ROOT"

if [[ -f "$VENV_DIR/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

export RECOGNITION_VOICE_TALK_HTTP_BASE="${RECOGNITION_VOICE_TALK_HTTP_BASE:-$RECOGNITION_VOICE_TALK_NOTIFY_BASE}"
export RECOGNITION_VOICE_TALK_WS_URL="${RECOGNITION_VOICE_TALK_WS_URL:-$RECEPTION_BROWSER_VOICE_WS_URL}"
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/ultralytics${PYTHONPATH:+:${PYTHONPATH}}"

cleanup() {
  local exit_code=$?
  if [[ -n "${RECEPTION_PID:-}" ]] && kill -0 "$RECEPTION_PID" 2>/dev/null; then
    kill "$RECEPTION_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait "${RECEPTION_PID:-}" 2>/dev/null || true
  wait "${FRONTEND_PID:-}" 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup INT TERM EXIT

wait_for_http_ready() {
  local name="$1"
  local url="$2"
  local max_wait_seconds="${3:-180}"
  local waited=0
  while (( waited < max_wait_seconds )); do
    if python3 - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=2) as resp:
    if 200 <= resp.status < 500:
        raise SystemExit(0)
raise SystemExit(1)
PY
    then
      echo "  ready: ${name} (${url})"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "  timeout waiting for ${name} (${url})" >&2
  return 1
}

echo "[1/2] starting recognition browser on port ${RECEPTION_PORT} ..."
PORT="$RECEPTION_PORT" python -m recognition.runpod_recognition_browser &
RECEPTION_PID=$!

echo "     waiting for vision api startup ..."
wait_for_http_ready "vision api" "http://127.0.0.1:${RECEPTION_PORT}/" 120

echo "[2/2] starting reception frontend on port ${FRONTEND_PORT} ..."
PORT="$FRONTEND_PORT" FRONTEND_PORT="$FRONTEND_PORT" python application/reception_frontend.py &
FRONTEND_PID=$!

echo
echo "Two-machine vision/frontend stack is running."
echo "  vision api          : http://127.0.0.1:${RECEPTION_PORT}"
echo "  frontend            : http://127.0.0.1:${FRONTEND_PORT}/app"
echo "  voice notify base   : ${RECOGNITION_VOICE_TALK_NOTIFY_BASE}"
echo "  browser voice ws    : ${RECEPTION_BROWSER_VOICE_WS_URL}"
echo

wait -n "$RECEPTION_PID" "$FRONTEND_PID"
