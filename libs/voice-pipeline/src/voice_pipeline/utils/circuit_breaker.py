"""Circuit breaker pattern for voice pipeline.

Provides circuit breaker implementation to prevent cascading failures
when external services (LLM, TTS, STT) are experiencing issues.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Type, TypeVar

logger = logging.getLogger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


class CircuitState(Enum):
    """Possible states of a circuit breaker."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Circuit is open, requests fail immediately
    HALF_OPEN = "half_open"  # Testing if service has recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior.

    Attributes:
        failure_threshold: Number of failures before opening circuit.
        success_threshold: Number of successes in half-open to close circuit.
        timeout: Seconds to wait before transitioning from open to half-open.
        monitored_exceptions: Exception types that count as failures.
        on_state_change: Optional callback when state changes.

    Example:
        >>> config = CircuitBreakerConfig(
        ...     failure_threshold=5,
        ...     timeout=30.0,
        ... )
    """

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 30.0
    monitored_exceptions: tuple[Type[Exception], ...] = field(
        default_factory=lambda: (Exception,)
    )
    on_state_change: Optional[Callable[["CircuitState", "CircuitState"], None]] = None


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, message: str, time_until_retry: Optional[float] = None):
        super().__init__(message)
        self.time_until_retry = time_until_retry


class CircuitBreaker:
    """Circuit breaker implementation.

    Monitors failures and prevents calls to failing services.

    States:
        - CLOSED: Normal operation, all calls pass through
        - OPEN: Service is failing, all calls fail immediately
        - HALF_OPEN: Testing if service recovered

    Example:
        >>> breaker = CircuitBreaker(config=CircuitBreakerConfig(failure_threshold=3))
        >>> async with breaker:
        ...     result = await llm.generate(prompt)
    """

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        name: str = "default",
    ):
        """Initialize circuit breaker.

        Args:
            config: Configuration for the circuit breaker.
            name: Name for logging and identification.
        """
        self.config = config or CircuitBreakerConfig()
        self.name = name
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)."""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self._state == CircuitState.HALF_OPEN

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state."""
        old_state = self._state
        if old_state != new_state:
            self._state = new_state
            logger.info(
                f"Circuit breaker '{self.name}' transitioned: "
                f"{old_state.value} -> {new_state.value}"
            )

            if self.config.on_state_change:
                try:
                    self.config.on_state_change(old_state, new_state)
                except Exception as e:
                    logger.warning(f"Error in on_state_change callback: {e}")

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self._last_failure_time is None:
            return True
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.config.timeout

    async def _check_state(self) -> None:
        """Check and potentially update state before call."""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to(CircuitState.HALF_OPEN)
                self._success_count = 0
            else:
                time_until_retry = (
                    self.config.timeout - (time.time() - self._last_failure_time)
                    if self._last_failure_time
                    else self.config.timeout
                )
                raise CircuitBreakerError(
                    f"Circuit breaker '{self.name}' is open. "
                    f"Service is unavailable, retry in {time_until_retry:.1f}s",
                    time_until_retry=time_until_retry,
                )

    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    async def _record_failure(self, exception: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Single failure in half-open returns to open
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
                    logger.warning(
                        f"Circuit breaker '{self.name}' opened after "
                        f"{self._failure_count} failures"
                    )

    async def __aenter__(self) -> "CircuitBreaker":
        """Enter async context - check if call is allowed."""
        await self._check_state()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit async context - record result."""
        if exc_type is None:
            await self._record_success()
        elif exc_type and issubclass(exc_type, self.config.monitored_exceptions):
            await self._record_failure(exc_val)
        return False  # Don't suppress exceptions

    async def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute a function with circuit breaker protection.

        Args:
            func: Async function to call.
            *args: Positional arguments for func.
            **kwargs: Keyword arguments for func.

        Returns:
            Result from func.

        Raises:
            CircuitBreakerError: If circuit is open.
            Exception: If func raises an exception.
        """
        async with self:
            return await func(*args, **kwargs)

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._transition_to(CircuitState.CLOSED)
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        logger.info(f"Circuit breaker '{self.name}' manually reset")

    def get_stats(self) -> dict[str, Any]:
        """Get current circuit breaker statistics.

        Returns:
            Dictionary with state, failure count, and other metrics.
        """
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.config.failure_threshold,
            "success_threshold": self.config.success_threshold,
            "timeout": self.config.timeout,
            "last_failure_time": self._last_failure_time,
        }


def with_circuit_breaker(
    breaker: CircuitBreaker,
) -> Callable[[F], F]:
    """Decorator that adds circuit breaker protection to async functions.

    Args:
        breaker: CircuitBreaker instance to use.

    Returns:
        Decorated function with circuit breaker protection.

    Example:
        >>> breaker = CircuitBreaker(name="llm")
        >>> @with_circuit_breaker(breaker)
        ... async def call_llm(prompt: str) -> str:
        ...     return await llm.generate(prompt)
    """
    import functools

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await breaker.call(func, *args, **kwargs)

        return wrapper  # type: ignore

    return decorator


# Default circuit breaker for LLM calls
LLM_CIRCUIT_BREAKER = CircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=5,
        success_threshold=2,
        timeout=30.0,
    ),
    name="llm",
)
