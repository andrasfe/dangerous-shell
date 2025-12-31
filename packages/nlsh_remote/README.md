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

On your client machine:

1. Create SSH tunnel:
   ```bash
   ./tunnel.sh user@remote-host
   ```

2. In another terminal, run nlsh:
   ```bash
   python nlshell.py --remote
   ```

## Protocol

WebSocket with HMAC-SHA256 signed JSON messages:
- `COMMAND` - Execute shell command
- `UPLOAD` - Upload file
- `DOWNLOAD` - Download file
- `PING/PONG` - Health check
