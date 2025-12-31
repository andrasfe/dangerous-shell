# nlsh - Natural Language Shell

An intelligent shell that translates natural language into shell commands using LLMs.

## Features

- Natural language to shell command translation
- Command confirmation before execution
- Voice input support (optional)
- Remote execution via SSH tunnel
- Local model support (LM Studio, Ollama)
- Direct mode toggle (`//`) for bypassing LLM

## Installation

```bash
cd packages/nlsh
pip install -r requirements.txt
cp .env.example .env
```

## LLM Configuration

### OpenRouter (Cloud)
```bash
OPENROUTER_API_KEY=your_api_key_here
OPENROUTER_MODEL=anthropic/claude-sonnet-4
```

### Local Model (LM Studio, Ollama)
```bash
NLSH_LOCAL_MODEL=true
NLSH_LOCAL_URL=http://localhost:1234/v1
```

## Usage

```bash
python nlshell.py
```

### Commands

| Command | Description |
|---------|-------------|
| `//` | Toggle LLM on/off (direct mode) |
| `!cmd` | Execute command directly |
| `/v` | Voice input |
| `exit` | Exit shell |

### Remote Execution

1. Start tunnel to remote server:
   ```bash
   ./tunnel.sh user@remote-host
   ```

2. Run nlsh with remote flag:
   ```bash
   python nlshell.py --remote
   ```

## Testing

```bash
python -m pytest test_nlshell.py -v
```
