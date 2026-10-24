#!/bin/bash
# Start the agent server and the frontend.
#
# The knowledge-base MCP server is NOT started here: the agent server launches it
# as a stdio subprocess and owns its lifetime. To drive it standalone instead, use
#   mcp dev sextant/vector_db/server.py
#
# Knobs, because the defaults are right for the project and wrong for somebody:
#   PY=./.venv/bin/python   interpreter
#   HOST=127.0.0.1          interface to bind -- see the note below before changing
#   PORT=8000               agent server port (this laptop uses 8100; :8000 is
#                           another project's)
set -euo pipefail
# Job control, so each background job gets its own process group and the
# cleanup below can kill a whole tree. Without it, `kill $FRONTEND_PID` kills
# the `( cd frontend && npm run dev )` subshell and leaves npm -- and Vite
# under it -- running: found by running this script and then finding the
# grandchild still alive.
set -m

cd "$(dirname "$0")"
PY="${PY:-./.venv/bin/python}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [ ! -x "$PY" ]; then
  echo "No interpreter at $PY -- run: python3 -m venv .venv && ./.venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi

# This used to be `--host 0.0.0.0`, which binds every interface including the
# Wi-Fi one. There is no authentication in front of this process: the gate is
# Caddy's `basic_auth`, and Caddy only exists on the box. Without
# SEXTANT_PROXY_SECRET every caller resolves to `shared`, and `shared` owns the
# CLI-ingested corpus and may write it -- so anyone who could reach the port
# could read the corpus through /query (spending the Gemini key against a
# prepaid cap), and overwrite a document through /ingest. Loopback by default;
# binding wider is a thing you decide and are told about.
case "$HOST" in
  127.0.0.1|localhost|::1|'') ;;
  *) echo "NOTE: binding $HOST exposes an UNAUTHENTICATED agent server beyond" >&2
     echo "      this machine. There is no gate outside the deployed box, and" >&2
     echo "      /query spends the Gemini key. Ctrl-C now if that was a typo." >&2 ;;
esac

echo "Starting agent server on $HOST:$PORT ..."
"$PY" -m uvicorn sextant.mcp_server.main:app --host "$HOST" --port "$PORT" &
SERVER_PID=$!

echo "Starting frontend on :3000 ..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "Stopping ..."
  # The group, not the process: `-PID` is the process group `set -m` gave the
  # job. The plain form left an orphaned npm behind every time.
  kill -TERM -- "-$SERVER_PID" "-$FRONTEND_PID" 2>/dev/null || true
  kill -TERM "$SERVER_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap 'cleanup; exit 0' SIGINT SIGTERM

# Everything below the `&` used to be unconditional. Both children could die on
# their first line -- no uvicorn installed, no `dev` script -- and this printed
# four URLs, "Ctrl+C to stop", and exited 0, with the two error messages
# scrolled above the banner where they read as noise. That is `deploy.sh start`
# printing ">> up at <ip>" regardless, and `trip.sh` ending "agenticrag is
# RUNNING" with exit 0, in the one entry point the README hands a newcomer.
#
# A banner is a claim. Earn it: ask the server the question its own health
# endpoint exists to answer, and if it does not answer, say why and take the
# frontend down rather than leaving an orphan npm behind.
ready=0
for _ in $(seq 1 "${START_TRIES:-40}"); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then break; fi
  if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep "${START_SLEEP:-0.5}"
done

if [ "$ready" != 1 ]; then
  echo "" >&2
  if kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "The agent server is running but /health did not answer on" \
         "$HOST:$PORT. Look at its output above." >&2
  else
    echo "The agent server exited. Its error is above -- that is the whole" \
         "reason, not a symptom." >&2
  fi
  echo "Nothing is being served. Stopping the frontend too." >&2
  cleanup
  exit 1
fi

# The frontend is not probed, because the script cannot know which port Vite
# took -- it moves off 3000 when 3000 is busy, and its own output is the only
# authority on that. What can be checked is that it is still alive, and that
# needs a settle: the first version of this checked once, immediately after
# the API came up, and a frontend that exits in 30ms was still alive at the
# moment it was asked. A check whose answer depends on how fast the thing
# before it finished is not a check.
for _ in $(seq 1 "${FRONTEND_SETTLE_TRIES:-6}"); do
  kill -0 "$FRONTEND_PID" 2>/dev/null || break
  sleep "${START_SLEEP:-0.5}"
done
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "" >&2
  echo "The frontend exited (its error is above). The agent server is up on" \
       "$HOST:$PORT; stopping it too so nothing is left half-running." >&2
  cleanup
  exit 1
fi

cat <<INFO

  Frontend    http://localhost:3000   (Vite says otherwise if 3000 was taken)
  Agent API   http://$HOST:$PORT
  API docs    http://$HOST:$PORT/docs
  Tool list   http://$HOST:$PORT/tools

  Ctrl+C to stop.

INFO

wait
