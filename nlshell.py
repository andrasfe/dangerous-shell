#!/usr/bin/env python3
"""
Natural Language Shell - An intelligent shell powered by LangChain DeepAgents.
Uses OpenRouter for LLM access.
"""

import os
import sys
import json
import subprocess
import readline
from pathlib import Path
from datetime import datetime
from typing import Annotated

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent

# Load environment variables
load_dotenv()

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
HISTORY_FILE = Path.home() / ".nlshell_history"
COMMAND_LOG_FILE = Path.home() / ".nlshell_command_log"
HISTORY_CONTEXT_SIZE = 20

# Global state for the shell
class ShellState:
    def __init__(self):
        self.cwd = Path.cwd()
        self.last_command = None
        self.last_output = None

shell_state = ShellState()

# System prompt for the agent
SYSTEM_PROMPT = """You are an intelligent shell assistant that helps users execute commands on their system.

Your primary function is to translate natural language requests into zsh shell commands and execute them.

## How to work:
1. When the user describes what they want to do, determine the appropriate zsh command
2. Use the `run_shell_command` tool to execute commands - it will ask the user for confirmation
3. Analyze the output and provide helpful explanations
4. If a command fails, explain what went wrong and suggest fixes

## Important rules:
- Always use the `run_shell_command` tool to execute commands - never just suggest commands without executing
- For dangerous operations (rm -rf, dd, format, etc.), warn the user in the explanation
- If the request is ambiguous, ask clarifying questions before executing
- Use the execution history to understand context (e.g., "do that again", "same but for X")
- Keep responses concise - this is a command line interface

## Context:
- Shell: zsh
- Current working directory will be provided with each command
- Execution history is available for context"""


def load_recent_history(limit: int = HISTORY_CONTEXT_SIZE) -> list[dict]:
    """Load recent command history for context."""
    history = []
    if not COMMAND_LOG_FILE.exists():
        return history

    try:
        with open(COMMAND_LOG_FILE) as f:
            lines = f.readlines()
        for line in lines[-limit:]:
            try:
                entry = json.loads(line.strip())
                history.append(entry)
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return history


def format_history_context(history: list[dict]) -> str:
    """Format execution history for context."""
    if not history:
        return "No previous commands in history."

    lines = ["Recent execution history:"]
    for entry in history[-10:]:  # Last 10 for context
        status = "OK" if entry.get("success") else "FAILED"
        lines.append(f"  [{status}] \"{entry.get('input')}\" -> {entry.get('command')}")
    return "\n".join(lines)


def log_command(natural_input: str, command: str, success: bool):
    """Log command execution for history."""
    try:
        with open(COMMAND_LOG_FILE, "a") as f:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "input": natural_input,
                "command": command,
                "cwd": str(shell_state.cwd),
                "success": success
            }
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def confirm_execution(command: str, explanation: str, warning: str = None) -> tuple[bool, str]:
    """Ask user to confirm command execution."""
    print(f"\n\033[1;36mCommand:\033[0m {command}")
    print(f"\033[1;33mExplanation:\033[0m {explanation}")

    if warning:
        print(f"\033[1;31mWarning:\033[0m {warning}")

    while True:
        response = input("\n\033[1;32mExecute? [y/n/e(dit)]:\033[0m ").strip().lower()
        if response in ("y", "yes"):
            return True, command
        elif response in ("n", "no"):
            return False, None
        elif response in ("e", "edit"):
            edited = input("\033[1;34mEdit command:\033[0m ").strip()
            if edited:
                return True, edited
            print("Empty command, cancelling.")
            return False, None
        else:
            print("Please enter 'y', 'n', or 'e'")


def run_shell_command(
    command: Annotated[str, "The zsh shell command to execute"],
    explanation: Annotated[str, "Brief explanation of what this command does"],
    warning: Annotated[str | None, "Safety warning for dangerous operations, or None"] = None,
    natural_request: Annotated[str, "The original natural language request from the user"] = "",
) -> str:
    """
    Execute a shell command after user confirmation.

    This tool executes zsh commands on the user's system. The user will be shown
    the command and asked to confirm before execution.

    Args:
        command: The zsh shell command to execute
        explanation: Brief explanation of what this command does
        warning: Safety warning for dangerous operations (rm -rf, dd, etc.)
        natural_request: The original natural language request

    Returns:
        The command output (stdout and stderr) and execution status
    """
    # Handle cd commands specially
    parts = command.strip().split()
    if parts and parts[0] == "cd":
        should_execute, final_command = confirm_execution(command, explanation, warning)
        if not should_execute:
            return "Command cancelled by user."

        try:
            if len(parts) == 1:
                new_path = Path.home()
            elif parts[1] == "~":
                new_path = Path.home()
            elif parts[1].startswith("~"):
                new_path = Path.home() / parts[1][2:]
            else:
                new_path = (shell_state.cwd / parts[1]).resolve()

            if new_path.is_dir():
                shell_state.cwd = new_path
                os.chdir(shell_state.cwd)
                log_command(natural_request, final_command, True)
                return f"Changed directory to: {shell_state.cwd}"
            else:
                return f"Directory not found: {new_path}"
        except Exception as e:
            return f"Error changing directory: {e}"

    # Confirm before execution
    should_execute, final_command = confirm_execution(command, explanation, warning)

    if not should_execute:
        return "Command cancelled by user."

    # Execute the command
    print(f"\n\033[2mExecuting...\033[0m")
    try:
        result = subprocess.run(
            final_command,
            shell=True,
            executable="/bin/zsh",
            cwd=shell_state.cwd,
            capture_output=True,
            text=True,
            timeout=300
        )

        output_parts = []
        if result.stdout:
            print(result.stdout, end="")
            output_parts.append(f"STDOUT:\n{result.stdout}")
        if result.stderr:
            print(f"\033[1;31m{result.stderr}\033[0m", end="")
            output_parts.append(f"STDERR:\n{result.stderr}")

        success = result.returncode == 0
        if success:
            print(f"\033[1;32m✓ Command completed successfully\033[0m")
        else:
            print(f"\033[1;31m✗ Command failed with exit code {result.returncode}\033[0m")

        log_command(natural_request, final_command, success)
        shell_state.last_command = final_command
        shell_state.last_output = result.stdout

        status = "SUCCESS" if success else f"FAILED (exit code {result.returncode})"
        return f"Execution {status}\n" + "\n".join(output_parts) if output_parts else f"Execution {status} (no output)"

    except subprocess.TimeoutExpired:
        log_command(natural_request, final_command, False)
        return "Command timed out after 5 minutes"
    except Exception as e:
        log_command(natural_request, final_command, False)
        return f"Error executing command: {e}"


def get_current_context() -> str:
    """Get current shell context for the agent."""
    history = load_recent_history()
    history_str = format_history_context(history)

    return f"""Current working directory: {shell_state.cwd}

{history_str}"""


# Common shell commands for detection
SHELL_COMMANDS = {
    'ls', 'cd', 'cat', 'grep', 'find', 'rm', 'cp', 'mv', 'mkdir', 'rmdir',
    'touch', 'echo', 'pwd', 'chmod', 'chown', 'ln', 'head', 'tail', 'less',
    'more', 'wc', 'sort', 'uniq', 'cut', 'sed', 'awk', 'tr', 'xargs', 'tee',
    'diff', 'tar', 'gzip', 'gunzip', 'zip', 'unzip', 'curl', 'wget', 'ssh',
    'scp', 'rsync', 'git', 'docker', 'kubectl', 'npm', 'yarn', 'pip', 'python',
    'python3', 'node', 'ruby', 'perl', 'java', 'make', 'cmake', 'gcc', 'clang',
    'ps', 'kill', 'killall', 'top', 'htop', 'df', 'du', 'free', 'uname',
    'whoami', 'which', 'whereis', 'man', 'history', 'alias', 'export', 'env',
    'source', 'eval', 'exec', 'nohup', 'sudo', 'su', 'apt', 'apt-get', 'brew',
    'yum', 'dnf', 'pacman', 'systemctl', 'journalctl', 'date', 'cal', 'sleep',
    'watch', 'time', 'timeout', 'yes', 'true', 'false', 'test', 'stat', 'file',
    'open', 'pbcopy', 'pbpaste', 'say', 'caffeinate', 'defaults', 'launchctl',
}


def looks_like_shell_command(text: str) -> bool:
    """Check if the input looks like a shell command rather than natural language."""
    text = text.strip()
    if not text:
        return False

    # Get the first word
    first_word = text.split()[0].lower()

    # Remove leading ./ or path
    if first_word.startswith('./') or first_word.startswith('/'):
        return True

    # Check if starts with a known command
    if first_word in SHELL_COMMANDS:
        return True

    # Check for shell operators (pipes, redirects, etc.)
    shell_operators = ['|', '>', '>>', '<', '&&', '||', ';', '$(', '`']
    if any(op in text for op in shell_operators):
        return True

    # Check for flags pattern (word followed by -something)
    parts = text.split()
    if len(parts) >= 2 and parts[1].startswith('-'):
        return True

    return False


class NLShell:
    def __init__(self):
        if not OPENROUTER_API_KEY:
            print("Error: OPENROUTER_API_KEY not set in .env file")
            sys.exit(1)

        # Create LLM using OpenRouter
        self.llm = ChatOpenAI(
            model=MODEL,
            openai_api_key=OPENROUTER_API_KEY,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.1,
        )

        # Create the deep agent with our shell tool
        self.agent = create_deep_agent(
            model=self.llm,
            tools=[run_shell_command],
            system_prompt=SYSTEM_PROMPT,
        )

        self._setup_readline()

    def _setup_readline(self):
        """Setup readline for input history."""
        if HISTORY_FILE.exists():
            try:
                readline.read_history_file(HISTORY_FILE)
            except Exception:
                pass
        readline.set_history_length(1000)
        readline.parse_and_bind("tab: complete")

    def _save_history(self):
        """Save readline history."""
        try:
            readline.write_history_file(HISTORY_FILE)
        except Exception:
            pass

    def print_prompt(self):
        """Print the shell prompt."""
        display_path = str(shell_state.cwd)
        home = str(Path.home())
        if display_path.startswith(home):
            display_path = "~" + display_path[len(home):]
        print(f"\n\033[1;35mnlsh\033[0m:\033[1;34m{display_path}\033[0m$ ", end="", flush=True)

    def process_input(self, user_input: str):
        """Process user input through the agent."""
        context = get_current_context()
        full_input = f"{context}\n\nUser request: {user_input}"

        try:
            result = self.agent.invoke({
                "messages": [{"role": "user", "content": full_input}]
            })

            # Get the final response
            final_message = result["messages"][-1]
            if hasattr(final_message, 'content') and final_message.content:
                # Only print if there's meaningful content (not just tool results)
                content = final_message.content.strip()
                if content and not content.startswith("Execution"):
                    print(f"\n\033[1;37m{content}\033[0m")

        except Exception as e:
            print(f"\033[1;31mError: {e}\033[0m")

    def run(self):
        """Main shell loop."""
        history_count = len(load_recent_history())
        print("\033[1;36m╔════════════════════════════════════════════╗\033[0m")
        print("\033[1;36m║   Natural Language Shell (nlsh)            ║\033[0m")
        print("\033[1;36m║   Powered by LangChain DeepAgents          ║\033[0m")
        print("\033[1;36m║   Type 'exit' or 'quit' to leave           ║\033[0m")
        print("\033[1;36m║   Type '!' prefix for direct commands      ║\033[0m")
        print("\033[1;36m║   Shell: zsh | Memory: on                  ║\033[0m")
        print(f"\033[1;36m║   Model: {MODEL[:35]:<35}║\033[0m")
        print(f"\033[1;36m║   History: {history_count} commands loaded{' ' * (27 - len(str(history_count)))}║\033[0m")
        print("\033[1;36m╚════════════════════════════════════════════╝\033[0m")

        try:
            while True:
                self.print_prompt()
                try:
                    user_input = input().strip()
                except EOFError:
                    print("\nGoodbye!")
                    break

                if not user_input:
                    continue

                # Handle exit
                if user_input.lower() in ("exit", "quit", "q"):
                    print("Goodbye!")
                    break

                # Handle direct command execution (bypass agent)
                if user_input.startswith("!"):
                    direct_cmd = user_input[1:].strip()
                    if direct_cmd:
                        result = subprocess.run(
                            direct_cmd,
                            shell=True,
                            executable="/bin/zsh",
                            cwd=shell_state.cwd,
                            capture_output=True,
                            text=True
                        )
                        if result.stdout:
                            print(result.stdout, end="")
                        if result.stderr:
                            print(f"\033[1;31m{result.stderr}\033[0m", end="")
                    continue

                # Handle built-in commands
                if user_input.lower() == "history":
                    if COMMAND_LOG_FILE.exists():
                        with open(COMMAND_LOG_FILE) as f:
                            for line in f:
                                try:
                                    entry = json.loads(line)
                                    status = "✓" if entry.get("success") else "✗"
                                    print(f"{status} {entry['input']} → {entry['command']}")
                                except:
                                    pass
                    continue

                if user_input.lower() == "clear":
                    os.system("clear")
                    continue

                # Check if input looks like a shell command
                if looks_like_shell_command(user_input):
                    print(f"\n\033[1;33mThis looks like a shell command.\033[0m")
                    response = input("\033[1;32mRun as-is? [y/n/i(nterpret)]:\033[0m ").strip().lower()
                    if response in ("y", "yes"):
                        # Run directly
                        result = subprocess.run(
                            user_input,
                            shell=True,
                            executable="/bin/zsh",
                            cwd=shell_state.cwd,
                            capture_output=True,
                            text=True
                        )
                        if result.stdout:
                            print(result.stdout, end="")
                        if result.stderr:
                            print(f"\033[1;31m{result.stderr}\033[0m", end="")
                        if result.returncode == 0:
                            print(f"\033[1;32m✓ Command completed successfully\033[0m")
                        else:
                            print(f"\033[1;31m✗ Command failed with exit code {result.returncode}\033[0m")
                        log_command(user_input, user_input, result.returncode == 0)
                        continue
                    elif response in ("n", "no"):
                        print("\033[2mCancelled.\033[0m")
                        continue
                    # else: fall through to interpret with agent

                # Process through agent
                print("\033[2m(thinking...)\033[0m")
                self.process_input(user_input)

        finally:
            self._save_history()


def main():
    shell = NLShell()
    shell.run()


if __name__ == "__main__":
    main()
