#!/usr/bin/env bash
# Run the demo scenarios against a running backend.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || PY=".venv/Scripts/python.exe"

"$PY" scripts/demo.py "$@"
