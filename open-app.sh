#!/bin/bash
# Shortcut: start the Weekly Schedule web UI locally and open it in the browser.
set -e

cd "$(dirname "$0")"

# Use the venv that has the web deps (hdubs.venv), falling back to .venv.
# Call the venv python directly — relying on PATH after `activate` is unreliable here.
if [ -x hdubs.venv/bin/python ]; then
    PY=hdubs.venv/bin/python
elif [ -x .venv/bin/python ]; then
    PY=.venv/bin/python
else
    PY=python3
fi

PORT=8077
URL="http://localhost:$PORT"

# If it's already running, just open the browser.
if curl -s -o /dev/null "$URL"; then
    echo "Already running — opening $URL"
    open "$URL"
    exit 0
fi

echo "Starting Weekly Schedule web UI on $URL ..."
# Start the server in the background
"$PY" -m uvicorn weekly_schedule.web:app --port "$PORT" --log-level warning &
SERVER_PID=$!

# Wait for it to come up, then open the browser
for _ in $(seq 1 30); do
    if curl -s -o /dev/null "$URL"; then
        break
    fi
    sleep 0.3
done
open "$URL"

echo "Server running (PID $SERVER_PID). Press Ctrl+C to stop."
wait $SERVER_PID
