"""Tests for Voice Pipeline callbacks."""

import asyncio
from io import StringIO
from typing import Any

import pytest

from voice_pipeline.callbacks import (
    CallbackManager,
    LoggingHandler,
    MetricsHandler,
    PipelineMetrics,
    RunContext,
    StdOutHandler,
    VoiceCallbackHandler,
    run_with_callbacks,
)
from voice_pipeline.callbacks.context import (
    child_run,
    get_callback_manager,
    get_run_context,
)
from voice_pipeline.interfaces import AudioChunk, LLMChunk, TranscriptionResult


# ==================== Test Helpers ====================


class RecordingHandler(VoiceCallbackHandler):
    """Handler that records all events for testing."""

    def __init__(self):
        self.events: list[tuple[str, Any]] = []

    def _record(self, event: str, *args):
        self.events.append((event, args))

    async def on_pipeline_start(self, ctx):
        self._record("pipeline_start", ctx.run_id)

    async def on_pipeline_end(self, ctx, output=None):
        self._record("pipeline_end", ctx.run_id, output)

    async def on_pipeline_error(self, ctx, error):
        self._record("pipeline_error", ctx.run_id, error)

    async def on_asr_start(self, ctx, input):
        self._record("asr_start", len(input))

    async def on_asr_end(self, ctx, result):
        self._record("asr_end", result.text)

    async def on_llm_start(self, ctx, messages):
        self._record("llm_start", len(messages))

    async def on_llm_token(self, ctx, token):
        self._record("llm_token", token)

    async def on_llm_end(self, ctx, response):
        self._record("llm_end", response)

    async def on_tts_start(self, ctx, text):
        self._record("tts_start", text)

    async def on_tts_chunk(self, ctx, chunk):
        self._record("tts_chunk", len(chunk.data))

    async def on_tts_end(self, ctx):
        self._record("tts_end")

    async def on_barge_in(self, ctx):
        self._record("barge_in")


class FailingHandler(VoiceCallbackHandler):
    """Handler that raises errors."""

    async def on_asr_start(self, ctx, input):
        raise ValueError("Intentional failure")


# ==================== Tests ====================


class TestRunContext:
    """Tests for RunContext."""

    def test_context_creation(self):
        """Test creating a run context."""
        ctx = RunContext(run_name="test-run")

        assert ctx.run_id is not None
        assert len(ctx.run_id) == 36  # UUID format
        assert ctx.run_name == "test-run"
        assert ctx.parent_run_id is None

    def test_context_elapsed_time(self):
        """Test elapsed time calculation."""
        import time

        ctx = RunContext()
        time.sleep(0.01)

        assert ctx.elapsed_ms > 0
        assert ctx.elapsed_ms < 1000  # Should be quick

    def test_context_with_metadata(self):
        """Test context with metadata and tags."""
        ctx = RunContext(
            metadata={"key": "value"},
            tags=["test", "unit"],
        )

        assert ctx.metadata == {"key": "value"}
        assert "test" in ctx.tags


class TestCallbackManager:
    """Tests for CallbackManager."""

    @pytest.mark.asyncio
    async def test_dispatch_to_handlers(self):
        """Test events are dispatched to handlers."""
        handler = RecordingHandler()
        manager = CallbackManager([handler], run_in_background=False)
        ctx = manager.create_context()

        await manager.on_asr_start(ctx, b"audio")
        await manager.on_asr_end(
            ctx, TranscriptionResult(text="Hello", is_final=True)
        )

        assert len(handler.events) == 2
        assert handler.events[0][0] == "asr_start"
        assert handler.events[1][0] == "asr_end"
        assert handler.events[1][1][0] == "Hello"

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        """Test events dispatched to multiple handlers."""
        handler1 = RecordingHandler()
        handler2 = RecordingHandler()
        manager = CallbackManager([handler1, handler2], run_in_background=False)
        ctx = manager.create_context()

        await manager.on_llm_start(ctx, [{"role": "user", "content": "Hi"}])

        assert len(handler1.events) == 1
        assert len(handler2.events) == 1

    @pytest.mark.asyncio
    async def test_handler_error_doesnt_break_others(self):
        """Test that one failing handler doesn't break others."""
        failing = FailingHandler()
        recording = RecordingHandler()
        manager = CallbackManager(
            [failing, recording], run_in_background=False
        )
        ctx = manager.create_context()

        # Should not raise
        await manager.on_asr_start(ctx, b"audio")

        # Recording handler should still work
        assert len(recording.events) == 1

    @pytest.mark.asyncio
    async def test_add_remove_handler(self):
        """Test adding and removing handlers."""
        manager = CallbackManager()
        handler = RecordingHandler()

        manager.add_handler(handler)
        assert handler in manager.handlers

        manager.remove_handler(handler)
        assert handler not in manager.handlers

    @pytest.mark.asyncio
    async def test_create_context(self):
        """Test context creation through manager."""
        manager = CallbackManager()

        ctx = manager.create_context(
            run_name="test",
            metadata={"key": "value"},
            tags=["test"],
        )

        assert ctx.run_name == "test"
        assert ctx.metadata == {"key": "value"}
        assert "test" in ctx.tags


class TestRunWithCallbacks:
    """Tests for run_with_callbacks context manager."""

    @pytest.mark.asyncio
    async def test_basic_usage(self):
        """Test basic context manager usage."""
        handler = RecordingHandler()

        async with run_with_callbacks([handler], run_name="test") as ctx:
            assert ctx.run_name == "test"
            assert get_run_context() is ctx
            assert get_callback_manager() is not None

        # Events should include start and end
        events = [e[0] for e in handler.events]
        assert "pipeline_start" in events
        assert "pipeline_end" in events

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """Test context manager handles errors."""
        handler = RecordingHandler()

        with pytest.raises(ValueError, match="Test error"):
            async with run_with_callbacks([handler]):
                raise ValueError("Test error")

        events = [e[0] for e in handler.events]
        assert "pipeline_start" in events
        assert "pipeline_error" in events

    @pytest.mark.asyncio
    async def test_nested_contexts(self):
        """Test nested callback contexts."""
        outer_handler = RecordingHandler()
        inner_handler = RecordingHandler()

        async with run_with_callbacks([outer_handler], run_name="outer") as outer:
            async with run_with_callbacks(
                [inner_handler], run_name="inner"
            ) as inner:
                assert inner.parent_run_id == outer.run_id

    @pytest.mark.asyncio
    async def test_child_run(self):
        """Test child_run helper."""
        handler = RecordingHandler()

        async with run_with_callbacks([handler]) as parent:
            async with child_run("child-operation") as child:
                assert child.parent_run_id == parent.run_id
                assert child.run_name == "child-operation"


class TestMetricsHandler:
    """Tests for MetricsHandler."""

    @pytest.mark.asyncio
    async def test_basic_metrics(self):
        """Test basic metrics collection."""
        handler = MetricsHandler()

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()

            await manager.on_asr_start(ctx, b"audio" * 100)
            await manager.on_asr_end(
                ctx, TranscriptionResult(text="Test", is_final=True)
            )

        metrics = handler.get_metrics(ctx.run_id)
        assert metrics is not None
        assert metrics.asr.latency_ms is not None
        assert metrics.asr.item_count == 1

    @pytest.mark.asyncio
    async def test_llm_metrics(self):
        """Test LLM metrics collection."""
        handler = MetricsHandler()

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()

            await manager.on_llm_start(
                ctx, [{"role": "user", "content": "Hi"}]
            )
            await manager.on_llm_token(ctx, "Hello")
            await manager.on_llm_token(ctx, " world")
            await manager.on_llm_end(ctx, "Hello world")

        metrics = handler.get_metrics(ctx.run_id)
        assert metrics.llm.item_count == 2  # 2 tokens
        assert metrics.llm.time_to_first_ms is not None

    @pytest.mark.asyncio
    async def test_tts_metrics(self):
        """Test TTS metrics collection."""
        handler = MetricsHandler()

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()

            await manager.on_tts_start(ctx, "Hello world")
            await manager.on_tts_chunk(ctx, AudioChunk(data=b"audio1"))
            await manager.on_tts_chunk(ctx, AudioChunk(data=b"audio2"))
            await manager.on_tts_end(ctx)

        metrics = handler.get_metrics(ctx.run_id)
        assert metrics.tts.item_count == 2
        assert metrics.tts.byte_count == 12  # len("audio1") + len("audio2")

    @pytest.mark.asyncio
    async def test_metrics_callback(self):
        """Test on_metrics callback."""
        collected: list[PipelineMetrics] = []
        handler = MetricsHandler(on_metrics=lambda m: collected.append(m))

        async with run_with_callbacks([handler], run_in_background=False):
            pass

        assert len(collected) == 1
        assert collected[0].total_latency_ms is not None

    @pytest.mark.asyncio
    async def test_barge_in_count(self):
        """Test barge-in counting."""
        handler = MetricsHandler()

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()
            await manager.on_barge_in(ctx)
            await manager.on_barge_in(ctx)

        metrics = handler.get_metrics(ctx.run_id)
        assert metrics.barge_in_count == 2

    def test_metrics_to_dict(self):
        """Test metrics serialization."""
        metrics = PipelineMetrics(run_id="test-123", run_name="test")
        metrics.asr.item_count = 5

        d = metrics.to_dict()
        assert d["run_id"] == "test-123"
        assert d["run_name"] == "test"
        assert d["asr"]["item_count"] == 5


class TestStdOutHandler:
    """Tests for StdOutHandler."""

    @pytest.mark.asyncio
    async def test_basic_output(self):
        """Test basic stdout output."""
        output = StringIO()
        handler = StdOutHandler(output=output, use_colors=False)

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()
            await manager.on_asr_start(ctx, b"audio")

        text = output.getvalue()
        assert "PIPELINE_START" in text
        assert "ASR_START" in text

    @pytest.mark.asyncio
    async def test_with_timestamps(self):
        """Test output with timestamps."""
        output = StringIO()
        handler = StdOutHandler(
            output=output, use_colors=False, show_timestamps=True
        )

        async with run_with_callbacks([handler], run_in_background=False):
            pass

        text = output.getvalue()
        assert "ms]" in text  # Timestamp format

    @pytest.mark.asyncio
    async def test_token_output(self):
        """Test inline token output."""
        output = StringIO()
        handler = StdOutHandler(
            output=output, use_colors=False, show_tokens=True
        )

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()
            await manager.on_llm_start(
                ctx, [{"role": "user", "content": "Hi"}]
            )
            await manager.on_llm_token(ctx, "Hello")
            await manager.on_llm_token(ctx, " world")
            await manager.on_llm_end(ctx, "Hello world")

        text = output.getvalue()
        assert "Hello" in text


class TestLoggingHandler:
    """Tests for LoggingHandler."""

    @pytest.mark.asyncio
    async def test_basic_logging(self):
        """Test basic logging."""
        import logging

        # Create a handler to capture logs
        logs: list[logging.LogRecord] = []

        class ListHandler(logging.Handler):
            def emit(self, record):
                logs.append(record)

        logger = logging.getLogger("test_voice_pipeline")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(ListHandler())

        handler = LoggingHandler(logger=logger)

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()
            await manager.on_asr_start(ctx, b"audio")
            await manager.on_asr_end(
                ctx, TranscriptionResult(text="Test", is_final=True)
            )

        # Check logs were created
        messages = [log.message for log in logs]
        assert any("PIPELINE_START" in m for m in messages)
        assert any("ASR_START" in m for m in messages)
        assert any("ASR_END" in m for m in messages)

    @pytest.mark.asyncio
    async def test_error_logging(self):
        """Test error events are logged at ERROR level."""
        import logging

        logs: list[logging.LogRecord] = []

        class ListHandler(logging.Handler):
            def emit(self, record):
                logs.append(record)

        logger = logging.getLogger("test_voice_pipeline_error")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(ListHandler())

        handler = LoggingHandler(logger=logger)

        async with run_with_callbacks([handler], run_in_background=False) as ctx:
            manager = get_callback_manager()
            await manager.on_asr_error(ctx, ValueError("Test error"))

        error_logs = [log for log in logs if log.levelno == logging.ERROR]
        assert len(error_logs) >= 1


class TestBackgroundCallbacks:
    """Tests for background callback execution."""

    @pytest.mark.asyncio
    async def test_callbacks_run_in_background(self):
        """Test that callbacks run in background by default."""
        executed = []

        class SlowHandler(VoiceCallbackHandler):
            async def on_asr_start(self, ctx, input):
                await asyncio.sleep(0.1)
                executed.append("done")

        handler = SlowHandler()
        manager = CallbackManager([handler], run_in_background=True)
        ctx = manager.create_context()

        await manager.on_asr_start(ctx, b"audio")

        # Should return immediately without waiting
        assert len(executed) == 0

        # Wait for background tasks
        await manager.wait_for_callbacks()
        assert len(executed) == 1

    @pytest.mark.asyncio
    async def test_wait_for_callbacks_on_end(self):
        """Test that pipeline end waits for callbacks."""
        executed = []

        class SlowHandler(VoiceCallbackHandler):
            async def on_asr_start(self, ctx, input):
                await asyncio.sleep(0.05)
                executed.append("asr")

        handler = SlowHandler()

        async with run_with_callbacks([handler], run_in_background=True) as ctx:
            manager = get_callback_manager()
            await manager.on_asr_start(ctx, b"audio")

        # After context exits, callbacks should have completed
        assert "asr" in executed
