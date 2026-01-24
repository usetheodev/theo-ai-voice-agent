"""Tests for provider base infrastructure."""

import asyncio
import os
import pytest
import time

from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    NonRetryableError,
    ProviderConfig,
    ProviderHealth,
    ProviderMetrics,
    RetryableError,
    config_from_env,
)


class TestProviderConfig:
    """Tests for ProviderConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ProviderConfig()

        assert config.api_key is None
        assert config.api_base is None
        assert config.timeout == 30.0
        assert config.retry_attempts == 3
        assert config.retry_delay == 1.0
        assert config.retry_backoff == 2.0
        assert config.retry_max_delay == 30.0
        assert config.extra == {}

    def test_custom_values(self):
        """Test custom configuration values."""
        config = ProviderConfig(
            api_key="test-key",
            api_base="https://api.example.com",
            timeout=60.0,
            retry_attempts=5,
        )

        assert config.api_key == "test-key"
        assert config.api_base == "https://api.example.com"
        assert config.timeout == 60.0
        assert config.retry_attempts == 5

    def test_get_api_key_from_config(self):
        """Test getting API key from config."""
        config = ProviderConfig(api_key="config-key")
        assert config.get_api_key("TEST_API_KEY") == "config-key"

    def test_get_api_key_from_env(self, monkeypatch):
        """Test getting API key from environment."""
        monkeypatch.setenv("TEST_API_KEY", "env-key")
        config = ProviderConfig()
        assert config.get_api_key("TEST_API_KEY") == "env-key"

    def test_get_api_key_config_takes_precedence(self, monkeypatch):
        """Test that config API key takes precedence over env."""
        monkeypatch.setenv("TEST_API_KEY", "env-key")
        config = ProviderConfig(api_key="config-key")
        assert config.get_api_key("TEST_API_KEY") == "config-key"

    def test_with_defaults(self):
        """Test applying defaults to config."""
        config = ProviderConfig(timeout=60.0, api_key=None)
        new_config = config.with_defaults(
            api_key="default-key",
            timeout=30.0,  # Should not override (60.0 is not None)
        )

        assert new_config.api_key == "default-key"  # None was replaced
        assert new_config.timeout == 60.0  # Original value preserved

    def test_extra_config(self):
        """Test extra configuration storage."""
        config = ProviderConfig(extra={"model": "gpt-4", "temperature": 0.7})
        assert config.extra["model"] == "gpt-4"
        assert config.extra["temperature"] == 0.7


class TestProviderHealth:
    """Tests for ProviderHealth enum."""

    def test_enum_values(self):
        """Test enum values."""
        assert ProviderHealth.HEALTHY.value == "healthy"
        assert ProviderHealth.DEGRADED.value == "degraded"
        assert ProviderHealth.UNHEALTHY.value == "unhealthy"
        assert ProviderHealth.UNKNOWN.value == "unknown"


class TestProviderMetrics:
    """Tests for ProviderMetrics."""

    def test_initial_values(self):
        """Test initial metric values."""
        metrics = ProviderMetrics()

        assert metrics.total_requests == 0
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 0
        assert metrics.total_latency_ms == 0.0
        assert metrics.min_latency_ms == float("inf")
        assert metrics.max_latency_ms == 0.0
        assert metrics.last_error is None

    def test_record_success(self):
        """Test recording successful requests."""
        metrics = ProviderMetrics()

        metrics.record_success(100.0)
        metrics.record_success(200.0)
        metrics.record_success(150.0)

        assert metrics.total_requests == 3
        assert metrics.successful_requests == 3
        assert metrics.failed_requests == 0
        assert metrics.total_latency_ms == 450.0
        assert metrics.min_latency_ms == 100.0
        assert metrics.max_latency_ms == 200.0
        assert metrics.avg_latency_ms == 150.0
        assert metrics.success_rate == 1.0
        assert metrics.error_rate == 0.0
        assert metrics.last_success_time is not None

    def test_record_failure(self):
        """Test recording failed requests."""
        metrics = ProviderMetrics()

        metrics.record_failure("Connection error")
        metrics.record_failure("Timeout")

        assert metrics.total_requests == 2
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 2
        assert metrics.last_error == "Timeout"
        assert metrics.last_error_time is not None
        assert metrics.success_rate == 0.0
        assert metrics.error_rate == 1.0

    def test_mixed_success_failure(self):
        """Test mixed success and failure."""
        metrics = ProviderMetrics()

        metrics.record_success(100.0)
        metrics.record_success(100.0)
        metrics.record_failure("Error")

        assert metrics.total_requests == 3
        assert metrics.successful_requests == 2
        assert metrics.failed_requests == 1
        assert metrics.success_rate == pytest.approx(0.666, rel=0.01)
        assert metrics.error_rate == pytest.approx(0.333, rel=0.01)

    def test_reset(self):
        """Test resetting metrics."""
        metrics = ProviderMetrics()
        metrics.record_success(100.0)
        metrics.record_failure("Error")

        metrics.reset()

        assert metrics.total_requests == 0
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 0
        assert metrics.last_error is None

    def test_to_dict(self):
        """Test converting metrics to dictionary."""
        metrics = ProviderMetrics()
        metrics.record_success(100.0)

        d = metrics.to_dict()

        assert d["total_requests"] == 1
        assert d["successful_requests"] == 1
        assert d["avg_latency_ms"] == 100.0
        assert d["success_rate"] == 1.0

    def test_avg_latency_empty(self):
        """Test average latency with no requests."""
        metrics = ProviderMetrics()
        assert metrics.avg_latency_ms == 0.0


class TestHealthCheckResult:
    """Tests for HealthCheckResult."""

    def test_basic_result(self):
        """Test basic health check result."""
        result = HealthCheckResult(status=ProviderHealth.HEALTHY)
        assert result.status == ProviderHealth.HEALTHY
        assert result.latency_ms is None
        assert result.message is None

    def test_full_result(self):
        """Test health check result with all fields."""
        result = HealthCheckResult(
            status=ProviderHealth.DEGRADED,
            latency_ms=150.0,
            message="High latency detected",
            details={"queue_size": 100},
        )

        assert result.status == ProviderHealth.DEGRADED
        assert result.latency_ms == 150.0
        assert result.message == "High latency detected"
        assert result.details["queue_size"] == 100


class MockProvider(BaseProvider):
    """Mock provider for testing."""

    provider_name = "mock"

    def __init__(self, health_result: HealthCheckResult = None, **kwargs):
        super().__init__(**kwargs)
        self._health_result = health_result or HealthCheckResult(
            status=ProviderHealth.HEALTHY
        )

    async def _do_health_check(self) -> HealthCheckResult:
        return self._health_result


class TestBaseProvider:
    """Tests for BaseProvider."""

    def test_initialization(self):
        """Test provider initialization."""
        provider = MockProvider()

        assert provider.provider_name == "mock"
        assert provider.config is not None
        assert provider.metrics is not None
        assert provider.is_connected is False
        assert provider.health_status == ProviderHealth.UNKNOWN

    def test_initialization_with_config(self):
        """Test initialization with custom config."""
        config = ProviderConfig(api_key="test-key", timeout=60.0)
        provider = MockProvider(config=config)

        assert provider.config.api_key == "test-key"
        assert provider.config.timeout == 60.0

    def test_initialization_with_kwargs(self):
        """Test initialization with kwargs."""
        provider = MockProvider(model="gpt-4", temperature=0.7)

        assert provider.config.extra["model"] == "gpt-4"
        assert provider.config.extra["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """Test connect and disconnect lifecycle."""
        provider = MockProvider()

        assert provider.is_connected is False

        await provider.connect()
        assert provider.is_connected is True

        await provider.disconnect()
        assert provider.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        provider = MockProvider()

        async with provider as p:
            assert p.is_connected is True
            assert p is provider

        assert provider.is_connected is False

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        """Test health check with healthy result."""
        provider = MockProvider(
            health_result=HealthCheckResult(status=ProviderHealth.HEALTHY)
        )

        result = await provider.health_check()

        assert result.status == ProviderHealth.HEALTHY
        assert result.latency_ms is not None
        assert result.latency_ms >= 0
        assert provider.health_status == ProviderHealth.HEALTHY

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """Test health check with unhealthy result."""
        provider = MockProvider(
            health_result=HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="API unreachable",
            )
        )

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert provider.health_status == ProviderHealth.UNHEALTHY

    @pytest.mark.asyncio
    async def test_retry_success_first_try(self):
        """Test retry with immediate success."""
        provider = MockProvider(
            config=ProviderConfig(retry_attempts=3)
        )

        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await provider._with_retry(operation)

        assert result == "success"
        assert call_count == 1
        assert provider.metrics.successful_requests == 1

    @pytest.mark.asyncio
    async def test_retry_success_after_retries(self):
        """Test retry with success after failures."""
        provider = MockProvider(
            config=ProviderConfig(
                retry_attempts=3,
                retry_delay=0.01,  # Fast for testing
            )
        )

        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RetryableError("Transient error")
            return "success"

        result = await provider._with_retry(operation)

        assert result == "success"
        assert call_count == 3
        assert provider.metrics.successful_requests == 1

    @pytest.mark.asyncio
    async def test_retry_all_fail(self):
        """Test retry with all attempts failing."""
        provider = MockProvider(
            config=ProviderConfig(
                retry_attempts=2,
                retry_delay=0.01,
            )
        )

        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            raise RetryableError("Always fails")

        with pytest.raises(RetryableError):
            await provider._with_retry(operation)

        assert call_count == 3  # Initial + 2 retries
        assert provider.metrics.failed_requests == 1

    @pytest.mark.asyncio
    async def test_retry_non_retryable_error(self):
        """Test that NonRetryableError is not retried."""
        provider = MockProvider(
            config=ProviderConfig(retry_attempts=3)
        )

        call_count = 0

        async def operation():
            nonlocal call_count
            call_count += 1
            raise NonRetryableError("Permanent error")

        with pytest.raises(NonRetryableError):
            await provider._with_retry(operation)

        assert call_count == 1  # No retries
        assert provider.metrics.failed_requests == 1

    @pytest.mark.asyncio
    async def test_retry_unexpected_error(self):
        """Test handling of unexpected errors."""
        provider = MockProvider()

        async def operation():
            raise ValueError("Unexpected")

        with pytest.raises(ValueError):
            await provider._with_retry(operation)

        assert provider.metrics.failed_requests == 1

    def test_repr(self):
        """Test string representation."""
        provider = MockProvider()
        repr_str = repr(provider)

        assert "MockProvider" in repr_str
        assert "mock" in repr_str
        assert "connected=False" in repr_str

    def test_reset_metrics(self):
        """Test resetting metrics."""
        provider = MockProvider()
        provider.metrics.record_success(100.0)
        provider.metrics.record_failure("Error")

        provider.reset_metrics()

        assert provider.metrics.total_requests == 0


class TestConfigFromEnv:
    """Tests for config_from_env function."""

    def test_no_prefix(self, monkeypatch):
        """Test config from env without prefix."""
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("TIMEOUT", "60.0")

        config = config_from_env()

        assert config.api_key == "test-key"
        assert config.timeout == 60.0

    def test_with_prefix(self, monkeypatch):
        """Test config from env with prefix."""
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
        monkeypatch.setenv("OPENAI_TIMEOUT", "45.0")
        monkeypatch.setenv("OPENAI_RETRY_ATTEMPTS", "5")

        config = config_from_env("OPENAI")

        assert config.api_key == "openai-key"
        assert config.timeout == 45.0
        assert config.retry_attempts == 5

    def test_with_defaults(self, monkeypatch):
        """Test config from env with defaults."""
        # No env vars set

        config = config_from_env(
            "TEST",
            api_key="default-key",
            timeout=120.0,
        )

        assert config.api_key == "default-key"
        assert config.timeout == 120.0

    def test_env_overrides_defaults(self, monkeypatch):
        """Test that env vars override defaults."""
        monkeypatch.setenv("TEST_TIMEOUT", "60.0")

        config = config_from_env(
            "TEST",
            timeout=120.0,  # Default
        )

        assert config.timeout == 60.0  # Env var wins


class TestLatencyContext:
    """Tests for latency measurement context."""

    def test_latency_measurement(self):
        """Test latency measurement."""
        provider = MockProvider()

        with provider._measure_latency() as ctx:
            time.sleep(0.01)  # 10ms

        assert ctx.latency_ms >= 10.0
        assert ctx.latency_ms < 100.0  # Reasonable upper bound
