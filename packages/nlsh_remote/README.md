# nlsh-remote

Remote execution server for Natural Language Shell.

## Security

Uses SSH tunnel for secure access (recommended). The server binds to localhost by default.

## Installation

```bash
cd packages/nlsh_remote
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

Required setting:
```bash
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
NLSH_SHARED_SECRET=your_shared_secret_here
```

## Running

```bash
./restart.sh   # Start in background
./stop.sh      # Stop server
```

Or foreground:
```bash
python server.py
```

## Client Setup

On your client machine, configure `.env`:
```bash
NLSH_REMOTE_USER=your_username
NLSH_REMOTE_HOST=192.168.1.100
NLSH_SHARED_SECRET=your_secret
```

Then:
```bash
./tunnel.sh              # Terminal 1: SSH tunnel
python nlshell.py --remote  # Terminal 2: nlsh
```

## Protocol

Communication uses WebSocket over SSH tunnel. Messages are JSON with HMAC-SHA256 signatures as an additional integrity check:
- `COMMAND` - Execute shell command
- `UPLOAD` - Upload file
- `DOWNLOAD` - Download file
- `PING/PONG` - Health check
