#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
VOICE_PORT="${VOICE_PORT:-8002}"
RECEPTION_PORT="${RECEPTION_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-8005}"

cd "$REPO_ROOT"

if [[ -f "$VENV_DIR/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

export QWEN3_REF_AUDIO="${QWEN3_REF_AUDIO:-$REPO_ROOT/lab_voice_talk/ref_audio.WAV}"
if [[ -z "${QWEN3_REF_TEXT:-}" ]] && [[ -f "$REPO_ROOT/lab_voice_talk/ref_text.txt" ]]; then
  export QWEN3_REF_TEXT
  QWEN3_REF_TEXT="$(cat "$REPO_ROOT/lab_voice_talk/ref_text.txt")"
fi

export RECOGNITION_VOICE_TALK_NOTIFY_BASE="${RECOGNITION_VOICE_TALK_NOTIFY_BASE:-http://127.0.0.1:${VOICE_PORT}}"
export RECOGNITION_VOICE_TALK_HTTP_BASE="${RECOGNITION_VOICE_TALK_HTTP_BASE:-http://127.0.0.1:${VOICE_PORT}}"
export RECOGNITION_VOICE_TALK_WS_URL="${RECOGNITION_VOICE_TALK_WS_URL:-ws://127.0.0.1:${VOICE_PORT}/ws}"
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/ultralytics${PYTHONPATH:+:${PYTHONPATH}}"

cleanup() {
  local exit_code=$?
  if [[ -n "${VOICE_PID:-}" ]] && kill -0 "$VOICE_PID" 2>/dev/null; then
    kill "$VOICE_PID" 2>/dev/null || true
  fi
  if [[ -n "${RECEPTION_PID:-}" ]] && kill -0 "$RECEPTION_PID" 2>/dev/null; then
    kill "$RECEPTION_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  wait "${VOICE_PID:-}" 2>/dev/null || true
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

echo "[1/3] starting voice gate on port ${VOICE_PORT} ..."
PORT="$VOICE_PORT" python lab_voice_talk/recognition_gate_main.py &
VOICE_PID=$!

echo "     waiting for voice gate startup ..."
wait_for_http_ready "voice gate" "http://127.0.0.1:${VOICE_PORT}/" 240

echo "[2/3] starting recognition browser on port ${RECEPTION_PORT} ..."
PORT="$RECEPTION_PORT" python -m recognition.runpod_recognition_browser &
RECEPTION_PID=$!

echo "     waiting for vision api startup ..."
wait_for_http_ready "vision api" "http://127.0.0.1:${RECEPTION_PORT}/" 120

echo "[3/3] starting reception frontend on port ${FRONTEND_PORT} ..."
PORT="$FRONTEND_PORT" FRONTEND_PORT="$FRONTEND_PORT" python application/reception_frontend.py &
FRONTEND_PID=$!

echo
echo "Separate reception stack is running."
echo "  voice gate : http://127.0.0.1:${VOICE_PORT}"
echo "  vision api : http://127.0.0.1:${RECEPTION_PORT}"
echo "  frontend   : http://127.0.0.1:${FRONTEND_PORT}/reception"
echo

wait -n "$VOICE_PID" "$RECEPTION_PID" "$FRONTEND_PID"
