# nlsh-remote

Remote execution server for Natural Language Shell. Accepts WebSocket connections from nlsh clients, verifies HMAC signatures, and executes commands on the local system.

## Installation

```bash
cd packages/nlsh_remote
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

Required settings:

```bash
# Shared secret for HMAC authentication (must match client)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
NLSH_SHARED_SECRET=your_shared_secret_here

# Server binding address (0.0.0.0 for all interfaces)
NLSH_REMOTE_HOST=0.0.0.0

# Server port
NLSH_REMOTE_PORT=8765
```

### SSL/TLS Configuration (Optional)

For secure WebSocket connections (wss://), provide certificate paths:

```bash
NLSH_SSL_CERT=/path/to/cert.pem
NLSH_SSL_KEY=/path/to/key.pem
```

To generate a self-signed certificate for testing:

```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes
```

## Running the Server

### Foreground (for testing)

```bash
python server.py
```

### Background (production)

```bash
./restart.sh
```

Check status:

```bash
cat .server.pid && ps aux | grep server.py
```

View logs:

```bash
tail -f server.log
```

### Stop Server

```bash
./stop.sh
```

## Firewall Configuration

If using `ufw` on Ubuntu/Debian:

```bash
sudo ufw allow 8765/tcp
```

## Client Configuration

On the nlsh client machine, set these environment variables:

```bash
# Remote server address
NLSH_REMOTE_HOST=192.168.1.100

# Remote server port
NLSH_REMOTE_PORT=8765

# Shared secret (must match server)
NLSH_SHARED_SECRET=your_shared_secret_here

# SSL settings (if server uses HTTPS)
NLSH_SSL=true
NLSH_SSL_VERIFY=true  # Set to false for self-signed certificates
```

Then run nlsh with the `--remote` flag:

```bash
python nlshell.py --remote
```

## Protocol

The server uses WebSocket with JSON messages signed using HMAC-SHA256. Supported message types:

- `COMMAND` - Execute shell command
- `UPLOAD` - Upload file to server
- `DOWNLOAD` - Download file from server
- `PING/PONG` - Connection health check

## Security Notes

- Always use a strong, randomly generated shared secret
- Use SSL/TLS in production (especially over public networks)
- The server executes commands with the permissions of the user running it
- Consider running as a non-root user with limited permissions
- Firewall the port to trusted IP addresses only
