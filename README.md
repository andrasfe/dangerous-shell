# Multimodal Natural Language Shell (nlsh)

An intelligent shell powered by **LangChain DeepAgents** that translates natural language into shell commands (bash/zsh). Uses OpenRouter for LLM access. Always confirms before executing.

---

## DISCLAIMER

**THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.**

This is an experimental and potentially **DANGEROUS** tool that executes shell commands on your system. While it includes a confirmation step, you should be aware that:

- LLMs can hallucinate or misinterpret requests, potentially generating harmful commands
- A single misunderstood command could delete files, corrupt data, or damage your system
- The author(s) accept **NO RESPONSIBILITY** for any damage, data loss, or other harm caused by using this software
- **USE AT YOUR OWN RISK** - you are solely responsible for reviewing and approving every command before execution
- This tool should **NEVER** be used on production systems or with elevated privileges (sudo/root)
- Always maintain backups of important data

By using this software, you acknowledge that you understand these risks and accept full responsibility for any consequences.

---

## Features

- **Natural language input** - Describe what you want in plain English
- **Voice input** - Speak your commands using Gemini for speech-to-text
- **File reading** - Reads READMEs, configs, and docs to understand how to install/configure projects
- **Complex task handling** - Can clone repos and follow installation instructions step by step
- **DeepAgents powered** - Built on LangChain's agentic framework with planning capabilities
- **Execution memory** - Remembers past commands; understands "do that again", "same but for X"
- **Confirmation before execution** - Review, edit, or cancel commands before they run
- **Auto-fix on error** - Analyzes failures and suggests fixes
- **Smart follow-up** - Suggests logical next commands based on output
- **Secure password handling** - Passwords go directly to subprocess, never captured or sent to LLM
- **Safety warnings** - Highlights dangerous operations (rm -rf, dd, etc.)
- **Persistent history** - Arrow keys navigate command history across sessions
- **Direct mode** - Bypass agent with `!` prefix for regular commands
- **Chat mode** - Ask questions with `?` prefix without executing commands
- **Configurable model** - Use any LLM available on OpenRouter
- **Automation mode** - `--dangerously-skip-permissions` flag for scripting

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   User Input                        │
│         "install this repo: github.com/..."         │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              LangChain DeepAgent                    │
│  ┌─────────────────────────────────────────────┐   │
│  │  System Prompt + Context + History          │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────┐   │
│  │  Tools:                                     │   │
│  │   • run_shell_command (with confirmation)   │   │
│  │   • read_file (README, requirements.txt)    │   │
│  │   • list_directory                          │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────┬───────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐
   │ Read    │  │ List     │  │ Execute  │
   │ Files   │  │ Dir      │  │ Command  │
   └─────────┘  └──────────┘  └────┬─────┘
                                   │
                                   ▼
                    ┌─────────────────────────┐
                    │   User Confirmation     │
                    │   Execute? [y/n/e(dit)] │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   Shell Execution       │
                    └─────────────────────────┘
```

## Requirements

- **Python 3.11+** (required by deepagents)
- OpenRouter API key

## Installation

```bash
# Clone or download the project
cd nlshell

# Install Python 3.11+ if needed (macOS)
brew install python@3.11

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your OpenRouter API key
```

Get your API key from: https://openrouter.ai/keys

## Configuration

Edit `.env` to configure:

```bash
# Required: Your OpenRouter API key
OPENROUTER_API_KEY=sk-or-v1-xxxxx

# Optional: Model to use (see https://openrouter.ai/models)
OPENROUTER_MODEL=anthropic/claude-sonnet-4

# Optional: Voice input model for speech-to-text
OPENROUTER_VOICE_MODEL=google/gemini-2.5-flash-lite
```

## Usage

```bash
# Using the launcher (recommended - handles venv automatically)
./nlsh

# Or run directly
python nlshell.py

# Run with automation mode (skip all confirmations - DANGEROUS!)
python nlshell.py --dangerously-skip-permissions
```

### Command Line Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show help message |
| `--dangerously-skip-permissions` | Skip all confirmation prompts (for automation) |

### Example Session

```
╔════════════════════════════════════════════╗
║   Natural Language Shell (nlsh)            ║
║   Powered by LangChain DeepAgents          ║
║   Type 'exit' or 'quit' to leave           ║
║   Type '!' prefix for direct commands      ║
║   Type '?' prefix for chat (no commands)   ║
║   Type 'v' for voice input                 ║
║   Shell: zsh  | Memory: on                 ║
║   Model: anthropic/claude-sonnet-4         ║
║   Voice: google/gemini-2.5-flash-lite      ║
║   History: 15 commands loaded              ║
╚════════════════════════════════════════════╝

nlsh:~$ find all python files larger than 1MB

Command: find . -name "*.py" -size +1M
Explanation: Searches for Python files exceeding 1MB in size
Execute? [y/n/e(dit)]: y

Executing...
./data/large_dataset.py
✓ Command completed successfully

nlsh:~$ do the same but for javascript files

Command: find . -name "*.js" -size +1M
Explanation: Same search as before but for JavaScript files
Execute? [y/n/e(dit)]: y

Executing...
./dist/bundle.js
✓ Command completed successfully
```

The agent remembers your execution history, so you can use contextual references like "do that again", "same thing but for X", or "run it with different options".

### Complex Task Example: Installing a Repo

```
nlsh:~$ install the repo https://github.com/user/cool-project

(thinking...)

Command: git clone https://github.com/user/cool-project
Explanation: Clone the repository to the current directory
Execute? [y/n/e(dit)]: y

Executing...
Cloning into 'cool-project'...
✓ Command completed successfully

[Agent reads README.md and requirements.txt]

Command: cd cool-project && pip install -r requirements.txt
Explanation: Install Python dependencies listed in requirements.txt
Execute? [y/n/e(dit)]: y

Executing...
Successfully installed package1 package2...
✓ Command completed successfully

Command: pip install -e .
Explanation: Install the package in editable mode as specified in README
Execute? [y/n/e(dit)]: y
...
```

The agent reads documentation files to understand installation steps and executes them one by one, always asking for confirmation.

### Shell Command Detection

If your input looks like a shell command (e.g., `ls -la`, `git status`), the shell will ask:

```
This looks like a shell command.
Run as-is? [y/n/i(nterpret)]:
```

- `y` - Run the command directly (no LLM)
- `n` - Cancel
- `i` - Interpret with the agent (treat as natural language)

### Special Commands

| Command | Description |
|---------|-------------|
| `exit` / `quit` / `q` | Exit the shell |
| `!<command>` | Execute command directly (bypass agent) |
| `?<message>` | Chat with LLM (no command execution) |
| `v` | Voice input mode (speak your command) |
| `history` | Show past natural language translations |
| `clear` | Clear the screen |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` Up Arrow | Previous command from history |
| `↓` Down Arrow | Next command in history |
| `←` Left Arrow | Move cursor backward |
| `→` Right Arrow | Move cursor forward |
| `Tab` | Auto-complete |
| `Ctrl+C` | Cancel current input |

### Confirmation Options

When a command is suggested:
- `y` / `yes` - Execute the command
- `n` / `no` - Cancel
- `e` / `edit` - Modify the command before executing

### Voice Input

Type `v` to enter voice mode:

```
nlsh:~$ v
🎤 Recording... (press Enter to stop)

(transcribing...)
You said: list all python files in this directory

Command: find . -name "*.py" -type f
Explanation: Find all Python files in the current directory tree
Execute? [y/n/e(dit)]: y
```

Voice input uses Gemini for speech-to-text transcription via OpenRouter. The transcribed text is then processed as normal natural language input.

**Requirements:**
- `sounddevice` and `numpy` packages (included in requirements.txt)
- Working microphone
- OpenRouter API key (same as for the main LLM)

### Auto-Fix on Error

When a command fails, the shell offers to analyze and fix it:

```
nlsh:~$ gcc myprog.c

gcc: error: myprog.c: No such file or directory
✗ Command failed with exit code 1

Would you like me to try to fix this? [y/n]: y
(analyzing error...)

Suggested fix: gcc myprogram.c -o myprogram
Explanation: The file was named 'myprogram.c' not 'myprog.c', and added -o flag for output

Run fixed command? [y/n/e(dit)]: y
```

The fix loop continues until the command succeeds or you decline further fixes.

### Smart Follow-up Suggestions

After a command runs successfully, the shell analyzes the output and may suggest a logical next command:

```
nlsh:~$ git status

On branch main
Changes not staged for commit:
  modified:   nlshell.py

✓ Command completed successfully

Suggested next: git add nlshell.py
Reason: Stage the modified file for commit

Run next command? [y/n/e(dit)]: y

Executing...
✓ Command completed successfully

Suggested next: git commit -m "Update nlshell.py"
Reason: Commit the staged changes

Run next command? [y/n/e(dit)]: y
```

This creates a natural workflow where you can chain related commands together.

### Automation Mode

For scripting or automation, use the `--dangerously-skip-permissions` flag to skip all confirmation prompts:

```bash
python nlshell.py --dangerously-skip-permissions
```

**⚠️ WARNING:** This mode will:
- Auto-execute ALL commands without confirmation
- Auto-accept follow-up suggestions
- Auto-accept error fix suggestions

```
⚠️  WARNING: Running with --dangerously-skip-permissions
⚠️  All commands will be executed WITHOUT confirmation!

nlsh:~$ list files

Command: ls -la
Explanation: List all files with details
(auto-executing: --dangerously-skip-permissions)

Executing...
...
```

**Use with extreme caution.** Only use in controlled environments where you trust the input completely.

### Secure Password Handling

Commands requiring passwords run in **interactive mode**, ensuring sensitive input is never exposed to the LLM.

#### How it works

When you run a command like `sudo`, `ssh`, or `scp`, the shell:

1. Detects that the command may require a password
2. Switches to interactive mode (no output capture)
3. Runs the command with direct terminal access
4. Your password goes straight to the subprocess

```
nlsh:~$ install this package system-wide

Command: sudo pip install package
Explanation: Install package globally (requires admin privileges)
Execute? [y/n/e(dit)]: y

🔒 Interactive mode: Password input goes directly to the command (not captured)
Executing interactively...

Password: ********     ← You type this directly to sudo, not to nlsh
✓ Command completed successfully
```

#### Commands that trigger interactive mode

| Command | Why |
|---------|-----|
| `sudo` | System password |
| `su` | User password |
| `ssh`, `scp`, `sftp` | SSH password/passphrase |
| `passwd` | Password change |
| `docker login` | Registry credentials |
| `npm login` | npm credentials |
| `gh auth` | GitHub authentication |

Any command containing `sudo` (e.g., `pip install foo && sudo systemctl restart`) also triggers interactive mode.

#### Security guarantees

| Concern | Protection |
|---------|------------|
| Password captured by nlsh? | **No** - subprocess runs without output capture |
| Password logged to history? | **No** - only the command is logged, never stdin |
| Password sent to LLM? | **No** - interactive mode output is not returned to agent |
| Password visible in process list? | **No** - typed via terminal, not command args |

#### Why this matters

Normal commands capture stdout/stderr and return them to the LLM for analysis. In interactive mode:
- No output capture occurs
- The terminal is passed directly to the subprocess
- The LLM only receives "Execution SUCCESS (interactive mode)" or failure status
- Your secrets never leave your terminal

## Remote Execution (nlsh-remote)

nlsh supports remote command execution via WebSocket. This allows you to run commands on a remote server as if you were using SSH, with HMAC-SHA256 authentication for security.

### Architecture

```
┌─────────────────┐         WebSocket + HMAC         ┌─────────────────┐
│    nlsh         │ ─────────────────────────────►   │  nlsh-remote    │
│  (local client) │                                  │  (remote server)│
│                 │ ◄─────────────────────────────   │                 │
└─────────────────┘         Signed responses         └─────────────────┘
```

### Setting Up the Remote Server

1. On your remote Linux server:

```bash
cd packages/nlsh_remote

# Create .env file
cp .env.example .env

# Edit .env and set:
# NLSH_SHARED_SECRET=your_secure_shared_secret
# NLSH_REMOTE_HOST=0.0.0.0
# NLSH_REMOTE_PORT=8765

# Install dependencies
pip install -r requirements.txt

# Run the server
python server.py
```

2. Configure the client on your local machine:

```bash
# In packages/nlsh/.env or your main .env:
NLSH_REMOTE_HOST=your-server-ip
NLSH_REMOTE_PORT=8765
NLSH_SHARED_SECRET=your_secure_shared_secret  # Must match server
```

### Remote Features

The remote client (`RemoteClient` in `packages/nlsh/remote_client.py`) supports:

| Feature | Description |
|---------|-------------|
| Command execution | Run shell commands on the remote server |
| File upload | Transfer files from local to remote (like scp) |
| File download | Transfer files from remote to local |
| Binary data | Full binary support for file transfers |
| Ping/pong | Connection health checks |

### Python API Example

```python
from nlsh.remote_client import RemoteClient

async with RemoteClient(
    host="192.168.1.100",
    port=8765,
    shared_secret="your_secret"
) as client:
    # Execute a command
    result = await client.execute_command("ls -la")
    print(result.stdout)

    # Upload a file
    await client.upload_file("local.txt", "/tmp/remote.txt")

    # Download a file
    data, response = await client.download_file("/tmp/remote.txt")
```

### Security

- **HMAC-SHA256 signing**: All messages are signed with a shared secret
- **Timestamp validation**: Messages expire after 5 minutes to prevent replay attacks
- **Nonce generation**: Each message has a unique nonce

**Important:** The connection is NOT encrypted. For production use:
- Use a VPN or SSH tunnel
- Run behind a reverse proxy with TLS
- Use firewall rules to restrict access

## Project Structure

This is a monorepo containing:

```
packages/
├── nlsh/              # Natural language shell client
│   ├── remote_client.py   # Remote execution client
│   ├── requirements.txt
│   └── .env.example
├── nlsh_remote/       # Remote execution server
│   ├── server.py          # FastAPI WebSocket server
│   ├── requirements.txt
│   └── .env.example
└── shared/            # Shared code between packages
    ├── crypto.py          # HMAC signing/verification
    └── protocol.py        # Message types and serialization
```

## Files

| File | Location | Description |
|------|----------|-------------|
| `nlsh` | Project directory | Launcher script (handles venv) |
| `nlshell.py` | Project directory | Main application |
| `.env` | Project directory | Configuration |
| `.nlshell_history` | Home directory | Readline input history |
| `.nlshell_command_log` | Home directory | Translation log (JSON lines) |
| `packages/nlsh_remote/server.py` | Remote server | WebSocket server for remote execution |
| `packages/shared/crypto.py` | Shared | HMAC message signing/verification |
| `packages/shared/protocol.py` | Shared | Protocol message definitions |

## How It Works

1. You type a natural language request
2. The DeepAgent processes your request with execution history context
3. The agent calls the `run_shell_command` tool with the command and explanation
4. You review and confirm the command
5. The command executes via your shell (bash/zsh)
6. Output is displayed with success/failure status
7. The agent can analyze results and suggest follow-ups

## Dependencies

- `deepagents` - LangChain's agentic framework
- `langchain` - LLM orchestration
- `langchain-openai` - OpenAI-compatible LLM interface
- `python-dotenv` - Environment variable management
- `sounddevice` - Audio recording for voice input
- `numpy` - Audio processing
- `requests` - HTTP client for API calls

## License

MIT
