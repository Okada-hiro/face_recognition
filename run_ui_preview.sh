#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
FRONTEND_PORT="${FRONTEND_PORT:-8005}"

cd "$REPO_ROOT"

if [[ -f "$VENV_DIR/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

echo "Starting lightweight UI preview on port ${FRONTEND_PORT} ..."
echo "  open: http://127.0.0.1:${FRONTEND_PORT}/app"
echo "  mode: POST /api/preview-mode/idle|unknown|recognized"
echo

PORT="$FRONTEND_PORT" python application/reception_ui_preview.py
