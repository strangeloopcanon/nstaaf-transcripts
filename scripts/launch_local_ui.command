#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
HOST="127.0.0.1"
PORT="8501"
URL="http://$HOST:$PORT"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "NSTAAF virtualenv Python not found at:"
  echo "  $PYTHON_BIN"
  echo
  echo "From the repo root, run:"
  echo "  python -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e \".[site]\""
  echo
  read -r -p "Press Enter to close..."
  exit 1
fi

cd "$REPO_DIR" || exit 1

echo "Starting NSTAAF local UI..."
echo "Repo: $REPO_DIR"
echo "URL:  $URL"
echo
echo "This window needs to stay open while the UI is running."
echo "Press Ctrl-C here when you want to stop it."
echo

exec "$PYTHON_BIN" -m nstaaf.cli ui --host "$HOST" --port "$PORT"
