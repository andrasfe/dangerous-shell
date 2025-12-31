#!/bin/bash
# SSH tunnel for nlsh-remote
# Reads config from .env file

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load .env if exists (only lines with = that don't start with #)
if [ -f "$SCRIPT_DIR/.env" ]; then
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue
        # Remove leading/trailing whitespace and export
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        [[ -n "$key" && -n "$value" ]] && export "$key=$value"
    done < "$SCRIPT_DIR/.env"
fi

USER="${NLSH_REMOTE_USER:-}"
HOST="${NLSH_REMOTE_HOST:-}"
PORT="${NLSH_REMOTE_PORT:-8765}"

if [ -z "$USER" ] || [ -z "$HOST" ]; then
    echo "Error: NLSH_REMOTE_USER and NLSH_REMOTE_HOST must be set in .env"
    echo ""
    echo "Add to .env:"
    echo "  NLSH_REMOTE_USER=your_username"
    echo "  NLSH_REMOTE_HOST=192.168.1.100"
    exit 1
fi

echo "Creating SSH tunnel..."
echo "  $USER@$HOST:$PORT -> localhost:$PORT"
echo ""
echo "Press Ctrl+C to close"
echo ""

ssh -N -L "$PORT:localhost:$PORT" "$USER@$HOST"
