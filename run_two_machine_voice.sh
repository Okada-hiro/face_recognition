#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
VOICE_PORT="${VOICE_PORT:-8002}"
VOICE_APP_MODE="${RECOGNITION_VOICE_APP_MODE:-prod}"

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

export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/ultralytics${PYTHONPATH:+:${PYTHONPATH}}"

echo "Starting two-machine voice gate ..."
echo "  port       : ${VOICE_PORT}"
echo "  mode       : ${VOICE_APP_MODE}"
echo "  ref audio  : ${QWEN3_REF_AUDIO}"
echo

PORT="$VOICE_PORT" python lab_voice_talk/recognition_gate_main.py
