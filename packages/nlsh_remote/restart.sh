#!/bin/bash
# Restart nlsh-remote server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.server.pid"
LOG_FILE="$SCRIPT_DIR/server.log"

# Kill existing server if running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping server (PID: $OLD_PID)..."
        kill "$OLD_PID"
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Also kill any other instances
pkill -f "python.*server.py" 2>/dev/null

# Start server
echo "Starting nlsh-remote server..."
cd "$SCRIPT_DIR"

# Use venv if available
if [ -f "../../.venv/bin/python" ]; then
    PYTHON="../../.venv/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="python3"
fi

nohup $PYTHON server.py > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

sleep 1
if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
    echo "Server started (PID: $(cat $PID_FILE))"
    echo "Log: $LOG_FILE"
else
    echo "Failed to start server. Check $LOG_FILE"
    exit 1
fi
