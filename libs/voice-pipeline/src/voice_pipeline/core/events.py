"""Event system for the pipeline."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional
import time


class PipelineEventType(Enum):
    """Types of pipeline events."""

    # Pipeline lifecycle
    PIPELINE_START = "pipeline_start"
    PIPELINE_STOP = "pipeline_stop"
    PIPELINE_ERROR = "pipeline_error"

    # VAD events
    VAD_SPEECH_START = "vad_speech_start"
    VAD_SPEECH_END = "vad_speech_end"

    # ASR events
    ASR_START = "asr_start"
    ASR_PARTIAL = "asr_partial"
    ASR_FINAL = "asr_final"
    ASR_ERROR = "asr_error"

    # LLM events
    LLM_START = "llm_start"
    LLM_CHUNK = "llm_chunk"
    LLM_COMPLETE = "llm_complete"
    LLM_RESPONSE = "llm_response"
    LLM_ERROR = "llm_error"

    # TTS events
    TTS_START = "tts_start"
    TTS_CHUNK = "tts_chunk"
    TTS_COMPLETE = "tts_complete"
    TTS_ERROR = "tts_error"

    # Transcription (convenience alias)
    TRANSCRIPTION = "transcription"

    # Interaction events
    BARGE_IN = "barge_in"


@dataclass
class PipelineEvent:
    """Event emitted by the pipeline."""

    type: PipelineEventType
    """Event type."""

    data: Any = None
    """Event data (varies by type)."""

    latency_ms: Optional[float] = None
    """Latency measurement (if applicable)."""

    timestamp: float = field(default_factory=time.time)
    """Event timestamp."""


class EventEmitter:
    """Simple async event emitter."""

    def __init__(self):
        """Initialize event emitter."""
        self._handlers: dict[PipelineEventType, list[Callable]] = {}
        self._all_handlers: list[Callable] = []

    def on(
        self,
        event_type: PipelineEventType,
        handler: Callable[[PipelineEvent], None],
    ) -> None:
        """Register handler for specific event type.

        Args:
            event_type: Event type to listen for.
            handler: Callback function.
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def on_all(self, handler: Callable[[PipelineEvent], None]) -> None:
        """Register handler for all events.

        Args:
            handler: Callback function.
        """
        self._all_handlers.append(handler)

    def off(
        self,
        event_type: PipelineEventType,
        handler: Callable[[PipelineEvent], None],
    ) -> None:
        """Remove handler for specific event type.

        Args:
            event_type: Event type.
            handler: Handler to remove.
        """
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

    async def emit(self, event: PipelineEvent) -> None:
        """Emit event to all registered handlers.

        Args:
            event: Event to emit.
        """
        # Call type-specific handlers
        for handler in self._handlers.get(event.type, []):
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                # Log but don't break pipeline
                pass

        # Call catch-all handlers
        for handler in self._all_handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    def clear(self) -> None:
        """Clear all handlers."""
        self._handlers.clear()
        self._all_handlers.clear()
