"""
Base classes for Voice Pipeline callbacks.

Callbacks provide hooks into the pipeline execution for observability,
logging, metrics collection, and custom behavior.
"""

import asyncio
import time
import uuid
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Optional

from voice_pipeline.interfaces import (
    AudioChunk,
    LLMChunk,
    TranscriptionResult,
    VADEvent,
)


@dataclass
class RunContext:
    """Context information for a pipeline run."""

    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this run."""

    parent_run_id: Optional[str] = None
    """Parent run ID for nested runs."""

    run_name: Optional[str] = None
    """Human-readable name for this run."""

    start_time: float = field(default_factory=time.time)
    """Start timestamp."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata associated with this run."""

    tags: list[str] = field(default_factory=list)
    """Tags for categorization."""

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time since start in milliseconds."""
        return (time.time() - self.start_time) * 1000


class VoiceCallbackHandler(ABC):
    """
    Base class for callback handlers.

    Implement the methods you need to handle specific events.
    All methods have default no-op implementations, so you only
    need to override the ones you're interested in.

    Example:
        class MyHandler(VoiceCallbackHandler):
            async def on_asr_end(self, ctx, result):
                print(f"Transcription: {result.text}")

            async def on_llm_token(self, ctx, token):
                print(token, end="", flush=True)
    """

    # ==================== Pipeline Lifecycle ====================

    async def on_pipeline_start(self, ctx: RunContext) -> None:
        """Called when pipeline starts processing."""
        pass

    async def on_pipeline_end(self, ctx: RunContext, output: Any = None) -> None:
        """Called when pipeline completes successfully."""
        pass

    async def on_pipeline_error(
        self, ctx: RunContext, error: Exception
    ) -> None:
        """Called when pipeline encounters an error."""
        pass

    # ==================== VAD Events ====================

    async def on_vad_start(self, ctx: RunContext) -> None:
        """Called when VAD processing starts."""
        pass

    async def on_vad_speech_start(self, ctx: RunContext, event: VADEvent) -> None:
        """Called when speech is detected."""
        pass

    async def on_vad_speech_end(self, ctx: RunContext, event: VADEvent) -> None:
        """Called when speech ends."""
        pass

    # ==================== ASR Events ====================

    async def on_asr_start(self, ctx: RunContext, input: bytes) -> None:
        """Called when ASR processing starts."""
        pass

    async def on_asr_partial(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        """Called for partial transcription results."""
        pass

    async def on_asr_end(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        """Called when ASR completes with final result."""
        pass

    async def on_asr_error(self, ctx: RunContext, error: Exception) -> None:
        """Called when ASR encounters an error."""
        pass

    # ==================== LLM Events ====================

    async def on_llm_start(
        self, ctx: RunContext, messages: list[dict[str, str]]
    ) -> None:
        """Called when LLM generation starts."""
        pass

    async def on_llm_token(self, ctx: RunContext, token: str) -> None:
        """Called for each generated token."""
        pass

    async def on_llm_chunk(self, ctx: RunContext, chunk: LLMChunk) -> None:
        """Called for each LLM chunk (includes metadata)."""
        pass

    async def on_llm_end(self, ctx: RunContext, response: str) -> None:
        """Called when LLM generation completes."""
        pass

    async def on_llm_error(self, ctx: RunContext, error: Exception) -> None:
        """Called when LLM encounters an error."""
        pass

    # ==================== TTS Events ====================

    async def on_tts_start(self, ctx: RunContext, text: str) -> None:
        """Called when TTS synthesis starts."""
        pass

    async def on_tts_chunk(self, ctx: RunContext, chunk: AudioChunk) -> None:
        """Called for each synthesized audio chunk."""
        pass

    async def on_tts_end(self, ctx: RunContext) -> None:
        """Called when TTS synthesis completes."""
        pass

    async def on_tts_error(self, ctx: RunContext, error: Exception) -> None:
        """Called when TTS encounters an error."""
        pass

    # ==================== Special Events ====================

    async def on_barge_in(self, ctx: RunContext) -> None:
        """Called when user interrupts (barge-in)."""
        pass

    async def on_turn_start(self, ctx: RunContext) -> None:
        """Called when a new conversation turn starts."""
        pass

    async def on_turn_end(self, ctx: RunContext) -> None:
        """Called when a conversation turn completes."""
        pass

    # ==================== Custom Events ====================

    async def on_custom_event(
        self, ctx: RunContext, event_name: str, data: Any = None
    ) -> None:
        """Called for custom events."""
        pass


class CallbackManager:
    """
    Manages a collection of callback handlers.

    This class aggregates multiple handlers and dispatches events
    to all of them. It handles errors in handlers gracefully,
    ensuring one failing handler doesn't break others.

    Example:
        manager = CallbackManager([
            LoggingHandler(),
            MetricsHandler(),
        ])

        ctx = manager.create_context(run_name="my-pipeline")
        await manager.on_asr_start(ctx, audio_bytes)
        # ... processing ...
        await manager.on_asr_end(ctx, result)
    """

    def __init__(
        self,
        handlers: Optional[list[VoiceCallbackHandler]] = None,
        run_in_background: bool = True,
    ):
        """
        Initialize the callback manager.

        Args:
            handlers: List of callback handlers.
            run_in_background: If True, callbacks run in background tasks
                              to avoid blocking the pipeline.
        """
        self.handlers = handlers or []
        self.run_in_background = run_in_background
        self._background_tasks: set[asyncio.Task] = set()

    def add_handler(self, handler: VoiceCallbackHandler) -> None:
        """Add a handler to the manager."""
        self.handlers.append(handler)

    def remove_handler(self, handler: VoiceCallbackHandler) -> None:
        """Remove a handler from the manager."""
        self.handlers.remove(handler)

    def create_context(
        self,
        run_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        run_name: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
    ) -> RunContext:
        """
        Create a new run context.

        Args:
            run_id: Custom run ID (auto-generated if not provided).
            parent_run_id: Parent run ID for nested runs.
            run_name: Human-readable name.
            metadata: Additional metadata.
            tags: Tags for categorization.

        Returns:
            New RunContext instance.
        """
        return RunContext(
            run_id=run_id or str(uuid.uuid4()),
            parent_run_id=parent_run_id,
            run_name=run_name,
            metadata=metadata or {},
            tags=tags or [],
        )

    async def _dispatch(
        self, method_name: str, ctx: RunContext, *args, **kwargs
    ) -> None:
        """Dispatch an event to all handlers."""
        for handler in self.handlers:
            method = getattr(handler, method_name, None)
            if method is None:
                continue

            try:
                if self.run_in_background:
                    # Run in background to avoid blocking
                    task = asyncio.create_task(method(ctx, *args, **kwargs))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                else:
                    await method(ctx, *args, **kwargs)
            except Exception:
                # Log but don't propagate callback errors
                import logging

                logging.getLogger(__name__).exception(
                    f"Error in callback {handler.__class__.__name__}.{method_name}"
                )

    async def wait_for_callbacks(self) -> None:
        """Wait for all background callbacks to complete."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

    # ==================== Event Dispatch Methods ====================

    async def on_pipeline_start(self, ctx: RunContext) -> None:
        await self._dispatch("on_pipeline_start", ctx)

    async def on_pipeline_end(self, ctx: RunContext, output: Any = None) -> None:
        await self._dispatch("on_pipeline_end", ctx, output)
        await self.wait_for_callbacks()

    async def on_pipeline_error(self, ctx: RunContext, error: Exception) -> None:
        await self._dispatch("on_pipeline_error", ctx, error)
        await self.wait_for_callbacks()

    async def on_vad_start(self, ctx: RunContext) -> None:
        await self._dispatch("on_vad_start", ctx)

    async def on_vad_speech_start(self, ctx: RunContext, event: VADEvent) -> None:
        await self._dispatch("on_vad_speech_start", ctx, event)

    async def on_vad_speech_end(self, ctx: RunContext, event: VADEvent) -> None:
        await self._dispatch("on_vad_speech_end", ctx, event)

    async def on_asr_start(self, ctx: RunContext, input: bytes) -> None:
        await self._dispatch("on_asr_start", ctx, input)

    async def on_asr_partial(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        await self._dispatch("on_asr_partial", ctx, result)

    async def on_asr_end(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        await self._dispatch("on_asr_end", ctx, result)

    async def on_asr_error(self, ctx: RunContext, error: Exception) -> None:
        await self._dispatch("on_asr_error", ctx, error)

    async def on_llm_start(
        self, ctx: RunContext, messages: list[dict[str, str]]
    ) -> None:
        await self._dispatch("on_llm_start", ctx, messages)

    async def on_llm_token(self, ctx: RunContext, token: str) -> None:
        await self._dispatch("on_llm_token", ctx, token)

    async def on_llm_chunk(self, ctx: RunContext, chunk: LLMChunk) -> None:
        await self._dispatch("on_llm_chunk", ctx, chunk)

    async def on_llm_end(self, ctx: RunContext, response: str) -> None:
        await self._dispatch("on_llm_end", ctx, response)

    async def on_llm_error(self, ctx: RunContext, error: Exception) -> None:
        await self._dispatch("on_llm_error", ctx, error)

    async def on_tts_start(self, ctx: RunContext, text: str) -> None:
        await self._dispatch("on_tts_start", ctx, text)

    async def on_tts_chunk(self, ctx: RunContext, chunk: AudioChunk) -> None:
        await self._dispatch("on_tts_chunk", ctx, chunk)

    async def on_tts_end(self, ctx: RunContext) -> None:
        await self._dispatch("on_tts_end", ctx)

    async def on_tts_error(self, ctx: RunContext, error: Exception) -> None:
        await self._dispatch("on_tts_error", ctx, error)

    async def on_barge_in(self, ctx: RunContext) -> None:
        await self._dispatch("on_barge_in", ctx)

    async def on_turn_start(self, ctx: RunContext) -> None:
        await self._dispatch("on_turn_start", ctx)

    async def on_turn_end(self, ctx: RunContext) -> None:
        await self._dispatch("on_turn_end", ctx)

    async def on_custom_event(
        self, ctx: RunContext, event_name: str, data: Any = None
    ) -> None:
        await self._dispatch("on_custom_event", ctx, event_name, data)
