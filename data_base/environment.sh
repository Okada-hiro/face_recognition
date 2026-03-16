#!/usr/bin/env bash
set -euo pipefail

# This script prepares a Python environment for the reception-recognition POC.
# It prefers CUDA builds when an NVIDIA GPU is visible, and falls back to CPU otherwise.
#
# Usage:
#   bash environment.sh
# Optional environment variables:
#   PYTHON_BIN=python3.10
#   VENV_DIR=.venv
#   SKIP_VENV=1
#   FORCE_CPU=1
#   TORCH_INDEX_URL=https://download.pytorch.org/whl/cu126

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
SKIP_VENV="${SKIP_VENV:-0}"
FORCE_CPU="${FORCE_CPU:-0}"

cd "$REPO_ROOT"

echo "[1/7] Checking Python version..."
"$PYTHON_BIN" - <<'PY'
import sys
major, minor = sys.version_info[:2]
if (major, minor) < (3, 10) or (major, minor) > (3, 12):
    raise SystemExit(
        f"Python {major}.{minor} is not recommended. Use Python 3.10-3.12 for this stack."
    )
print(f"Using Python {major}.{minor}")
PY

if [[ "$SKIP_VENV" != "1" ]]; then
  echo "[2/7] Creating virtual environment at $VENV_DIR ..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "[2/7] SKIP_VENV=1, using current Python environment."
fi

echo "[3/7] Upgrading pip tooling..."
python -m pip install --upgrade pip setuptools wheel

GPU_AVAILABLE=0
if [[ "$FORCE_CPU" != "1" ]] && command -v nvidia-smi >/dev/null 2>&1; then
  GPU_AVAILABLE=1
fi

if [[ "$GPU_AVAILABLE" == "1" ]]; then
  TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu126}"
  TF_SPEC="${TF_SPEC:-tensorflow[and-cuda]}"
  echo "[4/7] NVIDIA GPU detected. Installing CUDA-enabled PyTorch and TensorFlow..."
else
  TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}"
  TF_SPEC="${TF_SPEC:-tensorflow}"
  echo "[4/7] No NVIDIA GPU detected. Installing CPU builds..."
fi

python -m pip install --upgrade \
  torch torchvision torchaudio \
  --index-url "$TORCH_INDEX_URL"

echo "[5/7] Installing shared runtime dependencies..."
python -m pip install --upgrade \
  "$TF_SPEC" \
  tf-keras \
  deepface \
  opencv-python \
  numpy \
  pillow \
  matplotlib \
  pyyaml \
  requests \
  scipy \
  psutil \
  polars \
  flask \
  shapely \
  gdown

echo "[6/7] Installing local libraries from this repository..."
python -m pip install --upgrade -e "$REPO_ROOT/ultralytics"
python -m pip install --upgrade -e "$REPO_ROOT/retinaface"

echo "[7/7] Verifying key imports and accelerator visibility..."
python - <<'PY'
import os
os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

import torch
import tensorflow as tf
from deepface import DeepFace
from ultralytics import YOLO

print("torch", torch.__version__)
print("torch.cuda.is_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("torch.cuda.device_count", torch.cuda.device_count())
    print("torch.cuda.current_device", torch.cuda.current_device())
    print("torch.cuda.device_name", torch.cuda.get_device_name(torch.cuda.current_device()))

print("tensorflow", tf.__version__)
print("tensorflow.gpus", [gpu.name for gpu in tf.config.list_physical_devices("GPU")])
print("deepface", DeepFace.__name__)
print("ultralytics", YOLO.__name__)
PY

cat <<'EOF'

Environment setup finished.

Recommended run pattern:
  source .venv/bin/activate
  python -m recognition.main --device auto

Database layout:
  data_base/<person_id>/<image>.jpg

If you want CPU only:
  FORCE_CPU=1 bash environment.sh
EOF
