#!/usr/bin/env bash
# Create the schema and load the sample corpus. Pass --force to wipe and reload.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || PY=".venv/Scripts/python.exe"

cd backend
"../$PY" -m app.seed --index "$@"
