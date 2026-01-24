"""Tests for VoiceRunnable pattern."""

import asyncio
from typing import AsyncIterator, Optional

import pytest

from voice_pipeline.runnable import (
    RunnableConfig,
    VoiceFallback,
    VoiceFilter,
    VoiceLambda,
    VoiceParallel,
    VoicePassthrough,
    VoiceRaceParallel,
    VoiceRetry,
    VoiceRouter,
    VoiceRunnable,
    VoiceSequence,
    VoiceStreamingSequence,
    ensure_config,
)


# ==================== Mock Runnables ====================


class MockASR(VoiceRunnable[bytes, str]):
    """Mock ASR that returns a fixed transcription."""

    name = "MockASR"

    def __init__(self, transcription: str = "Hello world"):
        self.transcription = transcription
        self.call_count = 0

    async def ainvoke(
        self, input: bytes, config: Optional[RunnableConfig] = None
    ) -> str:
        self.call_count += 1
        return self.transcription

    async def astream(
        self, input: bytes, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[str]:
        self.call_count += 1
        for word in self.transcription.split():
            yield word


class MockLLM(VoiceRunnable[str, str]):
    """Mock LLM that echoes input with prefix."""

    name = "MockLLM"

    def __init__(self, prefix: str = "Response: "):
        self.prefix = prefix
        self.call_count = 0

    async def ainvoke(
        self, input: str, config: Optional[RunnableConfig] = None
    ) -> str:
        self.call_count += 1
        return f"{self.prefix}{input}"

    async def astream(
        self, input: str, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[str]:
        self.call_count += 1
        yield self.prefix
        yield input


class MockTTS(VoiceRunnable[str, bytes]):
    """Mock TTS that returns encoded text as bytes."""

    name = "MockTTS"

    def __init__(self):
        self.call_count = 0

    async def ainvoke(
        self, input: str, config: Optional[RunnableConfig] = None
    ) -> bytes:
        self.call_count += 1
        return input.encode("utf-8")

    async def astream(
        self, input: str, config: Optional[RunnableConfig] = None
    ) -> AsyncIterator[bytes]:
        self.call_count += 1
        for word in input.split():
            yield word.encode("utf-8")


class FailingRunnable(VoiceRunnable[str, str]):
    """Runnable that fails a specified number of times."""

    name = "FailingRunnable"

    def __init__(self, fail_count: int = 1):
        self.fail_count = fail_count
        self.attempts = 0

    async def ainvoke(
        self, input: str, config: Optional[RunnableConfig] = None
    ) -> str:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise ValueError(f"Intentional failure #{self.attempts}")
        return f"Success on attempt {self.attempts}: {input}"


class SlowRunnable(VoiceRunnable[str, str]):
    """Runnable that takes time to execute."""

    name = "SlowRunnable"

    def __init__(self, delay: float = 0.1, result: str = "done"):
        self.delay = delay
        self.result = result

    async def ainvoke(
        self, input: str, config: Optional[RunnableConfig] = None
    ) -> str:
        await asyncio.sleep(self.delay)
        return self.result


# ==================== Tests ====================


class TestVoiceRunnable:
    """Tests for base VoiceRunnable functionality."""

    @pytest.mark.asyncio
    async def test_ainvoke_basic(self):
        """Test basic ainvoke."""
        asr = MockASR(transcription="Test input")
        result = await asr.ainvoke(b"audio")
        assert result == "Test input"
        assert asr.call_count == 1

    @pytest.mark.asyncio
    async def test_astream_basic(self):
        """Test basic astream."""
        asr = MockASR(transcription="Hello world")
        chunks = [chunk async for chunk in asr.astream(b"audio")]
        assert chunks == ["Hello", "world"]

    @pytest.mark.asyncio
    async def test_abatch(self):
        """Test abatch executes all inputs."""
        asr = MockASR(transcription="Result")
        results = await asr.abatch([b"a1", b"a2", b"a3"])
        assert len(results) == 3
        assert all(r == "Result" for r in results)
        assert asr.call_count == 3

    @pytest.mark.asyncio
    async def test_abatch_with_concurrency_limit(self):
        """Test abatch respects max_concurrency."""
        slow = SlowRunnable(delay=0.05, result="done")
        config = RunnableConfig(max_concurrency=2)

        start = asyncio.get_event_loop().time()
        results = await slow.abatch(
            ["a", "b", "c", "d"], config, max_concurrency=2
        )
        elapsed = asyncio.get_event_loop().time() - start

        assert len(results) == 4
        # With concurrency 2 and 4 items, should take ~2 batches
        assert elapsed >= 0.1  # At least 2 * 0.05

    def test_sync_invoke(self):
        """Test sync invoke (wraps ainvoke)."""
        asr = MockASR(transcription="Sync result")
        result = asr.invoke(b"audio")
        assert result == "Sync result"


class TestVoiceSequence:
    """Tests for VoiceSequence (| operator)."""

    @pytest.mark.asyncio
    async def test_pipe_operator(self):
        """Test | operator creates sequence."""
        asr = MockASR(transcription="Hello")
        llm = MockLLM(prefix="LLM: ")

        chain = asr | llm
        assert isinstance(chain, VoiceSequence)
        assert len(chain.steps) == 2

    @pytest.mark.asyncio
    async def test_sequence_ainvoke(self):
        """Test sequence executes all steps in order."""
        asr = MockASR(transcription="Input")
        llm = MockLLM(prefix="Processed: ")
        tts = MockTTS()

        chain = asr | llm | tts
        result = await chain.ainvoke(b"audio")

        assert result == b"Processed: Input"
        assert asr.call_count == 1
        assert llm.call_count == 1
        assert tts.call_count == 1

    @pytest.mark.asyncio
    async def test_sequence_astream(self):
        """Test sequence streaming (last step streams)."""
        asr = MockASR(transcription="Hello world")
        llm = MockLLM(prefix="Echo: ")
        tts = MockTTS()

        chain = asr | llm | tts
        chunks = [chunk async for chunk in chain.astream(b"audio")]

        # TTS splits by words
        assert len(chunks) == 3  # "Echo:", "Hello", "world"

    @pytest.mark.asyncio
    async def test_triple_pipe(self):
        """Test chaining three runnables."""
        r1 = MockLLM(prefix="A:")
        r2 = MockLLM(prefix="B:")
        r3 = MockLLM(prefix="C:")

        chain = r1 | r2 | r3
        result = await chain.ainvoke("X")
        assert result == "C:B:A:X"

    @pytest.mark.asyncio
    async def test_sequence_properties(self):
        """Test sequence first/middle/last properties."""
        asr = MockASR()
        llm = MockLLM()
        tts = MockTTS()

        chain = asr | llm | tts

        assert chain.first is asr
        assert chain.last is tts
        assert chain.middle == [llm]

    @pytest.mark.asyncio
    async def test_pipe_method_alternative(self):
        """Test pipe() method as alternative to | operator."""
        asr = MockASR(transcription="Test")
        llm = MockLLM(prefix="P:")
        tts = MockTTS()

        chain = asr.pipe(llm, tts)
        result = await chain.ainvoke(b"audio")

        assert result == b"P:Test"


class TestVoiceStreamingSequence:
    """Tests for VoiceStreamingSequence (full streaming)."""

    @pytest.mark.asyncio
    async def test_streaming_sequence(self):
        """Test streaming sequence with two steps."""
        asr = MockASR(transcription="Hello world")
        llm = MockLLM(prefix="Echo: ")

        chain = VoiceStreamingSequence([asr, llm])
        chunks = [chunk async for chunk in chain.astream(b"audio")]

        # Should have chunks from both streams
        assert len(chunks) > 0


class TestVoiceParallel:
    """Tests for VoiceParallel."""

    @pytest.mark.asyncio
    async def test_parallel_ainvoke(self):
        """Test parallel execution returns dict."""
        asr1 = MockASR(transcription="ASR1")
        asr2 = MockASR(transcription="ASR2")

        parallel = VoiceParallel(first=asr1, second=asr2)
        result = await parallel.ainvoke(b"audio")

        assert isinstance(result, dict)
        assert result["first"] == "ASR1"
        assert result["second"] == "ASR2"

    @pytest.mark.asyncio
    async def test_parallel_timing(self):
        """Test parallel runs concurrently."""
        slow1 = SlowRunnable(delay=0.1, result="A")
        slow2 = SlowRunnable(delay=0.1, result="B")

        parallel = VoiceParallel(a=slow1, b=slow2)

        start = asyncio.get_event_loop().time()
        result = await parallel.ainvoke("input")
        elapsed = asyncio.get_event_loop().time() - start

        assert result == {"a": "A", "b": "B"}
        # Should complete in ~0.1s, not 0.2s (parallel)
        assert elapsed < 0.15

    @pytest.mark.asyncio
    async def test_parallel_astream(self):
        """Test parallel streaming yields as results arrive."""
        slow1 = SlowRunnable(delay=0.05, result="A")
        slow2 = SlowRunnable(delay=0.1, result="B")

        parallel = VoiceParallel(fast=slow1, slow=slow2)
        updates = [update async for update in parallel.astream("input")]

        assert len(updates) == 2
        # First update should have "fast" completed
        assert "fast" in updates[0]


class TestVoiceRaceParallel:
    """Tests for VoiceRaceParallel."""

    @pytest.mark.asyncio
    async def test_race_returns_first(self):
        """Test race returns first completed result."""
        fast = SlowRunnable(delay=0.01, result="FAST")
        slow = SlowRunnable(delay=0.1, result="SLOW")

        race = VoiceRaceParallel(fast=fast, slow=slow)
        result = await race.ainvoke("input")

        assert result == "FAST"

    @pytest.mark.asyncio
    async def test_race_returns_winner_name(self):
        """Test race can return winner name."""
        fast = SlowRunnable(delay=0.01, result="FAST")
        slow = SlowRunnable(delay=0.1, result="SLOW")

        race = VoiceRaceParallel(
            fast=fast, slow=slow, return_winner_name=True
        )
        name, result = await race.ainvoke("input")

        assert name == "fast"
        assert result == "FAST"


class TestVoicePassthrough:
    """Tests for VoicePassthrough and related utilities."""

    @pytest.mark.asyncio
    async def test_passthrough_returns_input(self):
        """Test passthrough returns input unchanged."""
        pt = VoicePassthrough()
        result = await pt.ainvoke({"key": "value"})
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_passthrough_with_fixed_value(self):
        """Test passthrough with fixed value."""
        pt = VoicePassthrough(value={"fixed": True})
        result = await pt.ainvoke("anything")
        assert result == {"fixed": True}


class TestVoiceLambda:
    """Tests for VoiceLambda."""

    @pytest.mark.asyncio
    async def test_lambda_sync_function(self):
        """Test lambda with sync function."""
        upper = VoiceLambda(lambda x: x.upper())
        result = await upper.ainvoke("hello")
        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_lambda_async_function(self):
        """Test lambda with async function."""

        async def async_upper(x):
            return x.upper()

        upper = VoiceLambda(async_upper)
        result = await upper.ainvoke("hello")
        assert result == "HELLO"

    @pytest.mark.asyncio
    async def test_lambda_in_chain(self):
        """Test lambda as part of chain."""
        asr = MockASR(transcription="hello world")
        upper = VoiceLambda(lambda x: x.upper())
        tts = MockTTS()

        chain = asr | upper | tts
        result = await chain.ainvoke(b"audio")
        assert result == b"HELLO WORLD"


class TestVoiceRouter:
    """Tests for VoiceRouter."""

    @pytest.mark.asyncio
    async def test_router_routes_correctly(self):
        """Test router selects correct runnable."""
        en_handler = MockLLM(prefix="EN: ")
        pt_handler = MockLLM(prefix="PT: ")

        router = VoiceRouter(
            condition=lambda x: x.get("lang", "en"),
            routes={
                "en": en_handler,
                "pt": pt_handler,
            },
        )

        result_en = await router.ainvoke({"lang": "en", "text": "Hello"})
        result_pt = await router.ainvoke({"lang": "pt", "text": "Hello"})

        assert result_en.startswith("EN:")
        assert result_pt.startswith("PT:")

    @pytest.mark.asyncio
    async def test_router_with_default(self):
        """Test router uses default for unknown routes."""
        default = MockLLM(prefix="DEFAULT: ")
        router = VoiceRouter(
            condition=lambda x: x.get("lang"),
            routes={"en": MockLLM(prefix="EN: ")},
            default=default,
        )

        result = await router.ainvoke({"lang": "fr", "text": "Bonjour"})
        assert result.startswith("DEFAULT:")


class TestVoiceFilter:
    """Tests for VoiceFilter."""

    @pytest.mark.asyncio
    async def test_filter_passes(self):
        """Test filter passes matching input."""
        f = VoiceFilter(condition=lambda x: len(x) > 5)
        result = await f.ainvoke("Hello World")
        assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_filter_blocks(self):
        """Test filter returns None for non-matching."""
        f = VoiceFilter(condition=lambda x: len(x) > 5)
        result = await f.ainvoke("Hi")
        assert result is None


class TestVoiceRetry:
    """Tests for VoiceRetry."""

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failures(self):
        """Test retry eventually succeeds."""
        failing = FailingRunnable(fail_count=2)
        retry = VoiceRetry(failing, max_retries=3, backoff=0.01)

        result = await retry.ainvoke("test")
        assert "Success on attempt 3" in result

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        """Test retry raises after max retries."""
        failing = FailingRunnable(fail_count=10)
        retry = VoiceRetry(failing, max_retries=2, backoff=0.01)

        with pytest.raises(ValueError, match="Intentional failure"):
            await retry.ainvoke("test")


class TestVoiceFallback:
    """Tests for VoiceFallback."""

    @pytest.mark.asyncio
    async def test_fallback_uses_primary(self):
        """Test fallback uses primary when it works."""
        primary = MockLLM(prefix="PRIMARY: ")
        backup = MockLLM(prefix="BACKUP: ")

        fb = VoiceFallback(primary=primary, fallbacks=[backup])
        result = await fb.ainvoke("test")

        assert result.startswith("PRIMARY:")
        assert primary.call_count == 1
        assert backup.call_count == 0

    @pytest.mark.asyncio
    async def test_fallback_uses_backup(self):
        """Test fallback uses backup when primary fails."""
        primary = FailingRunnable(fail_count=10)
        backup = MockLLM(prefix="BACKUP: ")

        fb = VoiceFallback(primary=primary, fallbacks=[backup])
        result = await fb.ainvoke("test")

        assert result.startswith("BACKUP:")


class TestRunnableConfig:
    """Tests for RunnableConfig."""

    def test_config_merge(self):
        """Test config merge combines values."""
        c1 = RunnableConfig(
            tags=["a", "b"],
            metadata={"key1": "value1"},
        )
        c2 = RunnableConfig(
            tags=["c"],
            metadata={"key2": "value2"},
            run_id="test-123",
        )

        merged = c1.merge(c2)

        assert set(merged.tags) == {"a", "b", "c"}
        assert merged.metadata == {"key1": "value1", "key2": "value2"}
        assert merged.run_id == "test-123"

    def test_config_with_methods(self):
        """Test config with_* methods."""
        config = RunnableConfig()

        config = config.with_tags(["test"])
        assert "test" in config.tags

        config = config.with_metadata(key="value")
        assert config.metadata["key"] == "value"

    def test_ensure_config(self):
        """Test ensure_config creates default."""
        assert ensure_config(None) is not None
        assert isinstance(ensure_config(None), RunnableConfig)

        existing = RunnableConfig(run_id="test")
        assert ensure_config(existing) is existing


class TestRunWithConfig:
    """Tests for with_config functionality."""

    @pytest.mark.asyncio
    async def test_runnable_with_config(self):
        """Test runnable with pre-configured config."""
        asr = MockASR(transcription="Test")
        config = RunnableConfig(
            run_id="test-run",
            metadata={"source": "test"},
        )

        configured = asr.with_config(config)
        result = await configured.ainvoke(b"audio")

        assert result == "Test"

    @pytest.mark.asyncio
    async def test_bound_runnable(self):
        """Test bound runnable with pre-set kwargs."""
        llm = MockLLM(prefix="Bound: ")

        # Note: bind() works with dict inputs
        bound = llm.bind(extra="value")
        result = await bound.ainvoke({"text": "Test"})

        # MockLLM converts dict to string
        assert "Bound:" in result
