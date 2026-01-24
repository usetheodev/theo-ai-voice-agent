"""Tests for event system."""

import pytest
from voice_pipeline.core.events import (
    EventEmitter,
    PipelineEvent,
    PipelineEventType,
)


class TestPipelineEvent:
    """Tests for PipelineEvent."""

    def test_event_creation(self):
        """Test creating an event."""
        event = PipelineEvent(
            type=PipelineEventType.TRANSCRIPTION,
            data={"text": "Hello"},
            latency_ms=100.5,
        )

        assert event.type == PipelineEventType.TRANSCRIPTION
        assert event.data == {"text": "Hello"}
        assert event.latency_ms == 100.5
        assert event.timestamp > 0

    def test_event_defaults(self):
        """Test event default values."""
        event = PipelineEvent(type=PipelineEventType.PIPELINE_START)

        assert event.data is None
        assert event.latency_ms is None


class TestEventEmitter:
    """Tests for EventEmitter."""

    @pytest.mark.asyncio
    async def test_on_and_emit(self):
        """Test registering handler and emitting event."""
        emitter = EventEmitter()
        received = []

        def handler(event):
            received.append(event)

        emitter.on(PipelineEventType.TRANSCRIPTION, handler)

        event = PipelineEvent(
            type=PipelineEventType.TRANSCRIPTION,
            data={"text": "Hello"},
        )
        await emitter.emit(event)

        assert len(received) == 1
        assert received[0].data == {"text": "Hello"}

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        """Test multiple handlers for same event."""
        emitter = EventEmitter()
        count = [0]

        def handler1(event):
            count[0] += 1

        def handler2(event):
            count[0] += 10

        emitter.on(PipelineEventType.TRANSCRIPTION, handler1)
        emitter.on(PipelineEventType.TRANSCRIPTION, handler2)

        await emitter.emit(PipelineEvent(type=PipelineEventType.TRANSCRIPTION))

        assert count[0] == 11

    @pytest.mark.asyncio
    async def test_on_all(self):
        """Test catch-all handler."""
        emitter = EventEmitter()
        received = []

        emitter.on_all(lambda e: received.append(e.type))

        await emitter.emit(PipelineEvent(type=PipelineEventType.PIPELINE_START))
        await emitter.emit(PipelineEvent(type=PipelineEventType.TRANSCRIPTION))
        await emitter.emit(PipelineEvent(type=PipelineEventType.PIPELINE_STOP))

        assert len(received) == 3
        assert PipelineEventType.PIPELINE_START in received
        assert PipelineEventType.TRANSCRIPTION in received
        assert PipelineEventType.PIPELINE_STOP in received

    @pytest.mark.asyncio
    async def test_async_handler(self):
        """Test async event handler."""
        emitter = EventEmitter()
        received = []

        async def async_handler(event):
            received.append(event.data)

        emitter.on(PipelineEventType.TRANSCRIPTION, async_handler)

        await emitter.emit(PipelineEvent(
            type=PipelineEventType.TRANSCRIPTION,
            data="async_data",
        ))

        assert received == ["async_data"]

    @pytest.mark.asyncio
    async def test_off(self):
        """Test removing handler."""
        emitter = EventEmitter()
        received = []

        def handler(event):
            received.append(event)

        emitter.on(PipelineEventType.TRANSCRIPTION, handler)
        emitter.off(PipelineEventType.TRANSCRIPTION, handler)

        await emitter.emit(PipelineEvent(type=PipelineEventType.TRANSCRIPTION))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_handler_error_doesnt_break_emit(self):
        """Test that handler errors don't break other handlers."""
        emitter = EventEmitter()
        received = []

        def bad_handler(event):
            raise ValueError("Error!")

        def good_handler(event):
            received.append(event)

        emitter.on(PipelineEventType.TRANSCRIPTION, bad_handler)
        emitter.on(PipelineEventType.TRANSCRIPTION, good_handler)

        # Should not raise
        await emitter.emit(PipelineEvent(type=PipelineEventType.TRANSCRIPTION))

        # Good handler should still be called
        assert len(received) == 1

    def test_clear(self):
        """Test clearing all handlers."""
        emitter = EventEmitter()

        emitter.on(PipelineEventType.TRANSCRIPTION, lambda e: None)
        emitter.on_all(lambda e: None)

        emitter.clear()

        assert len(emitter._handlers) == 0
        assert len(emitter._all_handlers) == 0


class TestPipelineEventType:
    """Tests for PipelineEventType enum."""

    def test_all_event_types_exist(self):
        """Test all expected event types exist."""
        # Pipeline lifecycle
        assert PipelineEventType.PIPELINE_START
        assert PipelineEventType.PIPELINE_STOP
        assert PipelineEventType.PIPELINE_ERROR

        # VAD
        assert PipelineEventType.VAD_SPEECH_START
        assert PipelineEventType.VAD_SPEECH_END

        # ASR
        assert PipelineEventType.ASR_START
        assert PipelineEventType.ASR_PARTIAL
        assert PipelineEventType.ASR_FINAL
        assert PipelineEventType.ASR_ERROR

        # LLM
        assert PipelineEventType.LLM_START
        assert PipelineEventType.LLM_CHUNK
        assert PipelineEventType.LLM_COMPLETE
        assert PipelineEventType.LLM_RESPONSE
        assert PipelineEventType.LLM_ERROR

        # TTS
        assert PipelineEventType.TTS_START
        assert PipelineEventType.TTS_CHUNK
        assert PipelineEventType.TTS_COMPLETE
        assert PipelineEventType.TTS_ERROR

        # Interaction
        assert PipelineEventType.BARGE_IN
        assert PipelineEventType.TRANSCRIPTION
