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
import base64
import tempfile
import io
import wave
from pathlib import Path
from datetime import datetime
from typing import Annotated

import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent

# Audio imports (optional - graceful fallback if not available)
try:
    import sounddevice as sd
    import numpy as np
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
VOICE_MODEL = os.getenv("OPENROUTER_VOICE_MODEL", "google/gemini-2.5-flash-lite")
SHELL_EXECUTABLE = os.getenv("NLSH_SHELL", os.getenv("SHELL", "/bin/bash"))
HISTORY_FILE = Path.home() / ".nlshell_history"
COMMAND_LOG_FILE = Path.home() / ".nlshell_command_log"
HISTORY_CONTEXT_SIZE = 20

# Audio settings
AUDIO_SAMPLE_RATE = 16000  # 16kHz for speech recognition
AUDIO_CHANNELS = 1  # Mono
AUDIO_MAX_DURATION = 30  # Max recording duration in seconds

# Global state for the shell
class ShellState:
    def __init__(self):
        self.cwd = Path.cwd()
        self.last_command = None
        self.last_output = None
        self.conversation_history = []  # Track conversation for context
        self.max_history = 20  # Keep last N exchanges

    def add_to_history(self, role: str, content: str):
        """Add a message to conversation history."""
        self.conversation_history.append({"role": role, "content": content})
        # Trim old messages if needed
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-self.max_history * 2:]

    def get_conversation_context(self) -> str:
        """Get recent conversation for context."""
        if not self.conversation_history:
            return ""

        lines = ["Recent conversation:"]
        for msg in self.conversation_history[-10:]:  # Last 10 messages
            role = "You" if msg["role"] == "assistant" else "User"
            # Truncate long messages
            content = msg["content"][:500] + "..." if len(msg["content"]) > 500 else msg["content"]
            lines.append(f"  {role}: {content}")
        return "\n".join(lines)

shell_state = ShellState()

# System prompt for the agent
SYSTEM_PROMPT = """You are an intelligent shell assistant that helps users execute commands on their system.

Your primary function is to translate natural language requests into zsh shell commands and execute them.

## Available Tools:
1. `run_shell_command` - Execute shell commands (asks user for confirmation)
2. `read_file` - Read contents of files (README, requirements.txt, setup.py, etc.)
3. `list_directory` - List files in a directory

## How to work:
1. When the user describes what they want to do, determine the appropriate action
2. Use `read_file` to examine documentation, config files, or source code when needed
3. Use `run_shell_command` to execute commands - it will ask the user for confirmation
4. Analyze the output and provide helpful explanations
5. If a command fails, explain what went wrong and suggest fixes

## Complex task workflow (e.g., "install this repo"):
1. Clone the repository using `run_shell_command`
2. Use `list_directory` to see what files exist
3. Use `read_file` to read README.md, INSTALL.md, setup.py, requirements.txt, pyproject.toml, package.json, etc.
4. Follow the installation instructions step by step, using `run_shell_command` for each step
5. Each command requires user confirmation - this is intentional for safety

## Important rules:
- Always use the tools - never just suggest commands without executing
- For dangerous operations (rm -rf, dd, format, etc.), warn the user in the explanation
- If the request is ambiguous, ask clarifying questions before executing
- Use the execution history to understand context (e.g., "do that again", "same but for X")
- Keep responses concise - this is a command line interface
- When installing projects, ALWAYS read the documentation first to understand requirements

## Context:
- Shell: {shell_name} (commands run via {shell_path})
- Current working directory will be provided with each command
- Execution history is available for context"""

def get_system_prompt() -> str:
    """Get the system prompt with current shell info."""
    shell_name = Path(SHELL_EXECUTABLE).name
    shell_path = SHELL_EXECUTABLE
    return SYSTEM_PROMPT.format(shell_name=shell_name, shell_path=shell_path)


def load_recent_history(limit: int = HISTORY_CONTEXT_SIZE) -> list[dict]:
    """Load recent command history for context."""
    history: list[dict] = []
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


def confirm_execution(command: str, explanation: str, warning: str | None = None) -> tuple[bool, str | None]:
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


def read_file(
    file_path: Annotated[str, "Path to the file to read (relative to current directory or absolute)"],
    max_lines: Annotated[int, "Maximum number of lines to read (default 200)"] = 200,
) -> str:
    """
    Read the contents of a file.

    Use this tool to read documentation (README.md, INSTALL.md), configuration files
    (requirements.txt, setup.py, pyproject.toml, package.json), or any other text file.

    Args:
        file_path: Path to the file (relative or absolute)
        max_lines: Maximum lines to read to avoid overwhelming context

    Returns:
        The file contents or an error message
    """
    try:
        # Resolve path relative to current working directory
        path = Path(file_path)
        if not path.is_absolute():
            path = shell_state.cwd / path

        if not path.exists():
            return f"Error: File not found: {path}"

        if not path.is_file():
            return f"Error: Not a file: {path}"

        # Check file size to avoid reading huge files
        size = path.stat().st_size
        if size > 1_000_000:  # 1MB limit
            return f"Error: File too large ({size} bytes). Use shell commands to inspect it."

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        if len(lines) > max_lines:
            content = ''.join(lines[:max_lines])
            return f"{content}\n\n[... truncated, showing first {max_lines} of {len(lines)} lines]"

        return ''.join(lines)

    except PermissionError:
        return f"Error: Permission denied reading {file_path}"
    except Exception as e:
        return f"Error reading file: {e}"


def list_directory(
    directory: Annotated[str, "Directory path to list (relative or absolute, defaults to current)"] = ".",
    show_hidden: Annotated[bool, "Include hidden files (starting with .)"] = False,
) -> str:
    """
    List contents of a directory.

    Use this tool to see what files exist in a directory before reading them.

    Args:
        directory: Path to list (defaults to current working directory)
        show_hidden: Whether to include hidden files

    Returns:
        List of files and directories with type indicators
    """
    try:
        path = Path(directory)
        if not path.is_absolute():
            path = shell_state.cwd / path

        if not path.exists():
            return f"Error: Directory not found: {path}"

        if not path.is_dir():
            return f"Error: Not a directory: {path}"

        entries = []
        for item in sorted(path.iterdir()):
            if not show_hidden and item.name.startswith('.'):
                continue

            if item.is_dir():
                entries.append(f"[DIR]  {item.name}/")
            elif item.is_symlink():
                entries.append(f"[LINK] {item.name} -> {item.resolve()}")
            else:
                size = item.stat().st_size
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size // 1024}KB"
                else:
                    size_str = f"{size // (1024 * 1024)}MB"
                entries.append(f"[FILE] {item.name} ({size_str})")

        if not entries:
            return f"Directory is empty: {path}"

        return f"Contents of {path}:\n" + "\n".join(entries)

    except PermissionError:
        return f"Error: Permission denied accessing {directory}"
    except Exception as e:
        return f"Error listing directory: {e}"


# Commands that may require password input - run these interactively
INTERACTIVE_COMMANDS = {'sudo', 'su', 'ssh', 'scp', 'sftp', 'passwd', 'kinit', 'docker login', 'npm login', 'gh auth'}


def requires_interactive_mode(command: str) -> bool:
    """Check if a command might require password input and should run interactively."""
    cmd_lower = command.lower().strip()

    # Check for commands that typically need passwords
    for interactive_cmd in INTERACTIVE_COMMANDS:
        if cmd_lower.startswith(interactive_cmd):
            return True

    # Check for password/passphrase prompts in piped commands
    if 'sudo ' in cmd_lower or ' sudo ' in cmd_lower:
        return True

    return False


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

    Commands requiring passwords (sudo, ssh, etc.) run interactively - the password
    goes directly to the subprocess and is NEVER captured, logged, or sent to the LLM.

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
        if not should_execute or final_command is None:
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

    if not should_execute or final_command is None:
        return "Command cancelled by user."

    # Check if command requires interactive mode (for passwords)
    if requires_interactive_mode(final_command):
        print(f"\n\033[1;35m🔒 Interactive mode: Password input goes directly to the command (not captured)\033[0m")
        print(f"\033[2mExecuting interactively...\033[0m\n")
        try:
            # Run WITHOUT capture_output so password prompts work
            # Password is NEVER seen by our code or the LLM
            result = subprocess.run(
                final_command,
                shell=True,
                executable=SHELL_EXECUTABLE,
                cwd=shell_state.cwd,
                text=True,
                timeout=600  # Longer timeout for interactive commands
            )

            if result.returncode == 0:
                print(f"\n\033[1;32m✓ Command completed successfully\033[0m")
                log_command(natural_request, final_command, True)
                return "Execution SUCCESS (interactive mode - output not captured)"
            else:
                print(f"\n\033[1;31m✗ Command failed with exit code {result.returncode}\033[0m")
                log_command(natural_request, final_command, False)
                return f"Execution FAILED (exit code {result.returncode}, interactive mode)"

        except subprocess.TimeoutExpired:
            log_command(natural_request, final_command, False)
            return "Command timed out"
        except Exception as e:
            log_command(natural_request, final_command, False)
            return f"Error executing command: {e}"

    # Execute the command with fix loop (non-interactive)
    current_cmd = final_command
    while True:
        print(f"\n\033[2mExecuting...\033[0m")
        try:
            result = subprocess.run(
                current_cmd,
                shell=True,
                executable=SHELL_EXECUTABLE,
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

            if result.returncode == 0:
                print(f"\033[1;32m✓ Command completed successfully\033[0m")
                log_command(natural_request, current_cmd, True)
                shell_state.last_command = current_cmd
                shell_state.last_output = result.stdout

                # Check for suggested next command
                full_output = result.stdout or ""
                if result.stderr:
                    full_output += "\n" + result.stderr

                suggestion = suggest_next_command(current_cmd, full_output, natural_request)
                if suggestion:
                    print(f"\n\033[1;36mSuggested next:\033[0m {suggestion['command']}")
                    print(f"\033[1;33mReason:\033[0m {suggestion['explanation']}")

                    next_response = input("\n\033[1;32mRun next command? [y/n/e(dit)]:\033[0m ").strip().lower()
                    if next_response in ("y", "yes"):
                        current_cmd = suggestion['command']
                        continue  # Run the suggested command
                    elif next_response in ("e", "edit"):
                        edited = input("\033[1;34mEdit command:\033[0m ").strip()
                        if edited:
                            current_cmd = edited
                            continue  # Run the edited command

                return f"Execution SUCCESS\n" + "\n".join(output_parts) if output_parts else "Execution SUCCESS (no output)"

            # Command failed
            print(f"\033[1;31m✗ Command failed with exit code {result.returncode}\033[0m")
            log_command(natural_request, current_cmd, False)

            # Offer to fix the command
            fix_response = input("\n\033[1;33mWould you like me to try to fix this? [y/n]:\033[0m ").strip().lower()
            if fix_response not in ("y", "yes"):
                return f"Execution FAILED (exit code {result.returncode})\n" + "\n".join(output_parts)

            print("\033[2m(analyzing error...)\033[0m")
            fix_result = fix_failed_command_standalone(current_cmd, result.stderr, result.returncode)

            if not fix_result or not fix_result.get("fixed_command"):
                print("\033[1;31mCouldn't determine a fix for this error.\033[0m")
                return f"Execution FAILED (exit code {result.returncode})\n" + "\n".join(output_parts)

            fixed_cmd = fix_result["fixed_command"]
            fix_explanation = fix_result.get("explanation", "")

            print(f"\n\033[1;36mSuggested fix:\033[0m {fixed_cmd}")
            print(f"\033[1;33mExplanation:\033[0m {fix_explanation}")

            run_fix = input("\n\033[1;32mRun fixed command? [y/n/e(dit)]:\033[0m ").strip().lower()
            if run_fix in ("y", "yes"):
                current_cmd = fixed_cmd
                continue  # Re-run with fixed command
            elif run_fix in ("e", "edit"):
                edited = input("\033[1;34mEdit command:\033[0m ").strip()
                if edited:
                    current_cmd = edited
                    continue  # Re-run with edited command

            return f"Execution FAILED (exit code {result.returncode})\n" + "\n".join(output_parts)

        except subprocess.TimeoutExpired:
            log_command(natural_request, current_cmd, False)
            return "Command timed out after 5 minutes"
        except Exception as e:
            log_command(natural_request, current_cmd, False)
            return f"Error executing command: {e}"


def get_current_context() -> str:
    """Get current shell context for the agent."""
    history = load_recent_history()
    history_str = format_history_context(history)
    conversation_str = shell_state.get_conversation_context()

    parts = [f"Current working directory: {shell_state.cwd}"]

    if conversation_str:
        parts.append(conversation_str)

    if history_str:
        parts.append(history_str)

    return "\n\n".join(parts)


# Global LLM instance for fix_failed_command (initialized in NLShell)
_llm_instance = None


def fix_failed_command_standalone(command: str, stderr: str, returncode: int) -> dict | None:
    """Use LLM to suggest a fix for a failed command."""
    if _llm_instance is None:
        return None

    fix_prompt = f"""The following shell command failed:

Command: {command}
Exit code: {returncode}
Error output:
{stderr}

Current directory: {shell_state.cwd}

Please analyze the error and provide a FIXED version of the command.
Respond with ONLY a JSON object in this format:
{{
    "fixed_command": "the corrected command",
    "explanation": "brief explanation of what was wrong and how you fixed it"
}}

If the command cannot be fixed (e.g., file doesn't exist, permission issue that can't be resolved), set fixed_command to null."""

    try:
        response = _llm_instance.invoke(fix_prompt)
        content = response.content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        return json.loads(content)
    except Exception:
        return None


def suggest_next_command(command: str, output: str, natural_request: str) -> dict | None:
    """Analyze command output and suggest a logical next command.

    Args:
        command: The command that was executed
        output: The command output (stdout + stderr)
        natural_request: The original user request

    Returns:
        Dict with 'command' and 'explanation' keys, or None if no suggestion.
    """
    if _llm_instance is None:
        return None

    # Truncate output if too long
    max_output = 2000
    if len(output) > max_output:
        output = output[:max_output] + "\n... (truncated)"

    prompt = f"""Based on this command execution, determine if there's a logical next command to suggest.

Original user request: {natural_request}
Command executed: {command}
Output:
{output}

If there's a clear, helpful next step based on the output, respond with JSON:
{{"command": "the next command", "explanation": "why this is the logical next step"}}

Only suggest a command if:
- The output clearly indicates a next step (e.g., "run npm install", compilation succeeded so run the binary, git status shows changes to commit)
- It's directly related to the user's original goal
- It's a safe, non-destructive command

If there's no clear next step or the task appears complete, respond with:
{{"command": null, "explanation": null}}

Respond ONLY with valid JSON, no other text."""

    try:
        response = _llm_instance.invoke(prompt)
        content = response.content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        result = json.loads(content)
        if result.get("command"):
            return result
        return None
    except Exception:
        return None


def record_audio() -> bytes | None:
    """Record audio from microphone until Enter is pressed.

    Returns WAV audio data as bytes, or None if recording failed.
    """
    if not AUDIO_AVAILABLE:
        print("\033[1;31mError: Audio not available. Install sounddevice and numpy.\033[0m")
        return None

    print("\033[1;35m🎤 Recording... (press Enter to stop)\033[0m")

    audio_data = []
    recording = True

    def callback(indata, frames, time, status):
        if recording:
            audio_data.append(indata.copy())

    try:
        with sd.InputStream(samplerate=AUDIO_SAMPLE_RATE, channels=AUDIO_CHANNELS,
                           dtype='int16', callback=callback):
            input()  # Wait for Enter key
            recording = False

        if not audio_data:
            print("\033[1;31mNo audio recorded.\033[0m")
            return None

        # Combine all audio chunks
        audio_array = np.concatenate(audio_data, axis=0)

        # Convert to WAV format
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(AUDIO_CHANNELS)
            wav_file.setsampwidth(2)  # 16-bit = 2 bytes
            wav_file.setframerate(AUDIO_SAMPLE_RATE)
            wav_file.writeframes(audio_array.tobytes())

        wav_buffer.seek(0)
        return wav_buffer.read()

    except Exception as e:
        print(f"\033[1;31mRecording error: {e}\033[0m")
        return None


def transcribe_audio(audio_data: bytes) -> str | None:
    """Transcribe audio using Gemini via OpenRouter.

    Args:
        audio_data: WAV audio data as bytes

    Returns:
        Transcribed text, or None if transcription failed.
    """
    # Encode audio as base64
    audio_base64 = base64.b64encode(audio_data).decode('utf-8')

    # Call OpenRouter with Gemini for transcription
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": VOICE_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Transcribe this audio exactly. Output ONLY the transcribed text, nothing else. If the audio is unclear or empty, respond with just: [unclear]"
                    },
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_base64,
                            "format": "wav"
                        }
                    }
                ]
            }
        ]
    }

    try:
        print("\033[2m(transcribing...)\033[0m")
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        transcription = result["choices"][0]["message"]["content"].strip()

        if transcription == "[unclear]" or not transcription:
            print("\033[1;33mCouldn't understand the audio.\033[0m")
            return None

        return transcription

    except requests.exceptions.RequestException as e:
        print(f"\033[1;31mTranscription error: {e}\033[0m")
        return None
    except (KeyError, IndexError) as e:
        print(f"\033[1;31mInvalid response from transcription service.\033[0m")
        return None


def looks_like_shell_command(text: str) -> bool:
    """Use LLM to check if input looks like a shell command rather than natural language."""
    text = text.strip()
    if not text:
        return False

    # Need LLM instance to check
    if _llm_instance is None:
        return False

    prompt = f"""Determine if the following input is a shell command or natural language.

Input: {text}

A shell command is something that can be directly executed in a terminal (like "ls -la", "git status", "docker ps").
Natural language is a human request describing what they want (like "show me all files", "list running containers").

Respond with ONLY "command" or "natural" (no other text)."""

    try:
        response = _llm_instance.invoke(prompt)
        answer = response.content.strip().lower()
        return answer == "command"
    except Exception:
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

        # Set global LLM instance for standalone fix function
        global _llm_instance
        _llm_instance = self.llm

        # Create the deep agent with our tools
        self.agent = create_deep_agent(
            model=self.llm,
            tools=[run_shell_command, read_file, list_directory],
            system_prompt=get_system_prompt(),
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

    def fix_failed_command(self, command: str, stderr: str, returncode: int) -> dict | None:
        """Use LLM to suggest a fix for a failed command."""
        return fix_failed_command_standalone(command, stderr, returncode)

    def print_prompt(self):
        """Print the shell prompt."""
        display_path = str(shell_state.cwd)
        home = str(Path.home())
        if display_path.startswith(home):
            display_path = "~" + display_path[len(home):]
        print(f"\n\033[1;35mnlsh\033[0m:\033[1;34m{display_path}\033[0m$ ", end="", flush=True)

    def chat(self, message: str):
        """Chat with the LLM without executing commands."""
        shell_state.add_to_history("user", message)

        context = shell_state.get_conversation_context()
        chat_prompt = f"""You are a helpful assistant in a shell environment. The user is asking a question or having a conversation - they do NOT want you to execute any commands.

Current directory: {shell_state.cwd}

{context}

User: {message}

Respond conversationally. Be concise but helpful."""

        try:
            response = self.llm.invoke(chat_prompt)
            reply = response.content if hasattr(response, 'content') else str(response)
            shell_state.add_to_history("assistant", reply)
            print(f"\n{reply}")
        except Exception as e:
            print(f"\n\033[1;31mError: {e}\033[0m")

    def process_input(self, user_input: str):
        """Process user input through the agent."""
        # Save user message to conversation history
        shell_state.add_to_history("user", user_input)

        context = get_current_context()
        full_input = f"{context}\n\nUser request: {user_input}"

        try:
            result = self.agent.invoke({
                "messages": [{"role": "user", "content": full_input}]
            })

            # Get the final response
            final_message = result["messages"][-1]
            if hasattr(final_message, 'content') and final_message.content:
                content = final_message.content.strip()

                # Save assistant response to conversation history
                shell_state.add_to_history("assistant", content)

                # Only print if there's meaningful content (not just tool results)
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
        print("\033[1;36m║   Type '?' prefix for chat (no commands)   ║\033[0m")
        print("\033[1;36m║   Type 'v' for voice input                 ║\033[0m")
        shell_name = Path(SHELL_EXECUTABLE).name
        print(f"\033[1;36m║   Shell: {shell_name:<4} | Memory: on                 ║\033[0m")
        print(f"\033[1;36m║   Model: {MODEL[:35]:<35}║\033[0m")
        if AUDIO_AVAILABLE:
            print(f"\033[1;36m║   Voice: {VOICE_MODEL[:35]:<35}║\033[0m")
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
                        if requires_interactive_mode(direct_cmd):
                            # Interactive mode - password goes directly to subprocess
                            print(f"\033[1;35m🔒 Interactive mode\033[0m")
                            subprocess.run(
                                direct_cmd,
                                shell=True,
                                executable=SHELL_EXECUTABLE,
                                cwd=shell_state.cwd
                            )
                        else:
                            result = subprocess.run(
                                direct_cmd,
                                shell=True,
                                executable=SHELL_EXECUTABLE,
                                cwd=shell_state.cwd,
                                capture_output=True,
                                text=True
                            )
                            if result.stdout:
                                print(result.stdout, end="")
                            if result.stderr:
                                print(f"\033[1;31m{result.stderr}\033[0m", end="")
                    continue

                # Handle chat mode (bypass agent, just conversation)
                if user_input.startswith("?"):
                    chat_msg = user_input[1:].strip()
                    if chat_msg:
                        self.chat(chat_msg)
                    continue

                # Handle voice input mode
                if user_input.lower() == "v":
                    if not AUDIO_AVAILABLE:
                        print("\033[1;31mVoice input not available. Install: pip install sounddevice numpy\033[0m")
                        continue

                    audio_data = record_audio()
                    if audio_data:
                        transcription = transcribe_audio(audio_data)
                        if transcription:
                            print(f"\033[1;36mYou said:\033[0m {transcription}")
                            # Process the transcribed text as normal input
                            self.process_input(transcription)
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

                # Check if input looks like a shell command (using LLM)
                if looks_like_shell_command(user_input):
                    print(f"\n\033[1;33mThis looks like a shell command.\033[0m")
                    response = input("\033[1;32mRun as-is? [y/n/i(nterpret)]:\033[0m ").strip().lower()
                    if response in ("y", "yes"):
                        # Check if interactive mode needed for passwords
                        if requires_interactive_mode(user_input):
                            print(f"\n\033[1;35m🔒 Interactive mode: Password input goes directly to the command (not captured)\033[0m\n")
                            result = subprocess.run(
                                user_input,
                                shell=True,
                                executable=SHELL_EXECUTABLE,
                                cwd=shell_state.cwd
                            )
                            if result.returncode == 0:
                                print(f"\n\033[1;32m✓ Command completed successfully\033[0m")
                                log_command(user_input, user_input, True)
                            else:
                                print(f"\n\033[1;31m✗ Command failed with exit code {result.returncode}\033[0m")
                                log_command(user_input, user_input, False)
                            continue

                        # Run directly (non-interactive)
                        current_cmd = user_input
                        while True:
                            result = subprocess.run(
                                current_cmd,
                                shell=True,
                                executable=SHELL_EXECUTABLE,
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
                                log_command(user_input, current_cmd, True)
                                break
                            else:
                                print(f"\033[1;31m✗ Command failed with exit code {result.returncode}\033[0m")
                                log_command(user_input, current_cmd, False)

                                # Offer to fix the command
                                fix_response = input("\n\033[1;33mWould you like me to try to fix this? [y/n]:\033[0m ").strip().lower()
                                if fix_response not in ("y", "yes"):
                                    break

                                print("\033[2m(analyzing error...)\033[0m")
                                fix_result = self.fix_failed_command(current_cmd, result.stderr, result.returncode)

                                if not fix_result or not fix_result.get("fixed_command"):
                                    print("\033[1;31mCouldn't determine a fix for this error.\033[0m")
                                    break

                                fixed_cmd = fix_result["fixed_command"]
                                explanation = fix_result.get("explanation", "")

                                print(f"\n\033[1;36mSuggested fix:\033[0m {fixed_cmd}")
                                print(f"\033[1;33mExplanation:\033[0m {explanation}")

                                run_fix = input("\n\033[1;32mRun fixed command? [y/n/e(dit)]:\033[0m ").strip().lower()
                                if run_fix in ("y", "yes"):
                                    current_cmd = fixed_cmd
                                    continue  # Re-run with fixed command
                                elif run_fix in ("e", "edit"):
                                    edited = input("\033[1;34mEdit command:\033[0m ").strip()
                                    if edited:
                                        current_cmd = edited
                                        continue  # Re-run with edited command
                                break
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
