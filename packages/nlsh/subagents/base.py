"""Base class for script subagents."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar, Generic

T = TypeVar("T")


class BaseSubagent(ABC, Generic[T]):
    """Base class for all script-related subagents.

    Subagents are specialized components that handle specific aspects of
    the script generation and execution workflow:
    - ScriptGenerator: Converts natural language to shell scripts
    - ScriptReviewer: Analyzes scripts for safety and correctness
    - ScriptExecutor: Executes scripts with streaming output
    """

    def __init__(self, name: str):
        """Initialize the subagent.

        Args:
            name: Human-readable name for the subagent
        """
        self.name = name

    @abstractmethod
    async def process(self, **kwargs: Any) -> T:
        """Process input and return output.

        Each subagent defines its own input parameters and output type.

        Returns:
            The processed output of type T
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
