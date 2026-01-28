"""Tests for retry utilities (Sprint 5)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.utils.retry import (
    RetryConfig,
    with_retry,
    retry_async,
    RateLimitError,
    ServiceUnavailableError,
    LLM_RETRY_CONFIG,
    RETRYABLE_EXCEPTIONS,
)


class TestRetryConfig:
    """Tests for RetryConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 30.0
        assert config.exponential_base == 2.0
        assert config.jitter >= 0

    def test_get_delay_exponential(self):
        """Test exponential backoff calculation."""
        config = RetryConfig(
            base_delay=1.0,
            exponential_base=2.0,
            jitter=0,  # Disable jitter for predictable test
        )

        assert config.get_delay(0) == 1.0  # 1 * 2^0 = 1
        assert config.get_delay(1) == 2.0  # 1 * 2^1 = 2
        assert config.get_delay(2) == 4.0  # 1 * 2^2 = 4

    def test_get_delay_respects_max(self):
        """Test that delay respects max_delay."""
        config = RetryConfig(
            base_delay=1.0,
            exponential_base=2.0,
            max_delay=5.0,
            jitter=0,
        )

        assert config.get_delay(5) == 5.0  # Would be 32, capped at 5

    def test_get_delay_with_jitter(self):
        """Test that jitter adds randomness."""
        config = RetryConfig(
            base_delay=1.0,
            jitter=0.5,
        )

        # With jitter, delay should vary
        delays = [config.get_delay(0) for _ in range(10)]
        # Not all delays should be exactly 1.0
        assert len(set(delays)) > 1


class TestWithRetryDecorator:
    """Tests for @with_retry decorator."""

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self):
        """Test that successful calls don't retry."""
        call_count = 0

        @with_retry()
        async def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await successful_func()

        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Test retry on ConnectionError."""
        call_count = 0

        @with_retry(max_attempts=3)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return "success"

        # Use short delays for test
        with patch("voice_pipeline.utils.retry.LLM_RETRY_CONFIG") as mock_config:
            mock_config.max_attempts = 3
            mock_config.base_delay = 0.01
            mock_config.max_delay = 0.1
            mock_config.jitter = 0
            mock_config.exponential_base = 2.0
            mock_config.retryable_exceptions = RETRYABLE_EXCEPTIONS
            mock_config.on_retry = None
            mock_config.get_delay = lambda attempt: 0.01

            config = RetryConfig(
                max_attempts=3,
                base_delay=0.01,
                max_delay=0.1,
                jitter=0,
            )

            @with_retry(config=config)
            async def flaky_func2():
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("Connection failed")
                return "success"

            call_count = 0
            result = await flaky_func2()

        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted_raises(self):
        """Test that exhausted retries raise the exception."""
        call_count = 0

        config = RetryConfig(
            max_attempts=2,
            base_delay=0.01,
            jitter=0,
        )

        @with_retry(config=config)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError):
            await always_fails()

        assert call_count == 2  # Tried twice

    @pytest.mark.asyncio
    async def test_non_retryable_exception_raises_immediately(self):
        """Test that non-retryable exceptions raise immediately."""
        call_count = 0

        @with_retry()
        async def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")

        with pytest.raises(ValueError):
            await raises_value_error()

        assert call_count == 1  # Only one try

    @pytest.mark.asyncio
    async def test_custom_retryable_exceptions(self):
        """Test custom retryable exceptions."""
        call_count = 0

        config = RetryConfig(
            max_attempts=2,
            base_delay=0.01,
            jitter=0,
            retryable_exceptions=(ValueError,),
        )

        @with_retry(config=config)
        async def raises_value_error():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Custom retryable")
            return "success"

        result = await raises_value_error()

        assert result == "success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_on_retry_callback(self):
        """Test that on_retry callback is called."""
        retry_calls = []

        def on_retry(exc, attempt, delay):
            retry_calls.append((type(exc).__name__, attempt, delay))

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.01,
            jitter=0,
            on_retry=on_retry,
        )

        call_count = 0

        @with_retry(config=config)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Flaky")
            return "success"

        await flaky_func()

        assert len(retry_calls) == 2  # Called before 2nd and 3rd attempt
        assert retry_calls[0][0] == "ConnectionError"
        assert retry_calls[0][1] == 1  # First retry


class TestRetryAsync:
    """Tests for retry_async function."""

    @pytest.mark.asyncio
    async def test_retry_async_success(self):
        """Test retry_async with successful function."""
        async def success():
            return "result"

        result = await retry_async(success)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_retry_async_with_args(self):
        """Test retry_async passes arguments."""
        async def add(a, b):
            return a + b

        result = await retry_async(add, 1, 2)
        assert result == 3


class TestAgentLoopRetry:
    """Tests for AgentLoop retry integration."""

    @pytest.fixture
    def mock_llm_flaky(self):
        """Create a mock LLM that fails then succeeds."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False

        call_count = 0

        async def flaky_generate(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Temporary failure")
            return "Success after retry"

        llm.generate = flaky_generate
        llm._call_count = lambda: call_count
        return llm

    @pytest.mark.asyncio
    async def test_agent_loop_retries_llm_calls(self, mock_llm_flaky):
        """Test that AgentLoop retries LLM calls on failure."""
        from voice_pipeline.agents.loop import AgentLoop

        config = RetryConfig(
            max_attempts=3,
            base_delay=0.01,
            jitter=0,
        )

        loop = AgentLoop(llm=mock_llm_flaky, retry_config=config)

        result = await loop.run("Test")

        # Should succeed after retry
        assert "Success" in result

    @pytest.mark.asyncio
    async def test_agent_loop_default_retry_config(self):
        """Test that AgentLoop uses default retry config."""
        from voice_pipeline.agents.loop import AgentLoop

        llm = AsyncMock()
        llm.supports_tools.return_value = False

        loop = AgentLoop(llm=llm)

        assert loop.retry_config is not None
        assert loop.retry_config.max_attempts == 3

    @pytest.mark.asyncio
    async def test_agent_loop_custom_retry_config(self):
        """Test that AgentLoop accepts custom retry config."""
        from voice_pipeline.agents.loop import AgentLoop

        llm = AsyncMock()
        llm.supports_tools.return_value = False

        config = RetryConfig(max_attempts=5)
        loop = AgentLoop(llm=llm, retry_config=config)

        assert loop.retry_config.max_attempts == 5


class TestCustomExceptions:
    """Tests for custom retry exceptions."""

    def test_rate_limit_error(self):
        """Test RateLimitError with retry_after."""
        error = RateLimitError("Too many requests", retry_after=30.0)
        assert str(error) == "Too many requests"
        assert error.retry_after == 30.0

    def test_service_unavailable_error(self):
        """Test ServiceUnavailableError."""
        error = ServiceUnavailableError("Service down")
        assert str(error) == "Service down"
