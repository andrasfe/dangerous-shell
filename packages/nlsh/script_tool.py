"""Shell script execution tool for nlsh."""

import asyncio
from typing import Annotated

from script_types import GeneratedScript, ScriptReview, RiskLevel
from subagents import ScriptExecutor, ScriptReviewer


# Global executor instance (initialized on first use)
_executor: ScriptExecutor | None = None
_reviewer: ScriptReviewer | None = None


def get_executor() -> ScriptExecutor:
    """Get or create the global script executor."""
    global _executor
    if _executor is None:
        _executor = ScriptExecutor()
    return _executor


def get_reviewer() -> ScriptReviewer:
    """Get or create the global script reviewer."""
    global _reviewer
    if _reviewer is None:
        _reviewer = ScriptReviewer()
    return _reviewer


def display_script_preview(
    script: str,
    name: str,
    explanation: str,
    steps: list[str],
    risk_level: str,
) -> None:
    """Display a script preview to the user.

    Args:
        script: The script content
        name: Script name
        explanation: What the script does
        steps: List of step descriptions
        risk_level: Risk level string
    """
    # Risk emoji
    risk_emojis = {
        "safe": "✅",
        "moderate": "⚠️",
        "dangerous": "🔶",
        "critical": "🚫",
    }
    emoji = risk_emojis.get(risk_level.lower(), "❓")

    print(f"\n{'─' * 60}")
    print(f"│ Script: {name}")
    print(f"{'─' * 60}")
    print("│ Steps:")
    for i, step in enumerate(steps, 1):
        print(f"│   {i}. {step}")
    print(f"{'─' * 60}")
    print(f"│ Risk: {emoji} {risk_level.upper()}")
    print(f"│ {explanation}")
    print(f"{'─' * 60}")


def display_script_code(script: str) -> None:
    """Display script code with line numbers.

    Args:
        script: The script content
    """
    lines = script.split('\n')
    width = len(str(len(lines)))
    print()
    for i, line in enumerate(lines, 1):
        print(f"\033[2m{i:>{width}}│\033[0m {line}")
    print()


def run_shell_script(
    script: Annotated[str, "Multi-line shell script content"],
    explanation: Annotated[str, "Brief explanation of what this script does"],
    steps: Annotated[list[str], "Human-readable list of steps"],
    name: Annotated[str, "Short name for the script"] = "script",
    warning: Annotated[str | None, "Safety warning for dangerous operations"] = None,
    natural_request: Annotated[str, "The original natural language request"] = "",
) -> str:
    """Execute a multi-line shell script with streaming output.

    Use this tool when the task requires:
    - Multiple sequential commands
    - Shared variables or state between commands
    - Loops, conditionals, or functions
    - Error handling with cleanup
    - Atomic all-or-nothing execution

    Use run_shell_command for simple single commands instead.

    Args:
        script: The complete shell script content
        explanation: Brief explanation of what the script does
        steps: Human-readable list of steps the script performs
        name: Short descriptive name for the script
        warning: Safety warning if the script contains dangerous operations
        natural_request: The original user request (for context)

    Returns:
        Execution results including stdout, stderr, and status
    """
    # Import here to avoid circular imports
    from nlshell import (
        shell_state,
        REMOTE_MODE,
        SKIP_PERMISSIONS,
        input_no_history,
        _remote_cwd,
    )

    # Create a GeneratedScript object for review
    generated = GeneratedScript(
        script=script,
        name=name,
        explanation=explanation,
        steps=steps,
        risk_level=RiskLevel.MODERATE if warning else RiskLevel.SAFE,
    )

    # Review the script for safety
    reviewer = get_reviewer()

    async def do_review():
        return await reviewer.process(generated)

    review = asyncio.run(do_review())

    # Display preview
    display_script_preview(
        script=script,
        name=name,
        explanation=explanation,
        steps=steps,
        risk_level=review.risk_level.value,
    )

    # Show warnings from review
    if review.warnings:
        print("\n\033[1;33mWarnings:\033[0m")
        for w in review.warnings:
            print(f"  ⚠️  {w}")

    # Show explicit warning if provided
    if warning:
        print(f"\n\033[1;31mWarning:\033[0m {warning}")

    # Check if script was rejected
    if not review.approved:
        print("\n\033[1;31m🚫 Script REJECTED due to critical safety issues.\033[0m")
        return "Script rejected: Contains critical safety issues that cannot be executed."

    # Always show the script content
    display_script_code(script)

    # Handle auto-execution mode
    if SKIP_PERMISSIONS:
        print("\033[2m(auto-executing: --dangerously-skip-permissions)\033[0m")
    else:
        # Confirmation prompt
        if review.risk_level == RiskLevel.DANGEROUS:
            prompt = "Execute? Type 'EXECUTE' to confirm: "
            response = input_no_history(prompt).strip()
            if response != "EXECUTE":
                return "Script cancelled by user."
        elif review.risk_level == RiskLevel.CRITICAL:
            return "Script rejected: Critical safety issues found."
        else:
            prompt = "Execute? [y/n/e(dit)/f(eedback)]: "
            response = input_no_history(prompt).lower().strip()

            if response == "f":
                feedback = input_no_history("Feedback for LLM: ")
                return f"User feedback on script: {feedback}. Please modify the script accordingly."
            elif response == "e":
                print("Script editing not yet implemented. Please provide feedback instead.")
                return "Script cancelled by user."
            elif response not in ("y", "yes"):
                return "Script cancelled by user."

    # Execute the script
    print(f"\n\033[2mExecuting script...\033[0m\n")

    executor = get_executor()

    # Output callback for streaming
    def on_output(stream: str, data: str):
        if stream == "stdout":
            print(data, end="")
        else:
            print(f"\033[1;31m{data}\033[0m", end="")

    # Get working directory
    if REMOTE_MODE:
        cwd = _remote_cwd
    else:
        cwd = str(shell_state.cwd)

    # Execute
    async def do_execute():
        return await executor.execute_script(
            script_id="local",
            script_content=script,
            cwd=cwd,
            timeout=3600,
            on_output=on_output,
            total_steps=len(steps),
        )

    result = asyncio.run(do_execute())

    # Report result
    if result.success:
        print(f"\n\033[1;32m✓ Script completed successfully\033[0m")
        print(f"\033[2m  Duration: {result.duration_seconds:.1f}s\033[0m")
        return f"Script executed successfully.\nOutput:\n{result.stdout}"
    else:
        print(f"\n\033[1;31m✗ Script failed with exit code {result.returncode}\033[0m")
        if result.error_message:
            print(f"\033[1;31m  {result.error_message}\033[0m")
        return (
            f"Script failed with exit code {result.returncode}.\n"
            f"Stdout:\n{result.stdout}\n"
            f"Stderr:\n{result.stderr}"
        )
