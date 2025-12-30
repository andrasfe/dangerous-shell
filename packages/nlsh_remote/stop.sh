#!/bin/bash
# Stop nlsh-remote server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.server.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping server (PID: $PID)..."
        kill "$PID"
        rm -f "$PID_FILE"
        echo "Server stopped"
    else
        echo "Server not running (stale PID file)"
        rm -f "$PID_FILE"
    fi
else
    echo "No PID file found"
    # Try to kill any running instances anyway
    pkill -f "python.*server.py" 2>/dev/null && echo "Killed running server instances"
fi
