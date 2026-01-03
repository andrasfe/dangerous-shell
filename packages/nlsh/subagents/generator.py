"""ScriptGenerator subagent - converts natural language to shell scripts."""

import json
import re
from typing import Any

from .base import BaseSubagent
from ..script_types import (
    GeneratedScript,
    RiskLevel,
    EstimatedDuration,
)


# Script template with best practices
SCRIPT_TEMPLATE = '''#!/usr/bin/env bash
set -euo pipefail
trap 'echo "Error on line $LINENO"; exit 1' ERR

# === Script: {name} ===
# Description: {description}

# --- Configuration ---
{variables}

# --- Functions ---
log() {{ echo "[$(date +'%H:%M:%S')] $*"; }}
error() {{ echo "[ERROR] $*" >&2; }}

# --- Main ---
{main_body}

log "✓ Complete"
'''

# System prompt for script generation
SCRIPT_GENERATION_PROMPT = '''You are an expert shell script generator. Convert natural language requests into well-structured bash scripts.

## Requirements

1. **Structure**: Use this exact structure:
   - Shebang: #!/usr/bin/env bash
   - set -euo pipefail (fail on errors)
   - trap for error handling
   - Variables section (with defaults)
   - Functions section (log, error helpers)
   - Main logic with step markers

2. **Step Markers**: Each major step MUST start with:
   log "[Step N/M] Description..."

3. **Variables**: Use environment variables with defaults:
   VAR="${VAR:-default_value}"

4. **Safety**:
   - Quote all variables
   - Use [[ ]] for tests
   - Check file/directory existence before operations

5. **Output Format**: Return ONLY valid JSON in this exact format:
{
  "script": "#!/usr/bin/env bash\\nset -euo pipefail\\n...",
  "name": "short-name",
  "explanation": "One sentence describing what it does",
  "steps": ["Step 1 description", "Step 2 description"],
  "variables": {"VAR_NAME": "default_value"},
  "risk_level": "safe|moderate|dangerous",
  "estimated_duration": "quick|medium|long"
}

## Risk Level Guidelines
- safe: Read operations, file creation, installations
- moderate: File modifications, network operations
- dangerous: Deletions, system modifications, sudo operations

## Estimated Duration
- quick: < 10 seconds
- medium: 10 seconds - 2 minutes
- long: > 2 minutes

## Context
Working directory: {cwd}
Shell: bash
Mode: {mode}
'''


class ScriptGenerator(BaseSubagent[GeneratedScript]):
    """Generates shell scripts from natural language requests.

    Uses LLM to convert user requests into properly structured
    bash scripts with error handling, logging, and step markers.
    """

    def __init__(self, llm: Any):
        """Initialize the script generator.

        Args:
            llm: The LangChain LLM instance to use for generation
        """
        super().__init__("ScriptGenerator")
        self.llm = llm

    async def process(
        self,
        request: str,
        cwd: str,
        is_remote: bool = False,
        context: str = "",
        feedback: str | None = None,
    ) -> GeneratedScript:
        """Generate a shell script from a natural language request.

        Args:
            request: The user's natural language request
            cwd: Current working directory
            is_remote: Whether executing on remote server
            context: Additional context (conversation history, etc.)
            feedback: User feedback on previous generation attempt

        Returns:
            GeneratedScript with the generated script and metadata
        """
        mode = "remote" if is_remote else "local"

        # Build the prompt
        system_prompt = SCRIPT_GENERATION_PROMPT.format(
            cwd=cwd,
            mode=mode,
        )

        user_prompt = f"Generate a shell script for: {request}"
        if context:
            user_prompt = f"{context}\n\n{user_prompt}"
        if feedback:
            user_prompt += f"\n\nUser feedback on previous attempt: {feedback}"

        # Call LLM
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await self._call_llm(messages)

        # Parse the response
        return self._parse_response(response)

    async def _call_llm(self, messages: list[dict]) -> str:
        """Call the LLM and return the response text.

        Args:
            messages: List of message dicts with role and content

        Returns:
            The LLM response as a string
        """
        # Use LangChain's invoke method
        from langchain_core.messages import HumanMessage, SystemMessage

        lc_messages = []
        for msg in messages:
            if msg["role"] == "system":
                lc_messages.append(SystemMessage(content=msg["content"]))
            else:
                lc_messages.append(HumanMessage(content=msg["content"]))

        result = await self.llm.ainvoke(lc_messages)
        return result.content

    def _parse_response(self, response: str) -> GeneratedScript:
        """Parse the LLM response into a GeneratedScript.

        Args:
            response: The raw LLM response

        Returns:
            Parsed GeneratedScript

        Raises:
            ValueError: If the response cannot be parsed
        """
        # Try to extract JSON from the response
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            raise ValueError(f"No JSON found in response: {response[:200]}")

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in response: {e}")

        # Validate required fields
        required = ["script", "name", "explanation", "steps"]
        missing = [f for f in required if f not in data]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        # Parse risk level
        risk_str = data.get("risk_level", "safe").lower()
        try:
            risk_level = RiskLevel(risk_str)
        except ValueError:
            risk_level = RiskLevel.MODERATE  # Default to moderate if unknown

        # Parse estimated duration
        duration_str = data.get("estimated_duration", "medium").lower()
        try:
            estimated_duration = EstimatedDuration(duration_str)
        except ValueError:
            estimated_duration = EstimatedDuration.MEDIUM

        return GeneratedScript(
            script=data["script"],
            name=data["name"],
            explanation=data["explanation"],
            steps=data["steps"],
            variables=data.get("variables", {}),
            risk_level=risk_level,
            estimated_duration=estimated_duration,
        )

    def generate_from_template(
        self,
        name: str,
        description: str,
        variables: dict[str, str],
        main_body: str,
    ) -> str:
        """Generate a script from the template.

        Useful for programmatic script generation without LLM.

        Args:
            name: Script name
            description: What the script does
            variables: Variable definitions with defaults
            main_body: The main script logic

        Returns:
            Complete script as a string
        """
        var_lines = []
        for var_name, default in variables.items():
            var_lines.append(f'{var_name}="${{{var_name}:-{default}}}"')

        return SCRIPT_TEMPLATE.format(
            name=name,
            description=description,
            variables="\n".join(var_lines) if var_lines else "# No variables",
            main_body=main_body,
        )
