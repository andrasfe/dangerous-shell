# nlsh - Natural Language Shell

An intelligent shell that translates natural language into shell commands using LLMs.

## Features

- Natural language to shell command translation
- Command confirmation with feedback option
- Remote execution via SSH tunnel
- Local model support (LM Studio, Ollama)
- Voice input (optional)
- Separate history for local and remote modes

## Installation

```bash
cd packages/nlsh
pip install -r requirements.txt
cp .env.example .env
```

## Configuration

### LLM Provider

**OpenRouter (Cloud):**
```bash
OPENROUTER_API_KEY=your_api_key_here
OPENROUTER_MODEL=anthropic/claude-sonnet-4
```

**Local Model (LM Studio, Ollama):**
```bash
NLSH_LOCAL_MODEL=true
NLSH_LOCAL_URL=http://localhost:1234/v1
NLSH_LOCAL_MODEL_NAME=local-model
```

### Remote Execution

```bash
NLSH_REMOTE_USER=your_username
NLSH_REMOTE_HOST=192.168.1.100
NLSH_REMOTE_PORT=8765
NLSH_SHARED_SECRET=your_secret
```

## Usage

```bash
python nlshell.py           # Local mode
python nlshell.py --remote  # Remote mode (run ./tunnel.sh first)
```

## Commands

| Command | Description |
|---------|-------------|
| `exit`, `quit`, `q` | Exit the shell |
| `!command` | Execute command directly (bypass LLM) |
| `?question` | Chat with LLM (no command execution) |
| `//` or `/llm` | Toggle LLM on/off (direct mode) |
| `/ch` or `/clearhistory` | Clear command history for current mode |
| `/d` or `/danger` | Toggle danger mode (skip confirmations) |
| `v` | Voice input |
| `clear` | Clear screen |

## Examples

### Natural Language Commands

```
nlsh:~$ find all python files modified today
(thinking...)

Command: find . -name "*.py" -mtime 0
Explanation: Find all Python files modified in the last 24 hours

Execute? [y/n/e(dit)/f(eedback)]: y

Executing...
./src/main.py
./tests/test_utils.py
✓ Exit code: 0
```

### Using Feedback

```
nlsh:~$ show largest file in home directory
(thinking...)

Command: find /Users/john -type f -exec du -h {} + | sort -hr | head -1
Explanation: Find the largest file in home directory

Execute? [y/n/e(dit)/f(eedback)]: f
Feedback for LLM: use $HOME instead of hardcoded path
(thinking...)

Command: find $HOME -type f -exec du -h {} + | sort -hr | head -1
Explanation: Find the largest file using $HOME variable

Execute? [y/n/e(dit)/f(eedback)]: y
```

### Remote Mode

```
nlsh[remote]:~$ change to the documents folder
(thinking...)

Command: cd ~/Documents && pwd
Explanation: Change to Documents directory and confirm location

Execute? [y/n/e(dit)/f(eedback)]: y

Executing on remote...
/home/andras/Documents
✓ Exit code: 0

nlsh[remote]:~/Documents$ list files here
(thinking...)

Command: ls -lah
Explanation: List all files with details

Execute? [y/n/e(dit)/f(eedback)]: y
```

### Direct Mode (LLM Off)

```
nlsh:~$ //
📟 LLM OFF - Direct mode

$:~$ ls -la
[executes directly without LLM]

$:~$ //
🤖 LLM ON - Natural language mode
```

### Danger Mode

```
nlsh:~$ /d
⚠️  DANGER MODE ON - Commands execute without confirmation!

nlsh:~$ list files
(thinking...)

Command: ls
Explanation: List files in current directory
(auto-executing: danger mode)

file1.txt  file2.txt

nlsh:~$ /d
✓ Safe mode - Commands require confirmation
```

## Command Confirmation Options

| Option | Description |
|--------|-------------|
| `y` | Execute the command |
| `n` | Cancel |
| `e` | Edit the command manually |
| `f` | Provide feedback to LLM to regenerate command |

## Remote Execution Setup

1. **On remote server:** Start nlsh-remote
   ```bash
   cd packages/nlsh_remote
   ./restart.sh
   ```

2. **On client:** Create SSH tunnel
   ```bash
   cd packages/nlsh
   ./tunnel.sh
   ```

3. **On client:** Run nlsh in remote mode
   ```bash
   python nlshell.py --remote
   ```

## History

- Local history: `~/.nlshell_history`
- Remote history: `~/.nlshell_history_remote`

Histories are separate so local and remote commands don't mix.

## Testing

```bash
python -m pytest test_nlshell.py -v
```
