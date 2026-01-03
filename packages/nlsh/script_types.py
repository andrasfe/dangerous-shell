"""Type definitions for shell script generation and execution."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    """Risk level for script operations."""
    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    CRITICAL = "critical"


class ExecutionStatus(str, Enum):
    """Status of script execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EstimatedDuration(str, Enum):
    """Estimated script duration."""
    QUICK = "quick"      # < 10 seconds
    MEDIUM = "medium"    # 10s - 2 minutes
    LONG = "long"        # > 2 minutes


@dataclass
class GeneratedScript:
    """Output from ScriptGenerator subagent."""
    script: str                           # Complete bash script
    name: str                             # Short name (e.g., "deploy-app")
    explanation: str                      # What it does
    steps: list[str]                      # Human-readable step list
    variables: dict[str, str] = field(default_factory=dict)  # Configurable params
    risk_level: RiskLevel = RiskLevel.SAFE
    estimated_duration: EstimatedDuration = EstimatedDuration.QUICK

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "script": self.script,
            "name": self.name,
            "explanation": self.explanation,
            "steps": self.steps,
            "variables": self.variables,
            "risk_level": self.risk_level.value,
            "estimated_duration": self.estimated_duration.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GeneratedScript":
        """Create from dictionary."""
        return cls(
            script=data["script"],
            name=data["name"],
            explanation=data["explanation"],
            steps=data["steps"],
            variables=data.get("variables", {}),
            risk_level=RiskLevel(data.get("risk_level", "safe")),
            estimated_duration=EstimatedDuration(data.get("estimated_duration", "quick")),
        )


@dataclass
class ScriptReview:
    """Output from ScriptReviewer subagent."""
    approved: bool
    risk_level: RiskLevel
    warnings: list[str] = field(default_factory=list)
    dangerous_ops: list[tuple[int, str]] = field(default_factory=list)  # (line_num, description)
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "approved": self.approved,
            "risk_level": self.risk_level.value,
            "warnings": self.warnings,
            "dangerous_ops": self.dangerous_ops,
            "suggestions": self.suggestions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScriptReview":
        """Create from dictionary."""
        return cls(
            approved=data["approved"],
            risk_level=RiskLevel(data["risk_level"]),
            warnings=data.get("warnings", []),
            dangerous_ops=[tuple(op) for op in data.get("dangerous_ops", [])],
            suggestions=data.get("suggestions", []),
        )


@dataclass
class ExecutionResult:
    """Output from ScriptExecutor subagent."""
    script_id: str
    returncode: int
    success: bool
    duration_seconds: float
    stdout: str
    stderr: str
    steps_completed: int = 0
    total_steps: int = 0
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "script_id": self.script_id,
            "returncode": self.returncode,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionResult":
        """Create from dictionary."""
        return cls(
            script_id=data["script_id"],
            returncode=data["returncode"],
            success=data["success"],
            duration_seconds=data["duration_seconds"],
            stdout=data["stdout"],
            stderr=data["stderr"],
            steps_completed=data.get("steps_completed", 0),
            total_steps=data.get("total_steps", 0),
            error_message=data.get("error_message"),
        )


@dataclass
class ScriptWorkflowState:
    """Shared state between subagents during script workflow."""
    # Request context
    original_request: str
    working_directory: str
    is_remote: bool
    conversation_context: list[dict] = field(default_factory=list)

    # Generation phase
    generated_script: GeneratedScript | None = None
    generation_attempts: int = 0

    # Review phase
    review_result: ScriptReview | None = None
    user_approved: bool = False

    # Execution phase
    execution_result: ExecutionResult | None = None

    # User interaction
    pending_confirmation: str | None = None
    user_feedback: str | None = None
