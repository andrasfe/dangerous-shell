"""Background worker for processing command output interpretations."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar

# Configure module logger
logger = logging.getLogger(__name__)


# ============================================================================
# Data Types
# ============================================================================

class RequestPriority(IntEnum):
    """Priority levels for interpretation requests (lower = higher priority)."""
    HIGH = 0      # User-initiated, needs immediate response
    NORMAL = 1    # Standard background processing
    LOW = 2       # Batch/bulk operations, can be delayed


@dataclass(order=True)
class InterpretationRequest:
    """A request for LLM interpretation of command output.

    The dataclass ordering is based on (priority, sequence) for PriorityQueue.
    """
    priority: int
    sequence: int  # FIFO ordering within same priority
    # Non-comparison fields
    request_id: str = field(compare=False)
    command: str = field(compare=False)
    output: str = field(compare=False)
    context: dict[str, Any] = field(default_factory=dict, compare=False)
    created_at: float = field(default_factory=time.time, compare=False)


@dataclass
class InterpretationResult:
    """Result from processing an interpretation request."""
    request_id: str
    sequence: int  # For ordering results in display
    success: bool
    interpretation: Optional[str] = None
    error_message: Optional[str] = None
    duration_seconds: float = 0.0
    retry_count: int = 0


# Type alias for the LLM interpretation function
# Takes (command, output, context) and returns interpretation text
InterpretFn = Callable[[str, str, dict[str, Any]], Awaitable[str]]


# ============================================================================
# Interpretation Worker
# ============================================================================

class InterpretationWorker:
    """Background worker that processes interpretation requests one-at-a-time.

    Features:
    - Runs in a background thread with its own asyncio event loop
    - Uses asyncio.PriorityQueue for incoming requests (priority + FIFO)
    - Uses thread-safe queue.Queue for outgoing results to main thread
    - Configurable timeout and retry logic with exponential backoff
    - Self-healing: logs errors and continues processing
    - Graceful shutdown with queue draining

    Usage:
        # Create worker with an async LLM interpretation function
        async def interpret(cmd: str, output: str, ctx: dict) -> str:
            return await llm_client.interpret(cmd, output)

        worker = InterpretationWorker(interpret_fn=interpret)
        worker.start()

        # Enqueue requests (non-blocking)
        worker.enqueue(InterpretationRequest(...))

        # Poll for results from main thread
        while result := worker.get_result():
            display(result)

        # Shutdown
        worker.stop()
    """

    # Queue limits
    MAX_QUEUE_SIZE = 100

    # Timeout settings
    DEFAULT_TIMEOUT = 30.0  # seconds per interpretation

    # Retry settings
    MAX_RETRIES = 2
    INITIAL_BACKOFF = 1.0  # seconds
    MAX_BACKOFF = 8.0  # seconds

    # Shutdown settings
    DRAIN_TIMEOUT = 5.0  # seconds to wait for queue drain on shutdown

    def __init__(
        self,
        interpret_fn: InterpretFn,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        max_queue_size: int = MAX_QUEUE_SIZE,
    ):
        """Initialize the interpretation worker.

        Args:
            interpret_fn: Async function to call for LLM interpretation.
                          Signature: (command, output, context) -> str
            timeout: Timeout in seconds for each interpretation call
            max_retries: Maximum number of retries on failure
            max_queue_size: Maximum items in the request queue
        """
        self._interpret_fn = interpret_fn
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_queue_size = max_queue_size

        # Threading and event loop
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopping = False

        # Request queue (asyncio, set up in _run_loop)
        self._request_queue: asyncio.PriorityQueue[InterpretationRequest] | None = None

        # Result queue (thread-safe for main thread consumption)
        self._result_queue: queue.Queue[InterpretationResult] = queue.Queue()

        # Sequence counter for FIFO ordering within priority levels
        self._sequence_counter = 0
        self._sequence_lock = threading.Lock()

        # Worker task reference
        self._worker_task: asyncio.Task | None = None

        # Stats
        self._processed_count = 0
        self._error_count = 0

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    def start(self) -> None:
        """Start the background worker thread and event loop.

        This method is idempotent - calling it multiple times is safe.
        """
        if self._started:
            logger.debug("InterpretationWorker already started")
            return

        logger.info("Starting InterpretationWorker")

        # Create and start the background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="InterpretationWorker",
            daemon=True,
        )
        self._thread.start()

        # Wait for the worker loop to be ready
        # Schedule the worker task to start in the new loop
        future = asyncio.run_coroutine_threadsafe(
            self._init_and_start_worker(),
            self._loop,
        )
        try:
            future.result(timeout=5.0)
            self._started = True
            logger.info("InterpretationWorker started successfully")
        except Exception as e:
            logger.error(f"Failed to start InterpretationWorker: {e}")
            self._cleanup()
            raise

    def stop(self, timeout: float | None = None) -> None:
        """Stop the background worker gracefully.

        Args:
            timeout: Maximum time to wait for shutdown.
                     Defaults to DRAIN_TIMEOUT.

        This method attempts to drain the queue before stopping.
        """
        if not self._started:
            return

        timeout = timeout if timeout is not None else self.DRAIN_TIMEOUT
        logger.info(f"Stopping InterpretationWorker (drain timeout: {timeout}s)")

        self._stopping = True

        if self._loop and self._worker_task:
            # Signal the worker to stop
            future = asyncio.run_coroutine_threadsafe(
                self._shutdown_worker(timeout),
                self._loop,
            )
            try:
                future.result(timeout=timeout + 2.0)
            except Exception as e:
                logger.warning(f"Error during worker shutdown: {e}")

        self._cleanup()
        logger.info("InterpretationWorker stopped")

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._started = False
        self._stopping = False
        self._loop = None
        self._thread = None
        self._request_queue = None
        self._worker_task = None

    def _run_loop(self) -> None:
        """Run the asyncio event loop in the background thread."""
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            # Clean up any remaining tasks
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            # Run until all tasks are cancelled
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.close()

    async def _init_and_start_worker(self) -> None:
        """Initialize the queue and start the worker loop."""
        self._request_queue = asyncio.PriorityQueue(maxsize=self._max_queue_size)
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def _shutdown_worker(self, timeout: float) -> None:
        """Gracefully shutdown the worker, draining the queue."""
        if not self._worker_task:
            return

        # Wait for queue to drain (up to timeout)
        start = time.time()
        while (
            self._request_queue
            and not self._request_queue.empty()
            and (time.time() - start) < timeout
        ):
            await asyncio.sleep(0.1)

        # Cancel the worker task
        self._worker_task.cancel()
        try:
            await self._worker_task
        except asyncio.CancelledError:
            pass

    # =========================================================================
    # Queue Methods
    # =========================================================================

    def enqueue(
        self,
        request: InterpretationRequest,
    ) -> bool:
        """Add an interpretation request to the queue (non-blocking).

        Args:
            request: The interpretation request to enqueue

        Returns:
            True if request was queued, False if queue is full or worker stopped
        """
        if not self._started or self._stopping:
            logger.warning("Cannot enqueue: worker not running")
            return False

        if not self._loop or not self._request_queue:
            logger.warning("Cannot enqueue: worker not initialized")
            return False

        # Assign sequence number for FIFO within priority
        with self._sequence_lock:
            request.sequence = self._sequence_counter
            self._sequence_counter += 1

        # Schedule the enqueue in the event loop
        future = asyncio.run_coroutine_threadsafe(
            self._async_enqueue(request),
            self._loop,
        )

        try:
            return future.result(timeout=1.0)
        except Exception as e:
            logger.error(f"Failed to enqueue request: {e}")
            return False

    async def _async_enqueue(self, request: InterpretationRequest) -> bool:
        """Async enqueue with overflow handling."""
        if not self._request_queue:
            return False

        # Check for queue overflow
        if self._request_queue.full():
            # Try to drop lowest priority item
            dropped = await self._drop_lowest_priority()
            if not dropped:
                logger.warning(
                    f"Queue overflow: dropping request {request.request_id}"
                )
                return False

        try:
            self._request_queue.put_nowait(request)
            logger.debug(
                f"Enqueued request {request.request_id} "
                f"(priority={request.priority}, seq={request.sequence})"
            )
            return True
        except asyncio.QueueFull:
            logger.warning(f"Queue full: dropping request {request.request_id}")
            return False

    async def _drop_lowest_priority(self) -> bool:
        """Drop the lowest priority item from the queue.

        Returns True if an item was dropped.
        """
        if not self._request_queue or self._request_queue.empty():
            return False

        # Get all items, find lowest priority, re-add others
        items: list[InterpretationRequest] = []

        try:
            while not self._request_queue.empty():
                items.append(self._request_queue.get_nowait())
        except asyncio.QueueEmpty:
            pass

        if not items:
            return False

        # Find item with highest priority value (lowest priority)
        # Since we want FIFO within priority, also consider sequence
        lowest = max(items, key=lambda x: (x.priority, x.sequence))
        items.remove(lowest)

        logger.warning(
            f"Queue overflow: dropped request {lowest.request_id} "
            f"(priority={lowest.priority})"
        )

        # Re-add remaining items
        for item in items:
            try:
                self._request_queue.put_nowait(item)
            except asyncio.QueueFull:
                pass  # Should not happen since we just removed items

        return True

    def get_result(self, block: bool = False, timeout: float | None = None) -> InterpretationResult | None:
        """Get a result from the result queue.

        Args:
            block: If True, block until a result is available
            timeout: Maximum time to block (only if block=True)

        Returns:
            InterpretationResult or None if no result available
        """
        try:
            if block:
                return self._result_queue.get(block=True, timeout=timeout)
            else:
                return self._result_queue.get_nowait()
        except queue.Empty:
            return None

    def get_all_results(self) -> list[InterpretationResult]:
        """Get all available results from the queue.

        Returns:
            List of results (may be empty)
        """
        results = []
        while True:
            result = self.get_result()
            if result is None:
                break
            results.append(result)
        return results

    def has_pending_results(self) -> bool:
        """Check if there are pending results."""
        return not self._result_queue.empty()

    @property
    def queue_size(self) -> int:
        """Current number of items in the request queue."""
        if self._request_queue is None:
            return 0
        # Access qsize through the event loop for thread safety
        if not self._loop or not self._started:
            return 0
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._get_queue_size(),
                self._loop,
            )
            return future.result(timeout=1.0)
        except Exception:
            return 0

    async def _get_queue_size(self) -> int:
        """Get queue size from event loop thread."""
        return self._request_queue.qsize() if self._request_queue else 0

    # =========================================================================
    # Worker Loop
    # =========================================================================

    async def _worker_loop(self) -> None:
        """Main worker loop - processes requests one at a time.

        This loop is self-healing: errors are logged and processing continues.
        """
        logger.debug("Worker loop started")

        while not self._stopping:
            try:
                # Wait for next request with timeout for shutdown check
                try:
                    request = await asyncio.wait_for(
                        self._request_queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue  # Check _stopping flag and retry

                # Process the request
                result = await self._process_request(request)

                # Put result in output queue for main thread
                self._result_queue.put(result)
                self._processed_count += 1

                if not result.success:
                    self._error_count += 1

                logger.debug(
                    f"Processed request {request.request_id}: "
                    f"success={result.success}"
                )

            except asyncio.CancelledError:
                logger.debug("Worker loop cancelled")
                raise
            except Exception as e:
                # Self-healing: log and continue
                logger.exception(f"Unexpected error in worker loop: {e}")
                await asyncio.sleep(0.5)  # Brief pause before continuing

        logger.debug("Worker loop stopped")

    async def _process_request(
        self,
        request: InterpretationRequest,
    ) -> InterpretationResult:
        """Process a single interpretation request with retries.

        Args:
            request: The request to process

        Returns:
            InterpretationResult with success/failure details
        """
        start_time = time.time()
        last_error: str | None = None
        retry_count = 0

        for attempt in range(self._max_retries + 1):
            try:
                # Call the interpretation function with timeout
                interpretation = await asyncio.wait_for(
                    self._interpret_fn(
                        request.command,
                        request.output,
                        request.context,
                    ),
                    timeout=self._timeout,
                )

                duration = time.time() - start_time

                return InterpretationResult(
                    request_id=request.request_id,
                    sequence=request.sequence,
                    success=True,
                    interpretation=interpretation,
                    duration_seconds=duration,
                    retry_count=retry_count,
                )

            except asyncio.TimeoutError:
                retry_count = attempt
                last_error = f"Timeout after {self._timeout}s"
                logger.warning(
                    f"Request {request.request_id} timed out "
                    f"(attempt {attempt + 1}/{self._max_retries + 1})"
                )

            except asyncio.CancelledError:
                # Don't retry on cancellation
                raise

            except Exception as e:
                retry_count = attempt
                last_error = str(e)
                logger.warning(
                    f"Request {request.request_id} failed: {e} "
                    f"(attempt {attempt + 1}/{self._max_retries + 1})"
                )

            # Exponential backoff before retry
            if attempt < self._max_retries:
                backoff = min(
                    self.INITIAL_BACKOFF * (2 ** attempt),
                    self.MAX_BACKOFF,
                )
                logger.debug(f"Retrying in {backoff}s")
                await asyncio.sleep(backoff)

        # All retries exhausted
        duration = time.time() - start_time

        return InterpretationResult(
            request_id=request.request_id,
            sequence=request.sequence,
            success=False,
            error_message=last_error or "Unknown error",
            duration_seconds=duration,
            retry_count=retry_count,
        )

    # =========================================================================
    # Stats and Status
    # =========================================================================

    @property
    def is_running(self) -> bool:
        """Check if the worker is running."""
        return self._started and not self._stopping

    @property
    def stats(self) -> dict[str, Any]:
        """Get worker statistics."""
        return {
            "running": self.is_running,
            "processed_count": self._processed_count,
            "error_count": self._error_count,
            "queue_size": self.queue_size,
            "pending_results": self._result_queue.qsize(),
        }


# ============================================================================
# Helper Functions
# ============================================================================

def create_request(
    request_id: str,
    command: str,
    output: str,
    priority: RequestPriority = RequestPriority.NORMAL,
    context: dict[str, Any] | None = None,
) -> InterpretationRequest:
    """Factory function to create an InterpretationRequest.

    Args:
        request_id: Unique identifier for the request
        command: The command that was executed
        output: The command's output to interpret
        priority: Request priority level
        context: Additional context for interpretation

    Returns:
        InterpretationRequest ready for enqueueing
    """
    return InterpretationRequest(
        priority=priority.value,
        sequence=0,  # Will be set by enqueue()
        request_id=request_id,
        command=command,
        output=output,
        context=context or {},
    )
