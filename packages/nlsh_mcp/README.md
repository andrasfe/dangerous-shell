# nlsh-mcp

MCP server for remote command execution via nlsh-remote.

## Installation

```bash
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

Required settings:
```bash
NLSH_MCP_PRIVATE_KEY_PATH=~/.nlsh/keys/mcp_private.key
NLSH_PUBLIC_KEY_PATH=~/.nlsh/keys/nlsh_public.key
```

## Key Generation

```bash
python -m shared.keygen mcp
```

## Running

```bash
python -m nlsh_mcp
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `nlsh_remote_execute` | Execute shell command |
| `nlsh_remote_upload` | Upload file |
| `nlsh_remote_download` | Download file |
| `nlsh_remote_cwd` | Get/set working directory |
| `nlsh_remote_status` | Connection status |
| `nlsh_remote_ping` | Health check |
