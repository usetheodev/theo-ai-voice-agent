"""Tests for circuit breaker utilities (Sprint 5)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time

from voice_pipeline.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitState,
    with_circuit_breaker,
    LLM_CIRCUIT_BREAKER,
)


class TestCircuitBreakerConfig:
    """Tests for CircuitBreakerConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout == 30.0
        assert config.monitored_exceptions == (Exception,)
        assert config.on_state_change is None

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout=10.0,
            monitored_exceptions=(ConnectionError, TimeoutError),
        )
        assert config.failure_threshold == 3
        assert config.success_threshold == 1
        assert config.timeout == 10.0
        assert config.monitored_exceptions == (ConnectionError, TimeoutError)


class TestCircuitBreakerStates:
    """Tests for circuit breaker state transitions."""

    def test_initial_state_is_closed(self):
        """Test that breaker starts in closed state."""
        breaker = CircuitBreaker()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.is_closed
        assert not breaker.is_open
        assert not breaker.is_half_open

    @pytest.mark.asyncio
    async def test_remains_closed_on_success(self):
        """Test that successful calls keep circuit closed."""
        breaker = CircuitBreaker()

        async def success():
            return "ok"

        for _ in range(10):
            result = await breaker.call(success)
            assert result == "ok"

        assert breaker.is_closed

    @pytest.mark.asyncio
    async def test_opens_after_failure_threshold(self):
        """Test that circuit opens after threshold failures."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(config=config, name="test")

        async def failing():
            raise ConnectionError("Failed")

        # Should fail 3 times then open
        for i in range(3):
            with pytest.raises(ConnectionError):
                await breaker.call(failing)

        assert breaker.is_open

    @pytest.mark.asyncio
    async def test_open_circuit_fails_fast(self):
        """Test that open circuit raises immediately."""
        config = CircuitBreakerConfig(failure_threshold=1, timeout=60.0)
        breaker = CircuitBreaker(config=config)

        async def failing():
            raise ConnectionError("Failed")

        # Open the circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing)

        assert breaker.is_open

        # Next call should fail fast
        with pytest.raises(CircuitBreakerError) as exc_info:
            await breaker.call(failing)

        assert "is open" in str(exc_info.value)
        assert exc_info.value.time_until_retry is not None

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self):
        """Test that circuit transitions to half-open after timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=1,  # Only need 1 success to close
            timeout=0.1,
        )
        breaker = CircuitBreaker(config=config)

        async def failing():
            raise ConnectionError("Failed")

        # Open the circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing)

        assert breaker.is_open

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Check state (should transition on next call attempt)
        async def success():
            return "ok"

        result = await breaker.call(success)
        assert result == "ok"
        # After success in half-open, should be closed
        assert breaker.is_closed

    @pytest.mark.asyncio
    async def test_half_open_closes_on_success(self):
        """Test that half-open circuit closes after success threshold."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            success_threshold=2,
            timeout=0.05,
        )
        breaker = CircuitBreaker(config=config)

        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("First failure")
            return "ok"

        # First call fails, opens circuit
        with pytest.raises(ConnectionError):
            await breaker.call(flaky)

        assert breaker.is_open

        # Wait for timeout
        await asyncio.sleep(0.1)

        # Next calls should succeed and close circuit
        result = await breaker.call(flaky)
        assert result == "ok"

        result = await breaker.call(flaky)
        assert result == "ok"

        assert breaker.is_closed

    @pytest.mark.asyncio
    async def test_half_open_returns_to_open_on_failure(self):
        """Test that half-open circuit reopens on failure."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout=0.05,
        )
        breaker = CircuitBreaker(config=config)

        async def always_fails():
            raise ConnectionError("Always fails")

        # Open circuit
        with pytest.raises(ConnectionError):
            await breaker.call(always_fails)

        assert breaker.is_open

        # Wait for timeout
        await asyncio.sleep(0.1)

        # Failure in half-open should return to open
        with pytest.raises(ConnectionError):
            await breaker.call(always_fails)

        assert breaker.is_open


class TestCircuitBreakerReset:
    """Tests for manual reset functionality."""

    @pytest.mark.asyncio
    async def test_manual_reset(self):
        """Test manual reset to closed state."""
        config = CircuitBreakerConfig(failure_threshold=1)
        breaker = CircuitBreaker(config=config)

        async def failing():
            raise ConnectionError("Failed")

        # Open the circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing)

        assert breaker.is_open

        # Manual reset
        breaker.reset()

        assert breaker.is_closed
        assert breaker.get_stats()["failure_count"] == 0


class TestCircuitBreakerStats:
    """Tests for statistics functionality."""

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting circuit breaker statistics."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = CircuitBreaker(config=config, name="stats-test")

        stats = breaker.get_stats()

        assert stats["name"] == "stats-test"
        assert stats["state"] == "closed"
        assert stats["failure_count"] == 0
        assert stats["failure_threshold"] == 3
        assert stats["timeout"] == 30.0

    @pytest.mark.asyncio
    async def test_stats_update_on_failures(self):
        """Test that stats update on failures."""
        config = CircuitBreakerConfig(failure_threshold=5)
        breaker = CircuitBreaker(config=config)

        async def failing():
            raise ConnectionError("Failed")

        for _ in range(3):
            with pytest.raises(ConnectionError):
                await breaker.call(failing)

        stats = breaker.get_stats()
        assert stats["failure_count"] == 3
        assert stats["state"] == "closed"  # Not yet at threshold


class TestCircuitBreakerCallback:
    """Tests for state change callback."""

    @pytest.mark.asyncio
    async def test_on_state_change_callback(self):
        """Test that callback is called on state transitions."""
        transitions = []

        def on_change(old_state, new_state):
            transitions.append((old_state.value, new_state.value))

        config = CircuitBreakerConfig(
            failure_threshold=1,
            timeout=0.05,
            on_state_change=on_change,
        )
        breaker = CircuitBreaker(config=config)

        async def failing():
            raise ConnectionError("Failed")

        async def success():
            return "ok"

        # Open circuit
        with pytest.raises(ConnectionError):
            await breaker.call(failing)

        assert ("closed", "open") in transitions

        # Wait and trigger half-open
        await asyncio.sleep(0.1)
        await breaker.call(success)

        # Should have half_open -> closed transition
        assert any("half_open" in t[0] or "half_open" in t[1] for t in transitions)


class TestCircuitBreakerContextManager:
    """Tests for async context manager usage."""

    @pytest.mark.asyncio
    async def test_context_manager_success(self):
        """Test using circuit breaker as context manager."""
        breaker = CircuitBreaker()

        async with breaker:
            result = "ok"

        assert result == "ok"
        assert breaker.is_closed

    @pytest.mark.asyncio
    async def test_context_manager_failure(self):
        """Test context manager with failure."""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(config=config)

        with pytest.raises(ConnectionError):
            async with breaker:
                raise ConnectionError("Failed")

        assert breaker.get_stats()["failure_count"] == 1


class TestCircuitBreakerDecorator:
    """Tests for @with_circuit_breaker decorator."""

    @pytest.mark.asyncio
    async def test_decorator_success(self):
        """Test decorator with successful function."""
        breaker = CircuitBreaker(name="decorator-test")

        @with_circuit_breaker(breaker)
        async def my_func(x):
            return x * 2

        result = await my_func(5)
        assert result == 10

    @pytest.mark.asyncio
    async def test_decorator_failure(self):
        """Test decorator tracks failures."""
        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(config=config)

        @with_circuit_breaker(breaker)
        async def failing_func():
            raise ConnectionError("Failed")

        with pytest.raises(ConnectionError):
            await failing_func()

        with pytest.raises(ConnectionError):
            await failing_func()

        assert breaker.is_open


class TestAgentLoopCircuitBreaker:
    """Tests for AgentLoop circuit breaker integration."""

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM."""
        llm = AsyncMock()
        llm.supports_tools.return_value = False
        return llm

    @pytest.mark.asyncio
    async def test_agent_loop_accepts_circuit_breaker(self, mock_llm):
        """Test that AgentLoop accepts circuit_breaker parameter."""
        from voice_pipeline.agents.loop import AgentLoop

        breaker = CircuitBreaker(name="agent-llm")
        loop = AgentLoop(llm=mock_llm, circuit_breaker=breaker)

        assert loop.circuit_breaker is breaker

    @pytest.mark.asyncio
    async def test_agent_loop_uses_circuit_breaker(self, mock_llm):
        """Test that AgentLoop uses circuit breaker for LLM calls."""
        from voice_pipeline.agents.loop import AgentLoop

        config = CircuitBreakerConfig(failure_threshold=2)
        breaker = CircuitBreaker(config=config, name="agent-llm")

        # Make LLM fail
        mock_llm.generate.side_effect = ConnectionError("LLM unavailable")

        from voice_pipeline.utils.retry import RetryConfig
        retry_config = RetryConfig(max_attempts=1, base_delay=0.01)

        loop = AgentLoop(
            llm=mock_llm,
            circuit_breaker=breaker,
            retry_config=retry_config,
        )

        # First call should fail and count
        result = await loop.run("Test")
        assert "Error" in result

        # Second call should fail and open circuit
        result = await loop.run("Test 2")
        assert "Error" in result

        # Circuit should be open
        assert breaker.is_open

    @pytest.mark.asyncio
    async def test_agent_loop_circuit_breaker_fails_fast(self, mock_llm):
        """Test that open circuit fails fast."""
        from voice_pipeline.agents.loop import AgentLoop

        config = CircuitBreakerConfig(failure_threshold=1, timeout=60.0)
        breaker = CircuitBreaker(config=config, name="agent-llm")

        mock_llm.generate.side_effect = ConnectionError("LLM unavailable")

        from voice_pipeline.utils.retry import RetryConfig
        retry_config = RetryConfig(max_attempts=1, base_delay=0.01)

        loop = AgentLoop(
            llm=mock_llm,
            circuit_breaker=breaker,
            retry_config=retry_config,
        )

        # Open the circuit
        await loop.run("Test")
        assert breaker.is_open

        # Reset mock to count calls
        mock_llm.generate.reset_mock()

        # Next call should fail fast (not call LLM)
        result = await loop.run("Test 2")

        # LLM should not have been called
        mock_llm.generate.assert_not_called()
        assert "Error" in result


class TestDefaultCircuitBreaker:
    """Tests for default LLM circuit breaker."""

    def test_llm_circuit_breaker_exists(self):
        """Test that LLM_CIRCUIT_BREAKER is defined."""
        assert LLM_CIRCUIT_BREAKER is not None
        assert LLM_CIRCUIT_BREAKER.name == "llm"

    def test_llm_circuit_breaker_config(self):
        """Test LLM circuit breaker configuration."""
        stats = LLM_CIRCUIT_BREAKER.get_stats()
        assert stats["failure_threshold"] == 5
        assert stats["success_threshold"] == 2
        assert stats["timeout"] == 30.0
