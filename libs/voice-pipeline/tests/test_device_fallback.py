"""Tests for GPU→CPU device fallback."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voice_pipeline.providers.base import (
    BaseProvider,
    DeviceFallbackStrategy,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
)


class MockGPUProvider(BaseProvider):
    """Mock provider for testing device fallback."""

    provider_name = "mock-gpu"

    def __init__(self, config=None, **kwargs):
        super().__init__(config=config, **kwargs)
        self.device = "cuda:0"
        self.reconnect_calls = []

    async def _do_health_check(self) -> HealthCheckResult:
        return HealthCheckResult(status=ProviderHealth.HEALTHY)

    async def reconnect_with_device(self, device: str) -> None:
        self.reconnect_calls.append(device)
        self.device = device
        await self.disconnect()
        await self.connect()


class TestDeviceFallbackStrategy:
    """Tests for DeviceFallbackStrategy enum."""

    def test_none_strategy(self):
        assert DeviceFallbackStrategy.NONE.value == "none"

    def test_gpu_to_cpu_strategy(self):
        assert DeviceFallbackStrategy.GPU_TO_CPU.value == "gpu_to_cpu"

    def test_default_is_none(self):
        config = ProviderConfig()
        assert config.device_fallback == DeviceFallbackStrategy.NONE


class TestOOMFallback:
    """Tests for OOM → CPU fallback."""

    @pytest.mark.asyncio
    async def test_oom_with_fallback_enabled(self):
        """OOM error with GPU_TO_CPU should attempt CPU fallback."""
        config = ProviderConfig(
            retry_attempts=1,
            device_fallback=DeviceFallbackStrategy.GPU_TO_CPU,
        )
        provider = MockGPUProvider(config=config)
        await provider.connect()

        call_count = 0

        async def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # Fail on first 2 attempts (original + 1 retry)
                raise RetryableError("CUDA out of memory")
            return "success"

        result = await provider._with_retry(failing_then_success)
        assert result == "success"
        assert "cpu" in provider.reconnect_calls

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_oom_without_fallback(self):
        """OOM error without fallback should propagate."""
        config = ProviderConfig(
            retry_attempts=1,
            device_fallback=DeviceFallbackStrategy.NONE,
        )
        provider = MockGPUProvider(config=config)
        await provider.connect()

        async def always_fail():
            raise RetryableError("CUDA out of memory")

        with pytest.raises(RetryableError, match="CUDA out of memory"):
            await provider._with_retry(always_fail)

        assert len(provider.reconnect_calls) == 0
        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_non_gpu_error_no_fallback(self):
        """Non-GPU errors should not trigger fallback."""
        config = ProviderConfig(
            retry_attempts=1,
            device_fallback=DeviceFallbackStrategy.GPU_TO_CPU,
        )
        provider = MockGPUProvider(config=config)
        await provider.connect()

        async def network_error():
            raise RetryableError("Connection timeout")

        with pytest.raises(RetryableError, match="Connection timeout"):
            await provider._with_retry(network_error)

        assert len(provider.reconnect_calls) == 0
        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_fallback_only_once(self):
        """Fallback should only be attempted once (no infinite loops)."""
        config = ProviderConfig(
            retry_attempts=1,
            device_fallback=DeviceFallbackStrategy.GPU_TO_CPU,
        )
        provider = MockGPUProvider(config=config)
        await provider.connect()

        async def always_oom():
            raise RetryableError("CUDA out of memory")

        # First call triggers fallback
        with pytest.raises(RetryableError):
            await provider._with_retry(always_oom)

        assert len(provider.reconnect_calls) == 1

        # Second call should NOT trigger fallback again
        with pytest.raises(RetryableError):
            await provider._with_retry(always_oom)

        assert len(provider.reconnect_calls) == 1  # Still only 1
        await provider.disconnect()


class TestIsGPUError:
    """Tests for _is_gpu_error static method."""

    def test_cuda_error(self):
        assert BaseProvider._is_gpu_error(RuntimeError("CUDA error: device-side assert"))

    def test_oom_error(self):
        assert BaseProvider._is_gpu_error(RuntimeError("CUDA out of memory"))

    def test_generic_oom(self):
        assert BaseProvider._is_gpu_error(RuntimeError("Out of memory"))

    def test_gpu_memory(self):
        assert BaseProvider._is_gpu_error(RuntimeError("GPU memory exhausted"))

    def test_non_gpu_error(self):
        assert not BaseProvider._is_gpu_error(RuntimeError("Connection timeout"))

    def test_api_error(self):
        assert not BaseProvider._is_gpu_error(RuntimeError("Invalid API key"))
