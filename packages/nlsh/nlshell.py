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
import io
import wave
import argparse
import shlex
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Annotated, Callable, Optional

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

# Remote client import
try:
    from remote_client import RemoteClient
    import asyncio
    REMOTE_AVAILABLE = True
except ImportError:
    REMOTE_AVAILABLE = False

# Command cache import (for semantic command caching)
try:
    from command_cache import get_command_cache, CacheHit
    CACHE_AVAILABLE = True
except ImportError:
    CACHE_AVAILABLE = False

# Load environment variables
load_dotenv()

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
VOICE_MODEL = os.getenv("OPENROUTER_VOICE_MODEL", "google/gemini-2.5-flash-lite")
SHELL_EXECUTABLE = os.getenv("NLSH_SHELL", os.getenv("SHELL", "/bin/bash"))

# Local model configuration (LM Studio, Ollama, etc.)
LOCAL_MODEL = os.getenv("NLSH_LOCAL_MODEL", "false").lower() in ("true", "1", "yes")
LOCAL_MODEL_URL = os.getenv("NLSH_LOCAL_URL", "http://localhost:1234/v1")
LOCAL_MODEL_NAME = os.getenv("NLSH_LOCAL_MODEL_NAME", "local-model")
HISTORY_FILE_LOCAL = Path.home() / ".nlshell_history"
HISTORY_FILE_REMOTE = Path.home() / ".nlshell_history_remote"
COMMAND_LOG_FILE = Path.home() / ".nlshell_command_log"
HISTORY_CONTEXT_SIZE = 20

# Remote execution configuration (use SSH tunnel for security)
REMOTE_PORT = int(os.getenv("NLSH_REMOTE_PORT", "8765"))
REMOTE_PRIVATE_KEY_PATH = os.getenv("NLSH_PRIVATE_KEY_PATH", "")
REMOTE_PRIVATE_KEY = None  # Loaded at startup if --remote is used

# Audio settings
AUDIO_SAMPLE_RATE = 16000  # 16kHz for speech recognition
AUDIO_CHANNELS = 1  # Mono
AUDIO_MAX_DURATION = 30  # Max recording duration in seconds

# Runtime flags (set via command line args)
SKIP_PERMISSIONS = False  # --dangerously-skip-permissions
REMOTE_MODE = False  # --remote
DIRECT_MODE = False  # --direct (no LLM, can be toggled at runtime)

# Global remote client (initialized when --remote is used)
_remote_client = None

# Remote working directory (separate from local cwd)
_remote_cwd = None

# Global state for the shell
class ShellState:
    def __init__(self):
        self.cwd = Path.cwd()
        self.last_command = None
        self.last_output = None
        self.conversation_history = []  # Track conversation for context
        self.max_history = 20  # Keep last N exchanges
        self.skip_llm_response = False  # Flag to skip LLM after user declines action
        self.current_request = ""  # Current user request (for cache storage)

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

# Skills directory (relative to this script)
SKILLS_DIR = Path(__file__).parent.parent / "skills"

# System prompt for the agent
SYSTEM_PROMPT = """You are an intelligent shell assistant that helps users execute commands on their system.

Your primary function is to translate natural language requests into zsh shell commands and execute them.

## Available Tools:
1. `run_shell_command` - Execute shell commands (asks user for confirmation)
2. `read_file` - Read contents of files (README, requirements.txt, setup.py, etc.)
3. `list_directory` - List files in a directory
4. `upload_file` - Upload a file from LOCAL machine to REMOTE server (remote mode only)
5. `download_file` - Download a file from REMOTE server to LOCAL machine (remote mode only)

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


def load_skill(skill_name: str) -> str | None:
    """Load a skill's content from SKILL.md file.

    Args:
        skill_name: Name of the skill directory (e.g., "remote")

    Returns:
        The skill content (body only, without YAML frontmatter), or None if not found.
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        return None

    try:
        content = skill_path.read_text()
        # Strip YAML frontmatter (between --- markers)
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return content.strip()
    except Exception:
        return None


def get_system_prompt() -> str:
    """Get the system prompt with current shell info and active skills."""
    shell_name = Path(SHELL_EXECUTABLE).name
    shell_path = SHELL_EXECUTABLE
    prompt = SYSTEM_PROMPT.format(shell_name=shell_name, shell_path=shell_path)

    # Load skills based on active modes
    if REMOTE_MODE:
        remote_skill = load_skill("remote")
        if remote_skill:
            prompt += "\n\n" + remote_skill

    return prompt


def input_no_history(prompt: str = "") -> str:
    """Get input without adding to readline history."""
    # Get current history length
    hist_len = readline.get_current_history_length()
    result = input(prompt)
    # Remove any items added during this input
    new_len = readline.get_current_history_length()
    for _ in range(new_len - hist_len):
        readline.remove_history_item(new_len - 1)
        new_len -= 1
    return result


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


# ============================================================================
# Confirmation System
# ============================================================================

@dataclass
class ConfirmationResult:
    """Result of a user confirmation prompt."""
    approved: bool
    edited_values: Optional[dict] = None  # {field_name: new_value}
    feedback: Optional[str] = None

    @property
    def is_feedback(self) -> bool:
        return self.feedback is not None


def confirm_action(
    action_type: str,
    description: str,
    editable_fields: Optional[dict] = None,
    warning: Optional[str] = None,
    prompt_text: str = "Execute?",
) -> ConfirmationResult:
    """
    Generic confirmation prompt supporting edit and feedback.

    Args:
        action_type: Label for the action (e.g., "Command", "Upload", "Download")
        description: What will happen (main content to display)
        editable_fields: Dict of {label: current_value} for edit mode.
                        If None, edit returns single value in edited_values["value"]
        warning: Optional warning message
        prompt_text: The question to ask (default: "Execute?")

    Returns:
        ConfirmationResult with approval status, edited values, or feedback
    """
    print(f"\n\033[1;36m{action_type}:\033[0m {description}")

    if warning:
        print(f"\033[1;31mWarning:\033[0m {warning}")

    if SKIP_PERMISSIONS:
        print("\033[1;35m(auto-executing: --dangerously-skip-permissions)\033[0m")
        return ConfirmationResult(approved=True, edited_values=editable_fields)

    while True:
        response = input_no_history(f"\n\033[1;32m{prompt_text} [y/n/e(dit)/f(eedback)]:\033[0m ").strip().lower()

        if response in ("y", "yes"):
            return ConfirmationResult(approved=True, edited_values=editable_fields)

        elif response in ("n", "no"):
            return ConfirmationResult(approved=False)

        elif response in ("e", "edit"):
            if editable_fields is None:
                # Single value edit (for commands)
                edited = input_no_history("\033[1;34mEdit:\033[0m ").strip()
                if edited:
                    return ConfirmationResult(approved=True, edited_values={"value": edited})
                print("Empty value, cancelling.")
                return ConfirmationResult(approved=False)
            else:
                # Multi-field edit (for file transfers, etc.)
                new_values = {}
                for label, current in editable_fields.items():
                    new_val = input_no_history(f"\033[1;34m{label} [{current}]:\033[0m ").strip()
                    new_values[label] = new_val if new_val else current
                return ConfirmationResult(approved=True, edited_values=new_values)

        elif response in ("f", "feedback"):
            feedback = input_no_history("\033[1;34mFeedback for LLM:\033[0m ").strip()
            if feedback:
                return ConfirmationResult(approved=False, feedback=feedback)
            print("Empty feedback, cancelling.")
            return ConfirmationResult(approved=False)

        else:
            print("Please enter 'y', 'n', 'e', or 'f'")


def confirm_suggested_command(
    initial_cmd: str,
    initial_explanation: str,
    action_label: str,
    explanation_label: str = "Explanation",
    prompt_text: str = "Run?",
    regenerate_fn: Optional[Callable[[str, str], Optional[dict]]] = None,
    thinking_message: str = "(thinking...)",
) -> Optional[str]:
    """
    Confirm a suggested command with optional feedback-based regeneration.

    This function handles the display + confirmation loop internally,
    properly looping back to re-prompt after regeneration (fixing a bug
    where feedback would cause re-execution instead of re-confirmation).

    Args:
        initial_cmd: The initially suggested command
        initial_explanation: Why this command is suggested
        action_label: Label for the command line (e.g., "Suggested fix", "Next command")
        explanation_label: Label for explanation line (e.g., "Explanation", "Reason")
        prompt_text: The prompt question (e.g., "Run fixed command?")
        regenerate_fn: Function(prev_suggestion, feedback) -> {"command": ..., "explanation": ...}
                      The caller should capture any additional context in the closure.
        thinking_message: Message to show while regenerating

    Returns:
        The command to run (possibly edited), or None if declined.
    """
    current_cmd = initial_cmd
    current_explanation = initial_explanation

    while True:
        print(f"\n\033[1;36m{action_label}:\033[0m {current_cmd}")
        print(f"\033[1;33m{explanation_label}:\033[0m {current_explanation}")

        if SKIP_PERMISSIONS:
            print("\033[1;35m(auto-executing: --dangerously-skip-permissions)\033[0m")
            return current_cmd

        response = input_no_history(f"\n\033[1;32m{prompt_text} [y/n/e(dit)/f(eedback)]:\033[0m ").strip().lower()

        if response in ("y", "yes"):
            return current_cmd
        elif response in ("n", "no"):
            return None
        elif response in ("e", "edit"):
            edited = input_no_history("\033[1;34mEdit command:\033[0m ").strip()
            if edited:
                return edited
            # Empty edit -> loop back to prompt
        elif response in ("f", "feedback"):
            if regenerate_fn is None:
                continue
            feedback = input_no_history("\033[1;34mFeedback for LLM:\033[0m ").strip()
            if feedback:
                print(f"\033[2m{thinking_message}\033[0m")
                new_result = regenerate_fn(current_cmd, feedback)
                if new_result and new_result.get("command"):
                    current_cmd = new_result["command"]
                    current_explanation = new_result.get("explanation", "")
            # Loop back to display + prompt with new (or same) suggestion
        # For any other response, loop back to prompt


def confirm_execution(command: str, explanation: str, warning: str | None = None) -> tuple[bool | str, str | None]:
    """Ask user to confirm command execution.

    Uses confirm_action() internally but maintains backward-compatible return type.

    Returns:
        Tuple of (approved, value) where:
        - (True, command) if approved (possibly edited)
        - (False, None) if cancelled
        - ("feedback", feedback_text) if user provided feedback
    """
    # Display explanation separately (confirm_action only shows one line)
    print(f"\033[1;33mExplanation:\033[0m {explanation}")

    result = confirm_action(
        action_type="Command",
        description=command,
        editable_fields=None,  # Single value edit mode
        warning=warning,
    )

    if result.is_feedback:
        return "feedback", result.feedback
    elif result.approved:
        # Return edited command if user edited, otherwise original
        if result.edited_values and "value" in result.edited_values:
            return True, result.edited_values["value"]
        return True, command
    else:
        return False, None


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


def upload_file(
    local_path: Annotated[str, "Path to the LOCAL file to upload (on your machine, not the remote server)"],
    remote_path: Annotated[str, "Destination path on the REMOTE server"],
    mode: Annotated[str, "Unix file permissions (e.g., '0644' for rw-r--r--, '0755' for executable)"] = "0644",
) -> str:
    """
    Upload a file from the LOCAL machine to the REMOTE server.

    IMPORTANT: In remote mode, run_shell_command executes on the REMOTE server.
    To transfer files FROM your local machine TO the remote, use this tool instead of scp/rsync.

    Args:
        local_path: Path on YOUR LOCAL machine (e.g., ~/.nlsh/keys/mcp_public.key)
        remote_path: Destination path on the REMOTE server (e.g., ~/.nlsh/keys/mcp_public.key)
        mode: Unix permissions for the uploaded file

    Returns:
        Success message or error
    """
    if not REMOTE_MODE:
        return "Error: upload_file is only available in remote mode (--remote)"

    if not REMOTE_AVAILABLE or _remote_client is None:
        return "Error: Remote client not available"

    # Confirm before upload
    result = confirm_action(
        action_type="Upload",
        description=f"{local_path} -> {remote_path}",
        editable_fields={"Local path": local_path, "Remote path": remote_path},
    )

    if result.is_feedback:
        return f"User feedback on upload '{local_path}' -> '{remote_path}': {result.feedback}. Please adjust the file transfer based on this feedback."
    if not result.approved:
        return "Upload cancelled by user."

    # Use edited paths if provided
    if result.edited_values:
        local_path = result.edited_values.get("Local path", local_path)
        remote_path = result.edited_values.get("Remote path", remote_path)

    async def _upload():
        async with RemoteClient(
            host="127.0.0.1",
            port=REMOTE_PORT,
            private_key=REMOTE_PRIVATE_KEY
        ) as client:
            result = await client.upload_file(local_path, remote_path, mode)
            return result

    try:
        result = asyncio.run(_upload())
        if result.success:
            return f"Successfully uploaded {local_path} to {remote_path} ({result.bytes_written} bytes)"
        else:
            return f"Upload failed: {result.message}"
    except FileNotFoundError:
        return f"Error: Local file not found: {local_path}"
    except Exception as e:
        return f"Error uploading file: {e}"


def download_file(
    remote_path: Annotated[str, "Path to the file on the REMOTE server"],
    local_path: Annotated[str, "Destination path on your LOCAL machine"],
) -> str:
    """
    Download a file from the REMOTE server to the LOCAL machine.

    IMPORTANT: In remote mode, run_shell_command executes on the REMOTE server.
    To transfer files FROM the remote TO your local machine, use this tool instead of scp/rsync.

    Args:
        remote_path: Path on the REMOTE server (e.g., /var/log/app.log)
        local_path: Destination path on YOUR LOCAL machine (e.g., ./app.log)

    Returns:
        Success message or error
    """
    if not REMOTE_MODE:
        return "Error: download_file is only available in remote mode (--remote)"

    if not REMOTE_AVAILABLE or _remote_client is None:
        return "Error: Remote client not available"

    # Confirm before download
    result = confirm_action(
        action_type="Download",
        description=f"{remote_path} -> {local_path}",
        editable_fields={"Remote path": remote_path, "Local path": local_path},
    )

    if result.is_feedback:
        return f"User feedback on download '{remote_path}' -> '{local_path}': {result.feedback}. Please adjust the file transfer based on this feedback."
    if not result.approved:
        return "Download cancelled by user."

    # Use edited paths if provided
    if result.edited_values:
        remote_path = result.edited_values.get("Remote path", remote_path)
        local_path = result.edited_values.get("Local path", local_path)

    async def _download():
        async with RemoteClient(
            host="127.0.0.1",
            port=REMOTE_PORT,
            private_key=REMOTE_PRIVATE_KEY
        ) as client:
            data, result = await client.download_file(remote_path, local_path)
            return result

    try:
        result = asyncio.run(_download())
        if result.success:
            return f"Successfully downloaded {remote_path} to {local_path} ({result.size} bytes)"
        else:
            return f"Download failed: {result.message}"
    except Exception as e:
        return f"Error downloading file: {e}"


# Commands that may require password input - run these interactively
INTERACTIVE_COMMANDS = {'sudo', 'su', 'ssh', 'scp', 'sftp', 'passwd', 'kinit', 'docker login', 'npm login', 'gh auth'}

# Error patterns in stderr that indicate failure even with exit code 0
ERROR_PATTERNS = [
    'error:',
    'Error:',
    'ERROR:',
    'unknown primary',
    'unknown option',
    'invalid option',
    'not found',
    'No such file',
    'Permission denied',
    'cannot ',
    'failed to ',
    'fatal:',
    'FATAL:',
]


def has_stderr_errors(stderr: str) -> bool:
    """Check if stderr contains error patterns indicating command failure.

    Some commands exit with code 0 even when they encounter errors
    (e.g., BSD find with invalid options). This function detects such cases.
    """
    if not stderr:
        return False
    stderr_lower = stderr.lower()
    for pattern in ERROR_PATTERNS:
        if pattern.lower() in stderr_lower:
            return True
    return False


def execute_remote_command(command: str, cwd: str | None = None) -> tuple[bool, str, str, int]:
    """Execute a command on the remote server.

    Args:
        command: The command to execute
        cwd: Working directory (optional)

    Returns:
        Tuple of (success, stdout, stderr, returncode)
    """
    if not REMOTE_AVAILABLE or _remote_client is None:
        return False, "", "Remote client not available", -1

    async def _run():
        async with RemoteClient(
            host="127.0.0.1",  # Always localhost (through SSH tunnel)
            port=REMOTE_PORT,
            private_key=REMOTE_PRIVATE_KEY
        ) as client:
            result = await client.execute_command(command, cwd=cwd)
            return result.success, result.stdout, result.stderr, result.returncode

    try:
        return asyncio.run(_run())
    except Exception as e:
        return False, "", str(e), -1


def validate_cached_command(natural_request: str, cached_command: str, cached_description: str) -> bool:
    """Use LLM to validate if a cached command is appropriate for the current request.

    Args:
        natural_request: The user's original request.
        cached_command: The cached command being considered.
        cached_description: Description of what the cached command does.

    Returns:
        True if the cached command is appropriate, False otherwise.
    """
    if _llm_instance is None:
        return False

    prompt = f"""Is this cached command appropriate for the user's current request?

User request: {natural_request}
Cached command: {cached_command}
Command description: {cached_description}

Consider:
- Does the cached command accomplish what the user is asking for?
- Are there any important differences in context or parameters?

Answer with ONLY "yes" or "no"."""

    try:
        response = _llm_instance.invoke(prompt)
        answer = response.content.strip().lower()
        return answer == "yes"
    except Exception:
        return False


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
    global _remote_cwd
    try:
        parts = shlex.split(command.strip())
    except ValueError:
        parts = command.strip().split()
    if parts and parts[0] == "cd":
        should_execute, final_command = confirm_execution(command, explanation, warning)
        if should_execute == "feedback":
            return f"User feedback on command '{command}': {final_command}. Please generate a new command based on this feedback."
        if not should_execute or final_command is None:
            return "Command cancelled by user."

        if REMOTE_MODE:
            # Handle cd on remote server
            try:
                # Get the target path
                if len(parts) == 1:
                    target = "~"
                else:
                    target = parts[1]

                # Quote the target for shell execution (but not ~ which needs expansion)
                if target == "~" or target.startswith("~/"):
                    shell_target = target  # Let shell expand ~
                else:
                    shell_target = shlex.quote(target)
                # Check if directory exists on remote and get its absolute path
                success, stdout, stderr, returncode = execute_remote_command(
                    f'cd {shell_target} && pwd',
                    cwd=_remote_cwd
                )
                if success:
                    _remote_cwd = stdout.strip()
                    log_command(natural_request, final_command, True)
                    return f"Changed remote directory to: {_remote_cwd}"
                else:
                    return f"Remote directory not found: {target}"
            except Exception as e:
                return f"Error changing remote directory: {e}"
        else:
            # Handle cd locally
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

    if should_execute == "feedback":
        # User provided feedback - return it so LLM can regenerate
        return f"User feedback on command '{command}': {final_command}. Please generate a new command based on this feedback."

    if not should_execute or final_command is None:
        return "Command cancelled by user."

    # Check if command requires interactive mode (for passwords) - not supported in remote mode
    if requires_interactive_mode(final_command) and not REMOTE_MODE:
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

    # Execute the command with fix loop
    current_cmd = final_command
    while True:
        if REMOTE_MODE:
            print(f"\n\033[2mExecuting on remote...\033[0m")
        else:
            print(f"\n\033[2mExecuting...\033[0m")
        try:
            # Execute locally or remotely based on mode
            if REMOTE_MODE:
                success, stdout, stderr, returncode = execute_remote_command(
                    current_cmd,
                    cwd=_remote_cwd  # Use remote cwd, not local
                )
            else:
                proc_result = subprocess.run(
                    current_cmd,
                    shell=True,
                    executable=SHELL_EXECUTABLE,
                    cwd=shell_state.cwd,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                success = proc_result.returncode == 0
                stdout = proc_result.stdout
                stderr = proc_result.stderr
                returncode = proc_result.returncode

            output_parts = []
            if stdout:
                print(stdout, end="")
                output_parts.append(f"STDOUT:\n{stdout}")
            if stderr:
                print(f"\033[1;31m{stderr}\033[0m", end="")
                output_parts.append(f"STDERR:\n{stderr}")

            # Check for success - exit code 0 AND no error patterns in stderr
            stderr_has_errors = has_stderr_errors(stderr)
            if returncode == 0 and not stderr_has_errors:
                print(f"\033[1;32m✓ Command completed successfully\033[0m")
                log_command(natural_request, current_cmd, True)
                shell_state.last_command = current_cmd
                shell_state.last_output = stdout

                # Store in cache for future use (remote mode only)
                # Use shell_state.current_request as fallback if LLM didn't pass natural_request
                cache_request = natural_request or shell_state.current_request
                if REMOTE_MODE and CACHE_AVAILABLE and cache_request:
                    try:
                        cache = get_command_cache()
                        cache.store(current_cmd, explanation, cache_request)
                        print(f"\033[2m(cached for future use)\033[0m")
                    except Exception as e:
                        print(f"\033[2m(cache store error: {e})\033[0m")

                # Check for suggested next command
                full_output = stdout or ""
                if stderr:
                    full_output += "\n" + stderr

                suggestion = suggest_next_command(current_cmd, full_output, natural_request)
                if suggestion:
                    # Create regenerate function with captured context
                    def regenerate_next(prev_suggestion: str, feedback: str) -> Optional[dict]:
                        return suggest_next_command(
                            current_cmd,
                            f"{full_output}\nPrevious suggestion: {prev_suggestion}\nUser feedback: {feedback}",
                            natural_request
                        )

                    next_cmd = confirm_suggested_command(
                        initial_cmd=suggestion['command'],
                        initial_explanation=suggestion['explanation'],
                        action_label="Suggested next",
                        explanation_label="Reason",
                        prompt_text="Run next command?",
                        regenerate_fn=regenerate_next,
                        thinking_message="(thinking...)",
                    )
                    if next_cmd:
                        current_cmd = next_cmd
                        continue  # Run the suggested/edited command
                    else:
                        # User declined suggested next command - stop here
                        shell_state.skip_llm_response = True
                        return "Command executed successfully. User declined follow-up. Do NOT suggest any more commands - wait for new user input."

                return f"Execution SUCCESS\n" + "\n".join(output_parts) if output_parts else "Execution SUCCESS (no output)"

            # Command failed
            print(f"\033[1;31m✗ Command failed with exit code {returncode}\033[0m")
            log_command(natural_request, current_cmd, False)

            # Offer to fix the command
            if SKIP_PERMISSIONS:
                fix_response = "y"
            else:
                fix_response = input_no_history("\n\033[1;33mWould you like me to try to fix this? [y/n]:\033[0m ").strip().lower()
            if fix_response not in ("y", "yes"):
                shell_state.skip_llm_response = True
                return "Command failed. User declined fix. Do NOT suggest any more commands - wait for new user input."

            print("\033[2m(analyzing error...)\033[0m")
            fix_result = fix_failed_command_standalone(current_cmd, stderr, returncode)

            if not fix_result or not fix_result.get("fixed_command"):
                print("\033[1;31mCouldn't determine a fix for this error.\033[0m")
                return f"Execution FAILED (exit code {returncode})\n" + "\n".join(output_parts)

            fixed_cmd = fix_result["fixed_command"]
            fix_explanation = fix_result.get("explanation", "")

            # Create regenerate function with captured context
            def regenerate_fix(prev_suggestion: str, feedback: str) -> Optional[dict]:
                return fix_failed_command_standalone(
                    current_cmd,
                    f"{stderr}\nPrevious fix suggestion: {prev_suggestion}\nUser feedback: {feedback}",
                    returncode
                )

            approved_cmd = confirm_suggested_command(
                initial_cmd=fixed_cmd,
                initial_explanation=fix_explanation,
                action_label="Suggested fix",
                explanation_label="Explanation",
                prompt_text="Run fixed command?",
                regenerate_fn=regenerate_fix,
                thinking_message="(analyzing error...)",
            )
            if approved_cmd:
                current_cmd = approved_cmd
                continue  # Re-run with fixed/edited command

            # User declined the fix suggestion
            shell_state.skip_llm_response = True
            return "Command failed. User declined fix. Do NOT suggest any more commands - wait for new user input."

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

IMPORTANT: If the error output contains "User feedback:", this is direct input from the user correcting or guiding your fix. You MUST incorporate this feedback into your new suggestion. The user's feedback takes priority over your previous analysis.

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

IMPORTANT: If the output contains "User feedback:", this is direct input from the user correcting or guiding your suggestion. You MUST incorporate this feedback into your new suggestion. The user's feedback takes priority over your previous analysis.

If there's a clear, helpful next step based on the output (and user feedback if present), respond with JSON:
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

    def callback(indata, _frames, _time, _status):
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
        self.llm = None
        self.agent = None

        # Create LLM - either local or OpenRouter
        if LOCAL_MODEL:
            print(f"\033[1;35m🏠 Using local model: {LOCAL_MODEL_URL}\033[0m")
            self.llm = ChatOpenAI(
                model=LOCAL_MODEL_NAME,
                openai_api_key="not-needed",  # LM Studio doesn't require API key
                openai_api_base=LOCAL_MODEL_URL,
                temperature=0.1,
            )
        else:
            if not OPENROUTER_API_KEY:
                print("Error: OPENROUTER_API_KEY not set in .env file")
                print("       Or set NLSH_LOCAL_MODEL=true to use a local model")
                sys.exit(1)

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
            tools=[run_shell_command, read_file, list_directory, upload_file, download_file],
            system_prompt=get_system_prompt(),
        )

        self._setup_readline()

    def _get_history_file(self) -> Path:
        """Get the appropriate history file based on mode."""
        return HISTORY_FILE_REMOTE if REMOTE_MODE else HISTORY_FILE_LOCAL

    def _setup_readline(self):
        """Setup readline for input history."""
        history_file = self._get_history_file()
        if history_file.exists():
            try:
                readline.read_history_file(history_file)
            except Exception:
                pass
        readline.set_history_length(1000)
        readline.parse_and_bind("tab: complete")

    def _save_history(self):
        """Save readline history."""
        try:
            readline.write_history_file(self._get_history_file())
        except Exception:
            pass

    def _execute_direct(self, command: str):
        """Execute a command directly without LLM."""
        global _remote_cwd
        print(f"\033[2m→ direct\033[0m")

        # Handle cd specially - use shlex to handle quoted paths and escaped spaces
        try:
            parts = shlex.split(command.strip())
        except ValueError:
            parts = command.strip().split()
        if parts and parts[0] == "cd":
            if REMOTE_MODE:
                target = parts[1] if len(parts) > 1 else "~"
                # Quote the target for shell execution (but not ~ which needs expansion)
                if target == "~" or target.startswith("~/"):
                    shell_target = target  # Let shell expand ~
                else:
                    shell_target = shlex.quote(target)
                success, stdout, stderr, returncode = execute_remote_command(
                    f'cd {shell_target} && pwd',
                    cwd=_remote_cwd
                )
                if success:
                    _remote_cwd = stdout.strip()
                    print(f"Changed remote directory to: {_remote_cwd}")
                else:
                    print(f"\033[1;31mDirectory not found: {target}\033[0m")
            else:
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
                        print(f"Changed directory to: {shell_state.cwd}")
                    else:
                        print(f"\033[1;31mDirectory not found: {new_path}\033[0m")
                except Exception as e:
                    print(f"\033[1;31mError: {e}\033[0m")
            return

        # Execute command
        if REMOTE_MODE:
            success, stdout, stderr, returncode = execute_remote_command(
                command,
                cwd=_remote_cwd
            )
            if stdout:
                print(stdout, end="")
            if stderr:
                print(f"\033[1;31m{stderr}\033[0m", end="")
            if returncode != 0:
                print(f"\033[1;31m✗ Exit code: {returncode}\033[0m")
        else:
            if requires_interactive_mode(command):
                subprocess.run(
                    command,
                    shell=True,
                    executable=SHELL_EXECUTABLE,
                    cwd=shell_state.cwd
                )
            else:
                result = subprocess.run(
                    command,
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
                if result.returncode != 0:
                    print(f"\033[1;31m✗ Exit code: {result.returncode}\033[0m")

    def fix_failed_command(self, command: str, stderr: str, returncode: int) -> dict | None:
        """Use LLM to suggest a fix for a failed command."""
        return fix_failed_command_standalone(command, stderr, returncode)

    def get_prompt(self) -> str:
        """Get the shell prompt string with readline-safe ANSI codes."""
        # Wrap ANSI codes in \001 and \002 so readline can track cursor position
        def rl_color(code: str) -> str:
            return f"\x01{code}\x02"

        BOLD_YELLOW = rl_color("\033[1;33m")
        BOLD_MAGENTA = rl_color("\033[1;35m")
        BOLD_BLUE = rl_color("\033[1;34m")
        RESET = rl_color("\033[0m")

        if REMOTE_MODE:
            display_path = _remote_cwd if _remote_cwd else "~"
            if DIRECT_MODE:
                return f"{BOLD_YELLOW}${RESET}[{BOLD_MAGENTA}remote{RESET}]:{BOLD_BLUE}{display_path}{RESET}$ "
            else:
                return f"{BOLD_MAGENTA}nlsh{RESET}[{BOLD_YELLOW}remote{RESET}]:{BOLD_BLUE}{display_path}{RESET}$ "
        else:
            display_path = str(shell_state.cwd)
            home = str(Path.home())
            if display_path.startswith(home):
                display_path = "~" + display_path[len(home):]
            if DIRECT_MODE:
                return f"{BOLD_YELLOW}${RESET}:{BOLD_BLUE}{display_path}{RESET}$ "
            else:
                return f"{BOLD_MAGENTA}nlsh{RESET}:{BOLD_BLUE}{display_path}{RESET}$ "

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

    def _execute_cached_command(self, cache_hit: "CacheHit", user_input: str) -> bool:
        """Execute a cached command (skipping LLM).

        Args:
            cache_hit: The cache hit with command and explanation.
            user_input: Original user request (for logging).

        Returns:
            True if command was executed, False if user cancelled.
        """
        global _remote_cwd

        # Show the cached command
        print(f"\033[2m⚡ cached\033[0m")
        print(f"\n\033[1;33mCommand:\033[0m {cache_hit.command}")
        print(f"\033[2mExplanation: {cache_hit.explanation}\033[0m")

        # Ask for confirmation
        if SKIP_PERMISSIONS:
            response = "y"
            print(f"\033[2m(auto-executing: --dangerously-skip-permissions)\033[0m")
        else:
            response = input_no_history("\n\033[1;32mExecute? [y/n/e(dit)]:\033[0m ").strip().lower()

        if response in ("n", "no"):
            print("\033[2mCancelled.\033[0m")
            return False

        command = cache_hit.command
        if response in ("e", "edit"):
            edited = input_no_history(f"\033[1;33mEdit command:\033[0m {command}\r\033[1;33mEdit command:\033[0m ")
            if edited.strip():
                command = edited.strip()

        # Execute the command
        print(f"\n\033[2mExecuting on remote...\033[0m")
        success, stdout, stderr, returncode = execute_remote_command(command, cwd=_remote_cwd)

        # Show output
        if stdout:
            print(stdout, end="")
        if stderr:
            print(f"\033[1;31m{stderr}\033[0m", end="")

        if returncode == 0 and not has_stderr_errors(stderr):
            print(f"\033[1;32m✓ Command completed successfully\033[0m")
            log_command(user_input, command, True)
        else:
            print(f"\033[1;31m✗ Command failed with exit code {returncode}\033[0m")
            log_command(user_input, command, False)

        return True

    def process_input(self, user_input: str):
        """Process user input through the agent."""
        # Store current request for cache storage (used by run_shell_command)
        shell_state.current_request = user_input

        # Check cache FIRST in remote mode to potentially skip LLM
        if REMOTE_MODE and CACHE_AVAILABLE:
            try:
                cache = get_command_cache()
                cache.set_llm_validator(validate_cached_command)
                cache_hit = cache.lookup(user_input)

                if cache_hit:
                    self._execute_cached_command(cache_hit, user_input)
                    return
            except Exception as e:
                print(f"\033[2m(cache error: {e})\033[0m")

        # Save user message to conversation history
        shell_state.add_to_history("user", user_input)

        context = get_current_context()
        full_input = f"{context}\n\nUser request: {user_input}"

        try:
            result = self.agent.invoke({
                "messages": [{"role": "user", "content": full_input}]
            })

            # Check if we should skip LLM response (user declined an action)
            if shell_state.skip_llm_response:
                shell_state.skip_llm_response = False
                return

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
        print("\033[1;36m║   Type '//' to toggle LLM on/off           ║\033[0m")
        print("\033[1;36m║   Type '/ch' to clear history              ║\033[0m")
        print("\033[1;36m║   Type '/d' to toggle danger mode          ║\033[0m")
        print("\033[1;36m║   Type 'v' for voice input                 ║\033[0m")
        shell_name = Path(SHELL_EXECUTABLE).name
        if REMOTE_MODE:
            print(f"\033[1;36m║   Mode: REMOTE (SSH tunnel)                ║\033[0m")
        else:
            print(f"\033[1;36m║   Shell: {shell_name:<4} | Memory: on                 ║\033[0m")
        print(f"\033[1;36m║   Model: {MODEL[:35]:<35}║\033[0m")
        if AUDIO_AVAILABLE:
            print(f"\033[1;36m║   Voice: {VOICE_MODEL[:35]:<35}║\033[0m")
        print(f"\033[1;36m║   History: {history_count} commands loaded{' ' * (27 - len(str(history_count)))}║\033[0m")
        print("\033[1;36m╚════════════════════════════════════════════╝\033[0m")

        try:
            while True:
                print()  # Newline before prompt (outside readline)
                try:
                    user_input = input(self.get_prompt()).strip()
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
                        print(f"\033[2m→ direct\033[0m")
                        if REMOTE_MODE:
                            # Remote execution
                            success, stdout, stderr, returncode = execute_remote_command(
                                direct_cmd,
                                cwd=_remote_cwd  # Use remote cwd, not local
                            )
                            if stdout:
                                print(stdout, end="")
                            if stderr:
                                print(f"\033[1;31m{stderr}\033[0m", end="")
                        elif requires_interactive_mode(direct_cmd):
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

                # Toggle LLM mode with /llm or //
                if user_input in ("/llm", "//"):
                    global DIRECT_MODE
                    DIRECT_MODE = not DIRECT_MODE
                    if DIRECT_MODE:
                        print("\033[1;33m📟 LLM OFF - Direct mode\033[0m")
                    else:
                        print("\033[1;32m🤖 LLM ON - Natural language mode\033[0m")
                    continue

                # Clear command history
                if user_input in ("/clearhistory", "/ch"):
                    readline.clear_history()
                    history_file = self._get_history_file()
                    if history_file.exists():
                        history_file.unlink()
                    mode = "remote" if REMOTE_MODE else "local"
                    print(f"\033[1;33m🗑️  Cleared {mode} command history\033[0m")
                    continue

                # Toggle skip-permissions mode
                if user_input in ("/danger", "/d"):
                    global SKIP_PERMISSIONS
                    SKIP_PERMISSIONS = not SKIP_PERMISSIONS
                    if SKIP_PERMISSIONS:
                        print("\033[1;31m⚠️  DANGER MODE ON - Commands execute without confirmation!\033[0m")
                    else:
                        print("\033[1;32m✓ Safe mode - Commands require confirmation\033[0m")
                    continue

                # In direct mode, execute commands directly without LLM
                if DIRECT_MODE:
                    self._execute_direct(user_input)
                    continue

                # Check if input looks like a shell command (using LLM)
                if looks_like_shell_command(user_input):
                    print(f"\n\033[1;33mThis looks like a shell command.\033[0m")
                    response = input_no_history("\033[1;32mRun as-is? [y/n/i(nterpret)]:\033[0m ").strip().lower()
                    if response in ("y", "yes"):
                        # Use _execute_direct which handles both local and remote modes correctly
                        self._execute_direct(user_input)
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
    global SKIP_PERMISSIONS, REMOTE_MODE, _remote_client

    parser = argparse.ArgumentParser(
        description="Natural Language Shell - An intelligent shell powered by LangChain DeepAgents"
    )
    parser.add_argument(
        "--dangerously-skip-permissions",
        action="store_true",
        help="DANGEROUS: Skip all confirmation prompts and auto-execute commands"
    )
    parser.add_argument(
        "--remote",
        action="store_true",
        help="Execute commands on remote server via SSH tunnel (run ./tunnel.sh first)"
    )
    parser.add_argument(
        "-c", "--inline",
        type=str,
        metavar="COMMAND",
        help="Execute a single command and exit (non-interactive mode)"
    )
    parser.add_argument(
        "--llm-off",
        action="store_true",
        help="Execute command directly without LLM processing (use with --inline)"
    )
    args = parser.parse_args()

    if args.dangerously_skip_permissions:
        SKIP_PERMISSIONS = True
        print("\033[1;31m⚠️  WARNING: Running with --dangerously-skip-permissions\033[0m")
        print("\033[1;31m⚠️  All commands will be executed WITHOUT confirmation!\033[0m")
        print()

    if args.remote:
        global REMOTE_PRIVATE_KEY

        if not REMOTE_AVAILABLE:
            print("\033[1;31mError: Remote execution not available. Check remote_client.py import.\033[0m")
            sys.exit(1)
        if not REMOTE_PRIVATE_KEY_PATH:
            print("\033[1;31mError: NLSH_PRIVATE_KEY_PATH not set in .env\033[0m")
            sys.exit(1)

        # Load private key for Ed25519 authentication
        from shared.asymmetric_crypto import load_private_key
        key_path = Path(REMOTE_PRIVATE_KEY_PATH).expanduser()
        if not key_path.exists():
            print(f"\033[1;31mError: Private key not found: {key_path}\033[0m")
            print("\033[1;33mRun: python packages/shared/keygen.py all\033[0m")
            sys.exit(1)
        try:
            REMOTE_PRIVATE_KEY = load_private_key(str(key_path))
        except Exception as e:
            print(f"\033[1;31mError loading private key: {e}\033[0m")
            sys.exit(1)

        REMOTE_MODE = True
        _remote_client = True  # Flag that remote is configured
        print(f"\033[1;35m🌐 Remote mode: via SSH tunnel (localhost:{REMOTE_PORT})\033[0m")
        print()

    # Handle inline execution mode
    if args.inline:
        command = args.inline
        if args.llm_off:
            # Direct execution - no LLM
            print(f"\033[2m→ direct\033[0m")
            if REMOTE_MODE:
                _success, stdout, stderr, returncode = execute_remote_command(command)
            else:
                proc_result = subprocess.run(
                    command,
                    shell=True,
                    executable=SHELL_EXECUTABLE,
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                stdout = proc_result.stdout
                stderr = proc_result.stderr
                returncode = proc_result.returncode

            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(f"\033[1;31m{stderr}\033[0m", end="" if stderr.endswith("\n") else "\n")

            sys.exit(0 if returncode == 0 else returncode)
        else:
            # Use LLM to process the natural language request
            shell = NLShell()
            shell.process_input(command)
            sys.exit(0)

    shell = NLShell()
    shell.run()


if __name__ == "__main__":
    main()
