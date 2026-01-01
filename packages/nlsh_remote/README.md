# nlsh-remote

Remote execution server for Natural Language Shell.

## Security

- SSH tunnel for transport (recommended)
- Ed25519 signatures (new) or HMAC-SHA256 (legacy)
- Server binds to localhost by default

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

### Ed25519 Mode (Recommended)

```bash
NLSH_MCP_PUBLIC_KEY_PATH=~/.nlsh/keys/mcp_public.key
```

### Legacy HMAC Mode

```bash
NLSH_SHARED_SECRET=your_shared_secret_here
```

## Running

```bash
./restart.sh   # Background
./stop.sh      # Stop
python server.py  # Foreground
```

## Protocol

WebSocket over SSH tunnel. Message types:
- `COMMAND` - Execute shell command
- `UPLOAD` - Upload file
- `DOWNLOAD` - Download file
- `PING/PONG` - Health check
