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

| Type | Direction | Description |
|------|-----------|-------------|
| `COMMAND` | Client → Server | Execute shell command |
| `UPLOAD` | Client → Server | Upload file |
| `DOWNLOAD` | Client → Server | Download file |
| `PING/PONG` | Both | Health check |
| `CACHE_LOOKUP` | Client → Server | Look up command by UUID |
| `CACHE_STORE_EXEC` | Client → Server | Store command and execute |
| `CACHE_HIT` | Server → Client | Lookup found the command |
| `CACHE_MISS` | Server → Client | Lookup did not find command |

## Command Cache

The server maintains a key-value store (`~/.nlsh/command_store.db`) for cached commands. This enables:

- **Reduced data transfer**: Only UUID sent for cached commands
- **Semantic matching**: Client embeds requests, server stores by UUID
- **Future RBAC**: Access control based on command keys

The cache is used automatically when nlsh runs in remote mode.
