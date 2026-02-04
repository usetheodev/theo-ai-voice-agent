"""
Base provider infrastructure for AI Agent.

Provides base classes and utilities for all providers (ASR, LLM, TTS).
Adapted from modelo_providers architecture for simplified use.
"""

import asyncio
import logging
import os
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class DeviceFallbackStrategy(Enum):
    """Strategy for device fallback when GPU fails."""
    NONE = "none"
    GPU_TO_CPU = "gpu_to_cpu"


class ProviderHealth(Enum):
    """Health status of a provider."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ProviderConfig:
    """Base configuration for providers."""

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

    device_fallback: DeviceFallbackStrategy = DeviceFallbackStrategy.NONE
    """Strategy for device fallback (e.g., GPU to CPU)."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Additional provider-specific configuration."""


@dataclass
class ProviderMetrics:
    """Metrics collected from provider operations."""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    last_error: Optional[str] = None
    last_error_time: Optional[float] = None
    last_success_time: Optional[float] = None

    @property
    def avg_latency_ms(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_latency_ms / self.successful_requests

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.successful_requests / self.total_requests

    def record_success(self, latency_ms: float) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.last_success_time = time.time()

    def record_failure(self, error: str) -> None:
        self.total_requests += 1
        self.failed_requests += 1
        self.last_error = error
        self.last_error_time = time.time()

    def reset(self) -> None:
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.total_latency_ms = 0.0
        self.min_latency_ms = float("inf")
        self.max_latency_ms = 0.0
        self.last_error = None
        self.last_error_time = None
        self.last_success_time = None


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    status: ProviderHealth
    latency_ms: Optional[float] = None
    message: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """
    Base class for all providers.

    Provides common functionality:
    - Lifecycle management (connect/disconnect)
    - Health checking
    - Retry logic with exponential backoff
    - Metrics collection

    Subclasses should implement:
    - `_do_health_check()` for health checking
    - Provider-specific methods
    """

    provider_name: str = "base"

    def __init__(
        self,
        config: Optional[ProviderConfig] = None,
        **kwargs,
    ):
        self._config = config or ProviderConfig()
        if kwargs:
            self._config.extra.update(kwargs)
        self._metrics = ProviderMetrics()
        self._connected = False
        self._health_status = ProviderHealth.UNKNOWN
        self._fallback_attempted = False
        self._is_warmed_up = False

    @property
    def config(self) -> ProviderConfig:
        return self._config

    @property
    def metrics(self) -> ProviderMetrics:
        return self._metrics

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def health_status(self) -> ProviderHealth:
        return self._health_status

    def reset_metrics(self) -> None:
        self._metrics.reset()

    # ==================== Lifecycle ====================

    async def connect(self) -> None:
        """Connect to the provider. Override for initialization."""
        self._connected = True
        logger.info(f"✅ {self.provider_name} connected")

    async def disconnect(self) -> None:
        """Disconnect from the provider. Override for cleanup."""
        self._connected = False
        logger.info(f"🔌 {self.provider_name} disconnected")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    def _ensure_connected(self) -> None:
        if not self._connected:
            import warnings
            warnings.warn(
                f"{self.provider_name} is not connected. "
                "Call await provider.connect() or use 'async with provider:'",
                RuntimeWarning,
                stacklevel=3,
            )

    # ==================== Health Check ====================

    @abstractmethod
    async def _do_health_check(self) -> HealthCheckResult:
        """Perform actual health check. Subclasses must implement."""
        pass

    async def health_check(self) -> HealthCheckResult:
        """Check provider health with timing."""
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

    # ==================== Warmup ====================

    async def warmup(self, **kwargs) -> float:
        """
        Warm up the provider to eliminate cold-start latency.

        Returns:
            Warmup time in milliseconds.
        """
        start = time.perf_counter()
        # Default: just run a health check
        await self.health_check()
        self._is_warmed_up = True
        return (time.perf_counter() - start) * 1000

    # ==================== Retry Logic ====================

    async def _with_retry(
        self,
        operation: Callable,
        retry_on: Optional[tuple[type[Exception], ...]] = None,
    ):
        """Execute operation with retry logic and exponential backoff."""
        retry_on = retry_on or (ConnectionError, TimeoutError)
        last_exception: Optional[Exception] = None

        for attempt in range(self._config.retry_attempts + 1):
            start_time = time.perf_counter()

            try:
                if asyncio.iscoroutinefunction(operation):
                    result = await operation()
                else:
                    result = operation()

                latency_ms = (time.perf_counter() - start_time) * 1000
                self._metrics.record_success(latency_ms)
                return result

            except retry_on as e:
                last_exception = e

                if attempt >= self._config.retry_attempts:
                    # Check for GPU→CPU fallback
                    if (
                        not self._fallback_attempted
                        and self._config.device_fallback == DeviceFallbackStrategy.GPU_TO_CPU
                        and self._is_gpu_error(e)
                    ):
                        self._fallback_attempted = True
                        logger.warning(
                            f"{self.provider_name}: GPU error after retries, "
                            "attempting CPU fallback"
                        )
                        await self.reconnect_with_device("cpu")
                        try:
                            if asyncio.iscoroutinefunction(operation):
                                result = await operation()
                            else:
                                result = operation()
                            latency_ms = (time.perf_counter() - start_time) * 1000
                            self._metrics.record_success(latency_ms)
                            return result
                        except Exception as cpu_err:
                            self._metrics.record_failure(str(cpu_err))
                            raise

                    self._metrics.record_failure(str(e))
                    raise

                # Calculate backoff delay with jitter
                delay = min(
                    self._config.retry_delay * (self._config.retry_backoff ** attempt),
                    self._config.retry_max_delay,
                )
                jitter = delay * 0.25 * (2 * random.random() - 1)
                delay = max(0, delay + jitter)

                logger.warning(
                    f"{self.provider_name}: Retry {attempt + 1}/{self._config.retry_attempts} "
                    f"after {delay:.2f}s - {e}"
                )
                await asyncio.sleep(delay)

            except Exception as e:
                self._metrics.record_failure(str(e))
                raise

        if last_exception:
            raise last_exception
        raise RuntimeError("Retry logic error")

    async def reconnect_with_device(self, device: str) -> None:
        """Reconnect with a different device. Override for device-specific logic."""
        logger.warning(f"{self.provider_name}: Falling back to device '{device}'")
        await self.disconnect()
        await self.connect()

    @staticmethod
    def _is_gpu_error(error: Exception) -> bool:
        """Check if error is GPU-related."""
        error_str = str(error).lower()
        return any(
            keyword in error_str
            for keyword in ["cuda", "oom", "out of memory", "gpu memory"]
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"provider_name={self.provider_name!r}, "
            f"connected={self._connected}, "
            f"health={self._health_status.value})"
        )


def config_from_env(prefix: str = "", **defaults) -> ProviderConfig:
    """Create ProviderConfig from environment variables."""
    def get_env(key: str, default: Any = None) -> Any:
        env_key = f"{prefix}_{key}" if prefix else key
        return os.environ.get(env_key, default)

    return ProviderConfig(
        timeout=float(get_env("TIMEOUT", defaults.get("timeout", 30.0))),
        retry_attempts=int(get_env("RETRY_ATTEMPTS", defaults.get("retry_attempts", 3))),
        retry_delay=float(get_env("RETRY_DELAY", defaults.get("retry_delay", 1.0))),
        retry_backoff=float(get_env("RETRY_BACKOFF", defaults.get("retry_backoff", 2.0))),
        retry_max_delay=float(get_env("RETRY_MAX_DELAY", defaults.get("retry_max_delay", 30.0))),
    )
