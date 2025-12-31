# nlsh - Natural Language Shell

An intelligent shell that translates natural language into shell commands using LLMs.

## Features

- Natural language to shell command translation
- Command confirmation before execution
- Voice input support (optional)
- Remote execution via nlsh-remote
- Local model support (LM Studio, Ollama)
- Direct mode toggle (`//`) for bypassing LLM

## Installation

```bash
cd packages/nlsh
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

### LLM Provider Options

#### Option 1: OpenRouter (Cloud)

```bash
OPENROUTER_API_KEY=your_api_key_here
OPENROUTER_MODEL=anthropic/claude-sonnet-4
```

#### Option 2: Local Model (LM Studio, Ollama)

```bash
NLSH_LOCAL_MODEL=true
NLSH_LOCAL_URL=http://localhost:1234/v1
NLSH_LOCAL_MODEL_NAME=local-model
```

For LM Studio:
1. Download and install [LM Studio](https://lmstudio.ai/)
2. Load a model (e.g., Llama, Mistral, Qwen)
3. Start the local server (default port 1234)
4. Set `NLSH_LOCAL_MODEL=true` in your `.env`

For Ollama:
```bash
NLSH_LOCAL_MODEL=true
NLSH_LOCAL_URL=http://localhost:11434/v1
NLSH_LOCAL_MODEL_NAME=llama3.2
```

### Remote Execution (Optional)

To execute commands on a remote server via nlsh-remote:

```bash
NLSH_REMOTE_HOST=192.168.1.100
NLSH_REMOTE_PORT=8765
NLSH_SHARED_SECRET=your_shared_secret_here

# SSL settings (if server uses HTTPS)
NLSH_SSL=true
NLSH_SSL_VERIFY=true  # false for self-signed certs
```

## Usage

### Basic Usage

```bash
python nlshell.py
```

### Command Line Options

```bash
python nlshell.py --remote                    # Use remote execution
python nlshell.py --dangerously-skip-permissions  # Skip confirmations (dangerous!)
```

### In-Shell Commands

| Command | Description |
|---------|-------------|
| `//` or `/llm` | Toggle LLM on/off (direct mode) |
| `!command` | Execute command directly without LLM |
| `/v` | Voice input (requires microphone) |
| `exit` or `quit` | Exit the shell |

### Examples

```
nlsh:~$ list all python files modified today
→ find . -name "*.py" -mtime 0
Execute? [Y/n]

nlsh:~$ show disk usage sorted by size
→ du -sh * | sort -hr
Execute? [Y/n]

nlsh:~$ //
📟 LLM OFF - Direct mode

nlsh:~$ ls -la
[executes directly]

nlsh:~$ //
🤖 LLM ON - Natural language mode
```

## Architecture

```
nlsh/
├── nlshell.py      # Main shell implementation
├── remote_client.py # WebSocket client for nlsh-remote
├── test_nlshell.py  # Unit tests
└── .env.example     # Configuration template
```

## Testing

```bash
python -m pytest test_nlshell.py -v
```

## Related

- [nlsh-remote](../nlsh_remote/README.md) - Remote execution server
