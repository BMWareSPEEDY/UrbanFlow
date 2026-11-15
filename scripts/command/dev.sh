#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-$ROOT/.venv/bin/python}"

if [[ "${1:-}" == "--vite" ]]; then
  echo "Starting Flask Command API on :8000 and Vite HMR on :5173..."
  "$PY" -m command.app &
  API_PID=$!
  trap 'kill $API_PID 2>/dev/null || true' EXIT
  cd "$ROOT/web"
  npm run dev
else
  echo "Building static UI and starting UrbanFLOW Command Center on http://127.0.0.1:8000 ..."
  (cd "$ROOT/web" && npm run build)
  exec "$PY" -m command.app
fi
