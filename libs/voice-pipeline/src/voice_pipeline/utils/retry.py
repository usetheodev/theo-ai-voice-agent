"""Retry utilities for voice pipeline.

Provides retry decorators and helpers for handling transient failures
in LLM calls, API requests, and other network operations.
"""

import asyncio
import functools
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence, Type, TypeVar, Union

logger = logging.getLogger(__name__)

# Type variable for decorated functions
F = TypeVar("F", bound=Callable[..., Any])


# Common transient exceptions that should trigger retry
RETRYABLE_EXCEPTIONS: tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    ConnectionResetError,
    ConnectionRefusedError,
)


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of attempts (including first try).
        base_delay: Base delay in seconds between retries.
        max_delay: Maximum delay in seconds between retries.
        exponential_base: Base for exponential backoff (default 2).
        jitter: Add random jitter to delays (0-1, where 1 = 100% jitter).
        retryable_exceptions: Tuple of exception types that trigger retry.
        on_retry: Optional callback called before each retry.

    Example:
        >>> config = RetryConfig(
        ...     max_attempts=3,
        ...     base_delay=1.0,
        ...     max_delay=30.0,
        ...     jitter=0.1,
        ... )
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: float = 0.1
    retryable_exceptions: tuple[Type[Exception], ...] = field(
        default_factory=lambda: RETRYABLE_EXCEPTIONS
    )
    on_retry: Optional[Callable[[Exception, int, float], None]] = None

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number.

        Uses exponential backoff with optional jitter.

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter > 0:
            jitter_amount = delay * self.jitter * random.random()
            delay += jitter_amount

        return delay


# Default configuration for LLM calls
LLM_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    jitter=0.1,
)


def with_retry(
    config: Optional[RetryConfig] = None,
    retryable_exceptions: Optional[Sequence[Type[Exception]]] = None,
    max_attempts: Optional[int] = None,
) -> Callable[[F], F]:
    """Decorator that adds retry logic to async functions.

    Retries the decorated function on specified exceptions using
    exponential backoff with jitter.

    Args:
        config: RetryConfig instance. If not provided, uses LLM_RETRY_CONFIG.
        retryable_exceptions: Override retryable exceptions.
        max_attempts: Override max attempts.

    Returns:
        Decorated function with retry logic.

    Example:
        >>> @with_retry()
        ... async def call_llm(prompt: str) -> str:
        ...     return await llm.generate(prompt)
        >>>
        >>> @with_retry(max_attempts=5)
        ... async def call_api(url: str) -> dict:
        ...     return await http_client.get(url)
    """
    effective_config = config or LLM_RETRY_CONFIG

    # Allow overrides
    if retryable_exceptions is not None:
        effective_config = RetryConfig(
            max_attempts=effective_config.max_attempts,
            base_delay=effective_config.base_delay,
            max_delay=effective_config.max_delay,
            exponential_base=effective_config.exponential_base,
            jitter=effective_config.jitter,
            retryable_exceptions=tuple(retryable_exceptions),
            on_retry=effective_config.on_retry,
        )

    if max_attempts is not None:
        effective_config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=effective_config.base_delay,
            max_delay=effective_config.max_delay,
            exponential_base=effective_config.exponential_base,
            jitter=effective_config.jitter,
            retryable_exceptions=effective_config.retryable_exceptions,
            on_retry=effective_config.on_retry,
        )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception: Optional[Exception] = None

            for attempt in range(effective_config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                except effective_config.retryable_exceptions as e:
                    last_exception = e

                    # Check if we have more attempts
                    if attempt + 1 >= effective_config.max_attempts:
                        logger.warning(
                            f"Retry exhausted for {func.__name__} after "
                            f"{effective_config.max_attempts} attempts: {e}"
                        )
                        raise

                    # Calculate delay
                    delay = effective_config.get_delay(attempt)

                    logger.info(
                        f"Retry {attempt + 1}/{effective_config.max_attempts} "
                        f"for {func.__name__} after {delay:.2f}s due to: {e}"
                    )

                    # Call on_retry callback if provided
                    if effective_config.on_retry:
                        effective_config.on_retry(e, attempt + 1, delay)

                    # Wait before retry
                    await asyncio.sleep(delay)

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper  # type: ignore

    return decorator


async def retry_async(
    func: Callable[..., Any],
    *args,
    config: Optional[RetryConfig] = None,
    **kwargs,
) -> Any:
    """Execute an async function with retry logic.

    Alternative to decorator for one-off retries.

    Args:
        func: Async function to call.
        *args: Positional arguments for func.
        config: RetryConfig instance.
        **kwargs: Keyword arguments for func.

    Returns:
        Result from func.

    Example:
        >>> result = await retry_async(
        ...     llm.generate,
        ...     prompt,
        ...     config=RetryConfig(max_attempts=5),
        ... )
    """
    effective_config = config or LLM_RETRY_CONFIG

    @with_retry(config=effective_config)
    async def wrapper():
        return await func(*args, **kwargs)

    return await wrapper()


class RateLimitError(Exception):
    """Raised when rate limit is exceeded.

    Attributes:
        retry_after: Suggested wait time in seconds before retry.
    """

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class ServiceUnavailableError(Exception):
    """Raised when a service is temporarily unavailable."""

    pass


# Extended retryable exceptions including custom ones
EXTENDED_RETRYABLE_EXCEPTIONS: tuple[Type[Exception], ...] = (
    *RETRYABLE_EXCEPTIONS,
    RateLimitError,
    ServiceUnavailableError,
)


# Configuration for LLM calls with extended exceptions
LLM_EXTENDED_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=30.0,
    jitter=0.1,
    retryable_exceptions=EXTENDED_RETRYABLE_EXCEPTIONS,
)
