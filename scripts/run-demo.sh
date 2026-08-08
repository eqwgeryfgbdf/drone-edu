#!/usr/bin/env bash
# Launch the Streamlit gesture dashboard from the project root.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Missing .venv — create it with: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [[ ! -f models/gesture_recognizer.task ]]; then
  python scripts/download-model.py
fi

exec streamlit run app.py "$@"
