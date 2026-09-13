#!/bin/bash
# Start the agent server and the frontend.
#
# The knowledge-base MCP server is NOT started here: the agent server launches it
# as a stdio subprocess and owns its lifetime. To drive it standalone instead, use
#   mcp dev tools/vector_db/server.py
set -euo pipefail

cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"

if [ ! -x "$PY" ]; then
  echo "No interpreter at $PY -- run: python3 -m venv .venv && ./.venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

echo "Starting agent server on :8000 ..."
"$PY" -m uvicorn mcp_server.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!

echo "Starting frontend on :3000 ..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "Stopping ..."
  kill "$SERVER_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap cleanup SIGINT SIGTERM

cat <<INFO

  Frontend    http://localhost:3000
  Agent API   http://localhost:8000
  API docs    http://localhost:8000/docs
  Tool list   http://localhost:8000/tools

  Ctrl+C to stop.

INFO

wait
