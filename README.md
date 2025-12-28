# Natural Language Shell (nlsh)

An intelligent shell powered by **LangChain DeepAgents** that translates natural language into zsh commands. Uses OpenRouter for LLM access. Always confirms before executing.

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
- **DeepAgents powered** - Built on LangChain's agentic framework with planning capabilities
- **Execution memory** - Remembers past commands; understands "do that again", "same but for X"
- **Confirmation before execution** - Review, edit, or cancel commands before they run
- **Safety warnings** - Highlights dangerous operations (rm -rf, dd, etc.)
- **Persistent history** - Logs all translations for future reference
- **Direct mode** - Bypass agent with `!` prefix for regular commands
- **Configurable model** - Use any LLM available on OpenRouter

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   User Input                        │
│              "find large files"                     │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              LangChain DeepAgent                    │
│  ┌─────────────────────────────────────────────┐   │
│  │  System Prompt + Context + History          │   │
│  └─────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────┐   │
│  │  Tools: run_shell_command                   │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│            User Confirmation                        │
│  Command: find . -size +100M                        │
│  Execute? [y/n/e(dit)]                              │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│            zsh Execution                            │
│  subprocess.run(executable="/bin/zsh")              │
└─────────────────────────────────────────────────────┘
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
```

## Usage

```bash
# Using the launcher (recommended - handles venv automatically)
./nlsh

# Or run directly
python nlshell.py
```

### Example Session

```
╔════════════════════════════════════════════╗
║   Natural Language Shell (nlsh)            ║
║   Powered by LangChain DeepAgents          ║
║   Type 'exit' or 'quit' to leave           ║
║   Type '!' prefix for direct commands      ║
║   Shell: zsh | Memory: on                  ║
║   Model: anthropic/claude-3.5-sonnet       ║
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
| `history` | Show past natural language translations |
| `clear` | Clear the screen |

### Confirmation Options

When a command is suggested:
- `y` / `yes` - Execute the command
- `n` / `no` - Cancel
- `e` / `edit` - Modify the command before executing

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

## Files

| File | Location | Description |
|------|----------|-------------|
| `nlsh` | Project directory | Launcher script (handles venv) |
| `nlshell.py` | Project directory | Main application |
| `.env` | Project directory | Configuration |
| `.nlshell_history` | Home directory | Readline input history |
| `.nlshell_command_log` | Home directory | Translation log (JSON lines) |

## How It Works

1. You type a natural language request
2. The DeepAgent processes your request with execution history context
3. The agent calls the `run_shell_command` tool with the command and explanation
4. You review and confirm the command
5. The command executes via `/bin/zsh`
6. Output is displayed with success/failure status
7. The agent can analyze results and suggest follow-ups

## Dependencies

- `deepagents` - LangChain's agentic framework
- `langchain` - LLM orchestration
- `langchain-openai` - OpenAI-compatible LLM interface
- `python-dotenv` - Environment variable management

## License

MIT
