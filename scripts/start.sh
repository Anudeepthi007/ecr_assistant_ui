#!/usr/bin/env bash
# Start the whole stack locally (backend on :8000, frontend on :3000).
set -euo pipefail
cd "$(dirname "$0")/.."

PY=".venv/bin/python"
[ -x "$PY" ] || PY=".venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then
  echo "Creating the virtualenv..."
  python -m venv .venv
  PY=".venv/bin/python"; [ -x "$PY" ] || PY=".venv/Scripts/python.exe"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r backend/requirements.txt
fi

echo "Seeding and indexing..."
(cd backend && "../$PY" -m app.seed --index)

echo "Starting the backend on http://localhost:8000 ..."
(cd backend && "../$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

if [ -d frontend/node_modules ]; then
  echo "Starting the frontend on http://localhost:3000 ..."
  (cd frontend && yarn start)
else
  echo "frontend/node_modules is missing - run 'cd frontend && yarn install' first."
  wait $BACKEND_PID
fi
