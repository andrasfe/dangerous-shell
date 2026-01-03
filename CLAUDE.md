# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

nlsh (Natural Language Shell) is a Python monorepo that translates natural language into shell commands using LLMs. It supports both local and remote execution with Ed25519 cryptographic authentication.

## Package Structure

```
packages/
├── nlsh/           # Main client - LangChain DeepAgent-powered shell
├── nlsh_mcp/       # MCP server middleware (re-signs messages)
├── nlsh_remote/    # WebSocket server for remote execution
├── shared/         # Cryptography (Ed25519, HMAC) & protocol definitions
└── skills/         # Skill plugins (loaded based on mode)
```

## Commands

### Running the Shell
```bash
# Local mode
cd packages/nlsh && ./nlsh

# Remote mode (requires tunnel first)
cd packages/nlsh && ./tunnel.sh  # Start SSH tunnel
cd packages/nlsh && ./nlsh --remote

# Non-interactive execution
python packages/nlsh/nlshell.py -c "command" --llm-off
```

### Running Tests
```bash
# All tests (95 total)
cd /Users/andraslferenczi/deleteme
.venv/bin/python -m pytest -v

# Specific package
.venv/bin/python -m pytest packages/nlsh/test_command_cache.py -v

# Type checking
.venv/bin/python -m mypy --explicit-package-bases \
  packages/nlsh/nlshell.py packages/nlsh/command_cache.py \
  packages/nlsh/embedding_client.py --ignore-missing-imports
```

### Remote Server Management
```bash
cd packages/nlsh_remote
./restart.sh   # Start/restart server (background)
./stop.sh      # Stop server
```

## Architecture

### Data Flow (Remote Mode)
```
nlsh (client) → SSH tunnel → nlsh_mcp (middleware) → SSH tunnel → nlsh_remote (server)
```

### Security Model (Chain of Trust)
- nlsh signs with `nlsh_private.key`
- nlsh_mcp verifies with `nlsh_public.key`, re-signs with `mcp_private.key`
- nlsh_remote verifies with `mcp_public.key`

Key files: `~/.nlsh/keys/{nlsh,mcp}_{private,public}.key`

### Semantic Command Cache
- Client embeds user requests using OpenRouter embeddings
- Stores in `~/.nlsh/cache/commands.db` (SQLite + numpy vectors)
- Cache hit (similarity > 0.99): Skip LLM entirely
- Near match (0.85-0.99): LLM validates before using cached command

### Protocol Messages (packages/shared/protocol.py)
All messages implement `to_payload()`/`from_payload()`:
- `COMMAND`, `UPLOAD`, `DOWNLOAD` - Operations
- `CACHE_LOOKUP`, `CACHE_STORE_EXEC`, `CACHE_HIT`, `CACHE_MISS` - Caching
- `PING`/`PONG` - Health checks

## Key Files

| File | Purpose |
|------|---------|
| `packages/nlsh/nlshell.py` | Main application (2000+ lines), DeepAgent, tools |
| `packages/nlsh/command_cache.py` | Semantic caching with embeddings |
| `packages/nlsh/memory_client.py` | Mem0 agentic memory integration |
| `packages/nlsh/remote_client.py` | Async WebSocket client |
| `packages/shared/asymmetric_crypto.py` | Ed25519 signing/verification |
| `packages/shared/protocol.py` | Message dataclasses |
| `packages/nlsh_remote/server.py` | FastAPI WebSocket server |

## Configuration

Environment variables in `.env` files:
- `OPENROUTER_API_KEY` - LLM provider
- `OPENROUTER_MODEL` - Default: anthropic/claude-3.5-sonnet
- `MEM0_MODEL` - Model for mem0 memory extraction (default: anthropic/claude-3.5-sonnet)
- `NLSH_PRIVATE_KEY_PATH` - Ed25519 key for signing
- `NLSH_REMOTE_PORT` - Default: 8765

## Session Workflow

This project uses `bd` (beads) for issue tracking. Before ending a session:
```bash
git status
git add <files>
bd sync
git commit -m "..."
bd sync
git push
```

## Shell Features

- `!command` - Execute directly (bypass LLM)
- `?message` - Chat without execution
- `//` - Toggle LLM on/off
- `/d` - Toggle danger mode (skip confirmations)
- `/ch` - Clear command history
- `/cm` - Clear mem0 conversation memory
- Confirmation options: `y`/`n`/`e(dit)`/`f(eedback)`

## Memory System (Mem0)

nlsh uses [mem0](https://github.com/mem0ai/mem0) for persistent agentic memory:
- Automatically extracts facts and preferences from conversations
- Semantic search retrieves relevant context for each query
- Falls back to simple 20-entry history if mem0 is not installed

Install mem0: `pip install mem0ai`
