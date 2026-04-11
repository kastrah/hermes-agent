#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Hermes Video Intel Modal Bootstrap =="
echo "Root: ${ROOT_DIR}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if ! python3 -c "import modal" >/dev/null 2>&1; then
  echo "Installing Modal SDK..."
  python3 -m pip install --upgrade modal
fi

if command -v modal >/dev/null 2>&1; then
  MODAL_CMD=(modal)
else
  MODAL_CMD=(python3 -m modal)
fi

if [[ -z "${MODAL_TOKEN_ID:-}" || -z "${MODAL_TOKEN_SECRET:-}" ]]; then
  echo "Missing MODAL_TOKEN_ID / MODAL_TOKEN_SECRET in environment."
  echo "Export both, then rerun."
  exit 2
fi

if [[ -z "${HUGGINGFACE_HUB_TOKEN:-}" ]]; then
  echo "Missing HUGGINGFACE_HUB_TOKEN in environment."
  echo "Export it, then rerun."
  exit 3
fi

"${MODAL_CMD[@]}" token set --token-id "${MODAL_TOKEN_ID}" --token-secret "${MODAL_TOKEN_SECRET}"

# Create/update Modal secret used by the worker.
"${MODAL_CMD[@]}" secret create video-intel-secrets \
  HUGGINGFACE_HUB_TOKEN="${HUGGINGFACE_HUB_TOKEN}" \
  --force

echo "Running health check..."
"${MODAL_CMD[@]}" run "${ROOT_DIR}/scripts/modal_video_intel_app.py::ping"

echo "Deploying app..."
"${MODAL_CMD[@]}" deploy "${ROOT_DIR}/scripts/modal_video_intel_app.py"

echo "Done."
