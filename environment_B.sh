#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
SKIP_VENV="${SKIP_VENV:-0}"
WHISPER_STREAMING_DIR="${WHISPER_STREAMING_DIR:-$REPO_ROOT/whisper_streaming}"

cd "$REPO_ROOT"

echo "[1/8] Checking Python version..."
"$PYTHON_BIN" - <<'PY'
import sys
major, minor = sys.version_info[:2]
print(f"Using Python {major}.{minor}")
if (major, minor) != (3, 10):
    print(f"[WARN] Recommended Python is 3.10, current: {major}.{minor}")
PY

if [[ "$SKIP_VENV" != "1" ]]; then
  echo "[2/8] Creating virtual environment at $VENV_DIR ..."
  if [[ ! -d "$VENV_DIR" ]]; then
    if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
      echo "venv creation failed. Trying virtualenv fallback..."
      "$PYTHON_BIN" -m pip install --upgrade virtualenv
      "$PYTHON_BIN" -m virtualenv "$VENV_DIR"
    fi
  else
    echo "Using existing virtual environment: $VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "[2/8] SKIP_VENV=1, using current Python environment."
fi

if [[ ! -d "$WHISPER_STREAMING_DIR" ]]; then
  echo "[3/8] Cloning whisper_streaming into $WHISPER_STREAMING_DIR ..."
  git clone https://github.com/ufal/whisper_streaming.git "$WHISPER_STREAMING_DIR"
else
  echo "[3/8] whisper_streaming already exists: $WHISPER_STREAMING_DIR"
fi

echo "[4/8] Installing OS packages..."
apt-get update
apt-get install -y ffmpeg sox git build-essential ninja-build

echo "[5/8] Upgrading pip tooling..."
python -m pip install -U pip setuptools wheel packaging psutil ninja

echo "[6/8] Installing Torch / Whisper dependencies..."
python -m pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121
MAX_JOBS=4 python -m pip install -U flash-attn==2.8.3 --no-build-isolation
python -m pip uninstall -y ctranslate2 faster-whisper || true
python -m pip install -U ctranslate2 faster-whisper

echo "[7/8] Installing audio / web / AI dependencies..."
python -m pip install -U librosa scipy soundfile pyworld pyopenjtalk num2words pydub
python -m pip install -U fastapi "uvicorn[standard]" google-generativeai huggingface_hub loguru transformers speechbrain

echo "[8/8] Reinstalling Qwen3-TTS compatible package set..."
python -m pip uninstall -y qwen-tts faster-qwen3-tts transformers huggingface_hub speechbrain || true
python -m pip install "transformers==4.57.3" "qwen-tts==0.1.1"
python -m pip install "huggingface_hub<1.0" "speechbrain>=1.0.0"
python -m pip install faster-qwen3-tts

cat <<'EOF'

Environment setup for Machine B finished.

Recommended commands:
  source .venv/bin/activate
  export QWEN3_MODEL_PATH=Qwen/Qwen3-TTS-12Hz-1.7B-Base
  export PERM_TTS_TRIM_TAIL_SILENCE=1
  export PERM_TTS_TAIL_SILENCE_DBFS=-42
  export PERM_TTS_TAIL_SILENCE_MAX_TRIM_CHUNKS=240
  export PERM_TTS_TAIL_SILENCE_KEEP_CHUNKS=0
  export PERM_TTS_HEAD_SILENCE_MAX_DROP_CHUNKS=20
  export PERM_TTS_HEAD_SILENCE_MAX_BUFFER_CHUNKS=2
  export PERM_TTS_MAX_CHUNKS_PER_SENTENCE=24
  export PERM_TTS_SAVE_DEBUG_AUDIO=1
  export PERM_TTS_WORKER_COUNT=1
  export VOICE_PORT=8002
  bash run_two_machine_voice.sh

If you want to reuse the current environment without creating a new venv:
  SKIP_VENV=1 bash environment_B.sh
EOF
