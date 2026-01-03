"""ScriptOrchestrator - coordinates the script workflow between subagents."""

from typing import Any, Callable

from subagents.generator import ScriptGenerator
from subagents.reviewer import ScriptReviewer
from subagents.executor import ScriptExecutor, OutputCallback
from script_types import (
    GeneratedScript,
    ScriptReview,
    ExecutionResult,
    ScriptWorkflowState,
    RiskLevel,
)


# Type alias for confirmation function
ConfirmCallback = Callable[[GeneratedScript, ScriptReview], tuple[bool, str | None]]


class ScriptOrchestrator:
    """Orchestrates the script generation, review, and execution workflow.

    Coordinates between:
    - ScriptGenerator: Converts natural language to scripts
    - ScriptReviewer: Analyzes scripts for safety
    - ScriptExecutor: Executes scripts with streaming

    Flow:
    1. Generate script from natural language
    2. Review script for safety
    3. Display to user and get confirmation
    4. Execute with streaming output
    """

    def __init__(
        self,
        llm: Any,
        shell: str = "/bin/bash",
    ):
        """Initialize the orchestrator.

        Args:
            llm: LangChain LLM instance for script generation
            shell: Shell interpreter for execution
        """
        self.generator = ScriptGenerator(llm)
        self.reviewer = ScriptReviewer()
        self.executor = ScriptExecutor(shell)

    async def process_request(
        self,
        request: str,
        cwd: str,
        is_remote: bool = False,
        context: str = "",
        confirm_callback: ConfirmCallback | None = None,
        output_callback: OutputCallback | None = None,
        timeout: int = 3600,
        env: dict[str, str] | None = None,
    ) -> tuple[ScriptWorkflowState, ExecutionResult | None]:
        """Process a complete script request through the full workflow.

        Args:
            request: Natural language request
            cwd: Current working directory
            is_remote: Whether executing on remote server
            context: Additional context for generation
            confirm_callback: Function to get user confirmation
            output_callback: Function for streaming output
            timeout: Script execution timeout
            env: Additional environment variables

        Returns:
            Tuple of (final workflow state, execution result or None)
        """
        state = ScriptWorkflowState(
            original_request=request,
            working_directory=cwd,
            is_remote=is_remote,
        )

        # Phase 1: Generate script
        state = await self._generate_phase(state, context)
        if state.generated_script is None:
            return state, None

        # Phase 2: Review script
        state = await self._review_phase(state)

        # Check if review rejected the script
        if state.review_result and not state.review_result.approved:
            return state, None

        # Phase 3: Get user confirmation (if callback provided)
        if confirm_callback:
            approved, feedback = confirm_callback(
                state.generated_script,
                state.review_result,
            )
            state.user_approved = approved
            state.user_feedback = feedback

            # If user provided feedback, regenerate
            if feedback and not approved:
                state.generation_attempts += 1
                state = await self._generate_phase(state, context, feedback)
                if state.generated_script:
                    state = await self._review_phase(state)
                    if state.review_result and state.review_result.approved:
                        approved, feedback = confirm_callback(
                            state.generated_script,
                            state.review_result,
                        )
                        state.user_approved = approved

            if not state.user_approved:
                return state, None
        else:
            # Auto-approve if no callback (for testing/automation)
            state.user_approved = True

        # Phase 4: Execute script
        result = await self._execute_phase(
            state,
            output_callback=output_callback,
            timeout=timeout,
            env=env,
        )

        return state, result

    async def _generate_phase(
        self,
        state: ScriptWorkflowState,
        context: str = "",
        feedback: str | None = None,
    ) -> ScriptWorkflowState:
        """Run the generation phase.

        Args:
            state: Current workflow state
            context: Additional context
            feedback: User feedback for regeneration

        Returns:
            Updated state with generated script
        """
        try:
            script = await self.generator.process(
                request=state.original_request,
                cwd=state.working_directory,
                is_remote=state.is_remote,
                context=context,
                feedback=feedback or state.user_feedback,
            )
            state.generated_script = script
        except Exception as e:
            # Generation failed - could add error handling/retry here
            state.generated_script = None
            raise

        return state

    async def _review_phase(
        self,
        state: ScriptWorkflowState,
    ) -> ScriptWorkflowState:
        """Run the review phase.

        Args:
            state: Current workflow state with generated script

        Returns:
            Updated state with review result
        """
        if state.generated_script is None:
            return state

        review = await self.reviewer.process(state.generated_script)
        state.review_result = review

        return state

    async def _execute_phase(
        self,
        state: ScriptWorkflowState,
        output_callback: OutputCallback | None = None,
        timeout: int = 3600,
        env: dict[str, str] | None = None,
    ) -> ExecutionResult | None:
        """Run the execution phase.

        Args:
            state: Current workflow state
            output_callback: Callback for streaming output
            timeout: Execution timeout
            env: Environment variables

        Returns:
            ExecutionResult or None if script not available
        """
        if state.generated_script is None:
            return None

        cwd = state.working_directory if not state.is_remote else None

        result = await self.executor.process(
            script=state.generated_script,
            cwd=cwd,
            timeout=timeout,
            on_output=output_callback,
            env=env,
        )

        state.execution_result = result
        return result

    async def generate_only(
        self,
        request: str,
        cwd: str,
        is_remote: bool = False,
        context: str = "",
    ) -> tuple[GeneratedScript | None, ScriptReview | None]:
        """Generate and review a script without executing.

        Useful for preview/edit workflows.

        Args:
            request: Natural language request
            cwd: Current working directory
            is_remote: Whether for remote execution
            context: Additional context

        Returns:
            Tuple of (generated script, review) or (None, None) on failure
        """
        state = ScriptWorkflowState(
            original_request=request,
            working_directory=cwd,
            is_remote=is_remote,
        )

        try:
            state = await self._generate_phase(state, context)
            if state.generated_script:
                state = await self._review_phase(state)
                return state.generated_script, state.review_result
        except Exception:
            pass

        return None, None

    def format_script_display(
        self,
        script: GeneratedScript,
        review: ScriptReview | None = None,
    ) -> str:
        """Format a script for terminal display.

        Args:
            script: The script to display
            review: Optional review result

        Returns:
            Formatted string for terminal output
        """
        lines = []

        # Header
        lines.append(f"\n{'─' * 60}")
        lines.append(f"│ Script: {script.name}")
        lines.append(f"{'─' * 60}")

        # Steps
        lines.append("│ Steps:")
        for i, step in enumerate(script.steps, 1):
            lines.append(f"│   {i}. {step}")

        # Metadata
        risk_emoji = self.reviewer.get_risk_emoji(script.risk_level)
        lines.append(f"{'─' * 60}")
        lines.append(
            f"│ Risk: {risk_emoji} {script.risk_level.value.upper()}  •  "
            f"Duration: ~{script.estimated_duration.value}"
        )
        lines.append(f"{'─' * 60}")

        # Review warnings (if any)
        if review and review.warnings:
            lines.append("│ Warnings:")
            for warning in review.warnings[:3]:  # Limit to 3
                lines.append(f"│   ⚠️  {warning}")
            lines.append(f"{'─' * 60}")

        return "\n".join(lines)

    def format_script_code(
        self,
        script: GeneratedScript,
        show_line_numbers: bool = True,
    ) -> str:
        """Format script code for terminal display.

        Args:
            script: The script to display
            show_line_numbers: Whether to show line numbers

        Returns:
            Formatted script code
        """
        lines = script.script.split('\n')
        if show_line_numbers:
            width = len(str(len(lines)))
            formatted = []
            for i, line in enumerate(lines, 1):
                formatted.append(f"{i:>{width}}│ {line}")
            return "\n".join(formatted)
        return script.script
