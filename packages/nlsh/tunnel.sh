#!/bin/bash
# SSH tunnel for nlsh-remote
# Usage: ./tunnel.sh user@remote-host

set -e

HOST="${1:-}"
PORT="${NLSH_REMOTE_PORT:-8765}"

if [ -z "$HOST" ]; then
    echo "Usage: ./tunnel.sh user@remote-host"
    echo ""
    echo "Creates SSH tunnel: localhost:$PORT -> remote:$PORT"
    echo "Then run: python nlshell.py --remote"
    exit 1
fi

echo "Creating SSH tunnel to $HOST..."
echo "  Local:  localhost:$PORT"
echo "  Remote: localhost:$PORT"
echo ""
echo "Press Ctrl+C to close tunnel"
echo ""

ssh -N -L "$PORT:localhost:$PORT" "$HOST"
