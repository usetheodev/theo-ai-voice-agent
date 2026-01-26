"""Base provider infrastructure.

Provides base classes and utilities for all providers (ASR, LLM, TTS, VAD).
"""

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

T = TypeVar("T")


class ProviderHealth(Enum):
    """Health status of a provider.

    Used for monitoring and circuit breaker decisions.

    Attributes:
        HEALTHY: Provider is working normally.
        DEGRADED: Provider is working but with issues (high latency, errors).
        UNHEALTHY: Provider is not working.
        UNKNOWN: Health status has not been checked.
    """

    HEALTHY = "healthy"
    """Provider is working normally."""

    DEGRADED = "degraded"
    """Provider is working but with issues."""

    UNHEALTHY = "unhealthy"
    """Provider is not working."""

    UNKNOWN = "unknown"
    """Health status has not been checked."""


@dataclass
class ProviderConfig:
    """Configuration for providers.

    Common configuration that applies to all provider types.
    Specific providers can extend this with additional fields.

    Attributes:
        api_key: API key for authentication.
        api_base: Base URL for API calls.
        timeout: Request timeout in seconds.
        retry_attempts: Number of retry attempts on failure.
        retry_delay: Initial delay between retries in seconds.
        retry_backoff: Multiplier for exponential backoff.
        retry_max_delay: Maximum delay between retries.

    Example:
        >>> config = ProviderConfig(
        ...     api_key="sk-...",
        ...     timeout=30.0,
        ...     retry_attempts=3,
        ... )
        >>> provider = MyProvider(config=config)
    """

    api_key: Optional[str] = None
    """API key for authentication. Can also use env vars."""

    api_base: Optional[str] = None
    """Base URL for API calls. Provider-specific default if None."""

    timeout: float = 30.0
    """Request timeout in seconds."""

    retry_attempts: int = 3
    """Number of retry attempts on failure."""

    retry_delay: float = 1.0
    """Initial delay between retries in seconds."""

    retry_backoff: float = 2.0
    """Multiplier for exponential backoff."""

    retry_max_delay: float = 30.0
    """Maximum delay between retries in seconds."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Additional provider-specific configuration."""

    def get_api_key(self, env_var: str = "API_KEY") -> Optional[str]:
        """Get API key from config or environment variable.

        Args:
            env_var: Environment variable name to check.

        Returns:
            API key or None if not configured.
        """
        return self.api_key or os.environ.get(env_var)

    def with_defaults(self, **defaults) -> "ProviderConfig":
        """Create a new config with defaults applied.

        Values in current config take precedence over defaults.

        Args:
            **defaults: Default values to apply.

        Returns:
            New ProviderConfig with defaults.
        """
        merged = {**defaults, **{k: v for k, v in self.__dict__.items() if v is not None}}
        return ProviderConfig(**merged)


@dataclass
class ProviderMetrics:
    """Metrics collected from provider operations.

    Used for monitoring, alerting, and circuit breaker decisions.

    Attributes:
        total_requests: Total number of requests made.
        successful_requests: Number of successful requests.
        failed_requests: Number of failed requests.
        total_latency_ms: Sum of all request latencies in ms.
        min_latency_ms: Minimum observed latency.
        max_latency_ms: Maximum observed latency.
        last_error: Last error message (if any).
        last_error_time: Timestamp of last error.
    """

    total_requests: int = 0
    """Total number of requests made."""

    successful_requests: int = 0
    """Number of successful requests."""

    failed_requests: int = 0
    """Number of failed requests."""

    total_latency_ms: float = 0.0
    """Sum of all request latencies in milliseconds."""

    min_latency_ms: float = float("inf")
    """Minimum observed latency in milliseconds."""

    max_latency_ms: float = 0.0
    """Maximum observed latency in milliseconds."""

    last_error: Optional[str] = None
    """Last error message (if any)."""

    last_error_time: Optional[float] = None
    """Timestamp of last error (Unix time)."""

    last_success_time: Optional[float] = None
    """Timestamp of last successful request (Unix time)."""

    @property
    def avg_latency_ms(self) -> float:
        """Average latency in milliseconds."""
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    @property
    def success_rate(self) -> float:
        """Success rate (0.0 to 1.0)."""
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    @property
    def error_rate(self) -> float:
        """Error rate (0.0 to 1.0)."""
        return 1.0 - self.success_rate

    def record_success(self, latency_ms: float) -> None:
        """Record a successful request.

        Args:
            latency_ms: Request latency in milliseconds.
        """
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.last_success_time = time.time()

    def record_failure(self, error: str) -> None:
        """Record a failed request.

        Args:
            error: Error message.
        """
        self.total_requests += 1
        self.failed_requests += 1
        self.last_error = error
        self.last_error_time = time.time()

    def reset(self) -> None:
        """Reset all metrics."""
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_latency_ms = 0.0
        self.min_latency_ms = float("inf")
        self.max_latency_ms = 0.0
        self.last_error = None
        self.last_error_time = None
        self.last_success_time = None

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary.

        Returns:
            Dictionary representation of metrics.
        """
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "avg_latency_ms": self.avg_latency_ms,
            "min_latency_ms": self.min_latency_ms if self.min_latency_ms != float("inf") else None,
            "max_latency_ms": self.max_latency_ms,
            "success_rate": self.success_rate,
            "error_rate": self.error_rate,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time,
            "last_success_time": self.last_success_time,
        }


@dataclass
class HealthCheckResult:
    """Result of a health check.

    Attributes:
        status: Health status.
        latency_ms: Health check latency in milliseconds.
        message: Optional status message.
        details: Additional details.
    """

    status: ProviderHealth
    """Health status."""

    latency_ms: Optional[float] = None
    """Health check latency in milliseconds."""

    message: Optional[str] = None
    """Optional status message."""

    details: dict[str, Any] = field(default_factory=dict)
    """Additional details."""


class RetryableError(Exception):
    """Exception that indicates the operation can be retried.

    Raise this in providers when a transient error occurs that
    might succeed on retry (network issues, rate limits, etc.).
    """

    pass


class NonRetryableError(Exception):
    """Exception that indicates the operation should not be retried.

    Raise this in providers when an error is permanent and retry
    would not help (invalid API key, bad request, etc.).
    """

    pass


class BaseProvider(ABC, Generic[T]):
    """Base class for all providers.

    Provides common functionality:
    - Configuration management
    - Lifecycle hooks (connect, disconnect)
    - Health checking
    - Retry logic with exponential backoff
    - Metrics collection

    Subclasses should implement:
    - `_do_health_check()` for health checking
    - Provider-specific methods

    Example:
        >>> class MyASRProvider(BaseProvider, ASRInterface):
        ...     provider_name = "my-asr"
        ...
        ...     async def _do_health_check(self) -> HealthCheckResult:
        ...         # Check if API is reachable
        ...         return HealthCheckResult(status=ProviderHealth.HEALTHY)
        ...
        ...     async def transcribe_stream(self, audio_stream, language=None):
        ...         async for chunk in audio_stream:
        ...             result = await self._with_retry(
        ...                 lambda: self._call_api(chunk)
        ...             )
        ...             yield result
    """

    provider_name: str = "base"
    """Name of this provider (for logging and metrics)."""

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        **kwargs,
    ):
        """Initialize provider.

        Args:
            config: Provider configuration.
            **kwargs: Additional configuration as keyword arguments.
        """
        self._config = config or ProviderConfig()

        # Apply kwargs to config.extra
        if kwargs:
            self._config.extra.update(kwargs)

        self._metrics = ProviderMetrics()
        self._connected = False
        self._health_status = ProviderHealth.UNKNOWN

    @property
    def config(self) -> ProviderConfig:
        """Get provider configuration."""
        return self._config

    @property
    def metrics(self) -> ProviderMetrics:
        """Get provider metrics."""
        return self._metrics

    @property
    def is_connected(self) -> bool:
        """Check if provider is connected."""
        return self._connected

    @property
    def health_status(self) -> ProviderHealth:
        """Get last known health status."""
        return self._health_status

    # ==================== Lifecycle ====================

    def _ensure_connected(self) -> None:
        """Raise warning if not connected. Call at start of operations."""
        if not self._connected:
            import warnings
            warnings.warn(
                f"{self.provider_name} is not connected. "
                "Call await provider.connect() or use 'async with provider:'",
                RuntimeWarning,
                stacklevel=3,
            )

    async def connect(self) -> None:
        """Connect to the provider.

        Override this method to perform any initialization
        that requires async operations (e.g., opening connections).

        Called automatically when using async context manager.
        """
        self._connected = True

    async def disconnect(self) -> None:
        """Disconnect from the provider.

        Override this method to perform cleanup
        (e.g., closing connections, flushing buffers).

        Called automatically when using async context manager.
        """
        self._connected = False

    async def __aenter__(self) -> "BaseProvider":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    # ==================== Health Checking ====================

    @abstractmethod
    async def _do_health_check(self) -> HealthCheckResult:
        """Perform actual health check.

        Subclasses must implement this to check if the provider
        is working correctly (e.g., API is reachable).

        Returns:
            HealthCheckResult with status and details.
        """
        pass

    async def health_check(self) -> HealthCheckResult:
        """Check provider health.

        Wraps _do_health_check() with timing and error handling.

        Returns:
            HealthCheckResult with status, latency, and details.
        """
        start_time = time.perf_counter()

        try:
            result = await self._do_health_check()
            latency_ms = (time.perf_counter() - start_time) * 1000
            result.latency_ms = latency_ms
            self._health_status = result.status
            return result

        except Exception as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            self._health_status = ProviderHealth.UNHEALTHY
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                latency_ms=latency_ms,
                message=str(e),
            )

    # ==================== Retry Logic ====================

    async def _with_retry(
        self,
        operation: Callable[[], T],
        retry_on: Optional[tuple[type[Exception], ...]] = None,
    ) -> T:
        """Execute operation with retry logic.

        Uses exponential backoff with jitter.

        Args:
            operation: Async callable to execute.
            retry_on: Exception types to retry on. Defaults to RetryableError.

        Returns:
            Result of the operation.

        Raises:
            The last exception if all retries fail.
        """
        retry_on = retry_on or (RetryableError,)
        last_exception: Optional[Exception] = None

        for attempt in range(self._config.retry_attempts + 1):
            start_time = time.perf_counter()

            try:
                # Execute operation
                if asyncio.iscoroutinefunction(operation):
                    result = await operation()
                else:
                    result = operation()

                # Record success
                latency_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_success(latency_ms)

                return result

            except NonRetryableError:
                # Don't retry, record failure and re-raise
                self._metrics.record_failure(str(last_exception))
                raise

            except retry_on as e:
                last_exception = e

                # Last attempt, don't retry
                if attempt >= self._config.retry_attempts:
                    self._metrics.record_failure(str(e))
                    raise

                # Calculate backoff delay with jitter
                delay = min(
                    self._config.retry_delay * (self._config.retry_backoff ** attempt),
                    self._config.retry_max_delay,
                )
                # Add jitter (±25%)
                import random
                jitter = delay * 0.25 * (2 * random.random() - 1)
                delay = max(0, delay + jitter)

                await asyncio.sleep(delay)

            except Exception as e:
                # Unexpected exception, record and re-raise
                self._metrics.record_failure(str(e))
                raise

        # Should not reach here, but just in case
        if last_exception:
            raise last_exception
        raise RuntimeError("Retry logic error")

    # ==================== Utilities ====================

    def _measure_latency(self) -> "_LatencyContext":
        """Context manager for measuring operation latency.

        Example:
            >>> with self._measure_latency() as ctx:
            ...     await do_operation()
            >>> print(f"Latency: {ctx.latency_ms}ms")
        """
        return _LatencyContext()

    def reset_metrics(self) -> None:
        """Reset all collected metrics."""
        self._metrics.reset()

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"{self.__class__.__name__}("
            f"provider_name={self.provider_name!r}, "
            f"connected={self._connected}, "
            f"health={self._health_status.value})"
        )


class _LatencyContext:
    """Context manager for measuring latency."""

    def __init__(self):
        self.start_time: float = 0
        self.end_time: float = 0

    @property
    def latency_ms(self) -> float:
        """Latency in milliseconds."""
        return (self.end_time - self.start_time) * 1000

    def __enter__(self) -> "_LatencyContext":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.end_time = time.perf_counter()


# Convenience function for creating configs from environment
def config_from_env(
    prefix: str = "",
    **defaults,
) -> ProviderConfig:
    """Create ProviderConfig from environment variables.

    Looks for environment variables with the given prefix:
    - {PREFIX}_API_KEY
    - {PREFIX}_API_BASE
    - {PREFIX}_TIMEOUT
    - {PREFIX}_RETRY_ATTEMPTS

    Args:
        prefix: Environment variable prefix (e.g., "OPENAI").
        **defaults: Default values if env vars not set.

    Returns:
        ProviderConfig populated from environment.

    Example:
        >>> # With OPENAI_API_KEY and OPENAI_TIMEOUT set in environment
        >>> config = config_from_env("OPENAI", timeout=60.0)
    """
    def get_env(key: str, default: Any = None) -> Any:
        env_key = f"{prefix}_{key}" if prefix else key
        return os.environ.get(env_key, default)

    return ProviderConfig(
        api_key=get_env("API_KEY", defaults.get("api_key")),
        api_base=get_env("API_BASE", defaults.get("api_base")),
        timeout=float(get_env("TIMEOUT", defaults.get("timeout", 30.0))),
        retry_attempts=int(get_env("RETRY_ATTEMPTS", defaults.get("retry_attempts", 3))),
        retry_delay=float(get_env("RETRY_DELAY", defaults.get("retry_delay", 1.0))),
        retry_backoff=float(get_env("RETRY_BACKOFF", defaults.get("retry_backoff", 2.0))),
        retry_max_delay=float(get_env("RETRY_MAX_DELAY", defaults.get("retry_max_delay", 30.0))),
    )
