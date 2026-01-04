"""Message dataclasses for the async interpretation queue.

This module defines the data structures used for queuing command execution
results for asynchronous LLM interpretation. The queue supports priority-based
ordering where errors are processed before normal results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar
import time
import uuid


# Priority constants for interpretation requests
PRIORITY_LOW: int = 0
PRIORITY_NORMAL: int = 1
PRIORITY_HIGH: int = 2  # Used for errors that need immediate attention


@dataclass
class InterpretationRequest:
    """A request to interpret the results of a command execution.

    This dataclass encapsulates all the information needed to interpret
    a command's execution results, including the original user request,
    the command that was run, and its output.

    Attributes:
        request_id: Unique identifier for this request (UUID).
        timestamp: Unix timestamp when the request was created.
        original_request: The user's natural language request.
        command: The shell command that was executed.
        cwd: The current working directory when the command was executed.
        stdout: Standard output from the command.
        stderr: Standard error from the command.
        returncode: The command's exit code.
        success: Whether the command executed successfully.
        duration_seconds: How long the command took to execute.
        priority: Priority level (0=low, 1=normal, 2=high for errors).
        sequence_number: Sequential number for FIFO ordering within same priority.
    """

    request_id: str
    timestamp: float
    original_request: str
    command: str
    cwd: str
    stdout: str
    stderr: str
    returncode: int
    success: bool
    duration_seconds: float
    priority: int
    sequence_number: int

    # Class-level priority constants for convenience
    PRIORITY_LOW: ClassVar[int] = PRIORITY_LOW
    PRIORITY_NORMAL: ClassVar[int] = PRIORITY_NORMAL
    PRIORITY_HIGH: ClassVar[int] = PRIORITY_HIGH

    @classmethod
    def create(
        cls,
        original_request: str,
        command: str,
        cwd: str,
        stdout: str,
        stderr: str,
        returncode: int,
        success: bool,
        duration_seconds: float,
        priority: int,
        sequence_number: int,
    ) -> "InterpretationRequest":
        """Factory method to create an InterpretationRequest with auto-generated ID and timestamp.

        This method automatically generates a UUID for request_id and captures
        the current timestamp, simplifying the creation of new requests.

        Args:
            original_request: The user's natural language request.
            command: The shell command that was executed.
            cwd: The current working directory when the command was executed.
            stdout: Standard output from the command.
            stderr: Standard error from the command.
            returncode: The command's exit code.
            success: Whether the command executed successfully.
            duration_seconds: How long the command took to execute.
            priority: Priority level (0=low, 1=normal, 2=high for errors).
            sequence_number: Sequential number for FIFO ordering within same priority.

        Returns:
            A new InterpretationRequest instance with auto-generated request_id and timestamp.
        """
        return cls(
            request_id=str(uuid.uuid4()),
            timestamp=time.time(),
            original_request=original_request,
            command=command,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            success=success,
            duration_seconds=duration_seconds,
            priority=priority,
            sequence_number=sequence_number,
        )

    def __lt__(self, other: "InterpretationRequest") -> bool:
        """Compare requests for PriorityQueue ordering.

        Ordering is determined by:
        1. Higher priority first (so we negate priority for min-heap behavior)
        2. Lower sequence_number first (FIFO within same priority)

        This ensures that high-priority items (like errors) are processed first,
        and within the same priority level, items are processed in FIFO order.

        Args:
            other: Another InterpretationRequest to compare against.

        Returns:
            True if this request should be processed before the other.
        """
        # Negate priority so higher priority values come first in min-heap
        # Then use sequence_number for FIFO ordering within same priority
        return (-self.priority, self.sequence_number) < (
            -other.priority,
            other.sequence_number,
        )


@dataclass
class InterpretationResult:
    """The result of interpreting a command execution.

    This dataclass contains the LLM's interpretation of a command's output,
    or an error message if the interpretation failed.

    Attributes:
        request_id: The ID of the original InterpretationRequest this result corresponds to.
        commentary: The LLM's interpretation of the command output.
        error: Error message if interpretation failed, None otherwise.
        sequence_number: Sequential number for ordered display of results.
    """

    request_id: str
    commentary: str
    error: str | None
    sequence_number: int
