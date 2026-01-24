"""
Logging callback handler for Voice Pipeline.

Provides structured logging for pipeline events.
"""

import logging
from typing import Any, Optional

from voice_pipeline.callbacks.base import RunContext, VoiceCallbackHandler
from voice_pipeline.interfaces import (
    AudioChunk,
    LLMChunk,
    TranscriptionResult,
    VADEvent,
)


class LoggingHandler(VoiceCallbackHandler):
    """
    Callback handler that logs pipeline events.

    Supports structured logging with run context information.

    Example:
        handler = LoggingHandler(
            logger=logging.getLogger("voice-pipeline"),
            level=logging.INFO,
        )
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        level: int = logging.INFO,
        include_metadata: bool = True,
        log_tokens: bool = False,
        log_audio_chunks: bool = False,
    ):
        """
        Initialize the logging handler.

        Args:
            logger: Logger instance to use. Defaults to "voice_pipeline".
            level: Logging level.
            include_metadata: Include run metadata in log messages.
            log_tokens: Log individual LLM tokens (can be verbose).
            log_audio_chunks: Log audio chunk events (can be verbose).
        """
        self.logger = logger or logging.getLogger("voice_pipeline")
        self.level = level
        self.include_metadata = include_metadata
        self.log_tokens = log_tokens
        self.log_audio_chunks = log_audio_chunks

    def _log(
        self,
        ctx: RunContext,
        event: str,
        message: str,
        level: Optional[int] = None,
        **extra,
    ) -> None:
        """Log a message with context."""
        log_level = level or self.level

        log_data = {
            "event": event,
            "run_id": ctx.run_id,
            "elapsed_ms": round(ctx.elapsed_ms, 2),
        }

        if ctx.parent_run_id:
            log_data["parent_run_id"] = ctx.parent_run_id

        if ctx.run_name:
            log_data["run_name"] = ctx.run_name

        if self.include_metadata and ctx.metadata:
            log_data["metadata"] = ctx.metadata

        if ctx.tags:
            log_data["tags"] = ctx.tags

        log_data.update(extra)

        self.logger.log(log_level, f"[{event}] {message}", extra=log_data)

    # ==================== Pipeline Lifecycle ====================

    async def on_pipeline_start(self, ctx: RunContext) -> None:
        self._log(ctx, "PIPELINE_START", "Pipeline started")

    async def on_pipeline_end(self, ctx: RunContext, output: Any = None) -> None:
        self._log(
            ctx,
            "PIPELINE_END",
            f"Pipeline completed in {ctx.elapsed_ms:.1f}ms",
        )

    async def on_pipeline_error(self, ctx: RunContext, error: Exception) -> None:
        self._log(
            ctx,
            "PIPELINE_ERROR",
            f"Pipeline error: {error}",
            level=logging.ERROR,
            error=str(error),
            error_type=type(error).__name__,
        )

    # ==================== VAD Events ====================

    async def on_vad_speech_start(self, ctx: RunContext, event: VADEvent) -> None:
        self._log(
            ctx,
            "VAD_SPEECH_START",
            f"Speech detected (confidence: {event.confidence:.2f})",
            confidence=event.confidence,
        )

    async def on_vad_speech_end(self, ctx: RunContext, event: VADEvent) -> None:
        self._log(
            ctx,
            "VAD_SPEECH_END",
            "Speech ended",
            confidence=event.confidence,
        )

    # ==================== ASR Events ====================

    async def on_asr_start(self, ctx: RunContext, input: bytes) -> None:
        self._log(
            ctx,
            "ASR_START",
            f"ASR started ({len(input)} bytes)",
            input_size=len(input),
        )

    async def on_asr_partial(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        self._log(
            ctx,
            "ASR_PARTIAL",
            f"Partial: '{result.text[:50]}...' (conf: {result.confidence:.2f})",
            text=result.text,
            confidence=result.confidence,
            level=logging.DEBUG,
        )

    async def on_asr_end(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        self._log(
            ctx,
            "ASR_END",
            f"Transcription: '{result.text}' (conf: {result.confidence:.2f})",
            text=result.text,
            confidence=result.confidence,
            language=result.language,
        )

    async def on_asr_error(self, ctx: RunContext, error: Exception) -> None:
        self._log(
            ctx,
            "ASR_ERROR",
            f"ASR error: {error}",
            level=logging.ERROR,
            error=str(error),
        )

    # ==================== LLM Events ====================

    async def on_llm_start(
        self, ctx: RunContext, messages: list[dict[str, str]]
    ) -> None:
        msg_count = len(messages)
        last_msg = messages[-1]["content"][:50] if messages else ""
        self._log(
            ctx,
            "LLM_START",
            f"LLM started ({msg_count} messages, last: '{last_msg}...')",
            message_count=msg_count,
        )

    async def on_llm_token(self, ctx: RunContext, token: str) -> None:
        if self.log_tokens:
            self._log(
                ctx,
                "LLM_TOKEN",
                f"Token: '{token}'",
                token=token,
                level=logging.DEBUG,
            )

    async def on_llm_end(self, ctx: RunContext, response: str) -> None:
        preview = response[:100] + "..." if len(response) > 100 else response
        self._log(
            ctx,
            "LLM_END",
            f"Response: '{preview}'",
            response_length=len(response),
        )

    async def on_llm_error(self, ctx: RunContext, error: Exception) -> None:
        self._log(
            ctx,
            "LLM_ERROR",
            f"LLM error: {error}",
            level=logging.ERROR,
            error=str(error),
        )

    # ==================== TTS Events ====================

    async def on_tts_start(self, ctx: RunContext, text: str) -> None:
        preview = text[:50] + "..." if len(text) > 50 else text
        self._log(
            ctx,
            "TTS_START",
            f"TTS started: '{preview}'",
            text_length=len(text),
        )

    async def on_tts_chunk(self, ctx: RunContext, chunk: AudioChunk) -> None:
        if self.log_audio_chunks:
            self._log(
                ctx,
                "TTS_CHUNK",
                f"Audio chunk: {len(chunk.data)} bytes",
                chunk_size=len(chunk.data),
                sample_rate=chunk.sample_rate,
                level=logging.DEBUG,
            )

    async def on_tts_end(self, ctx: RunContext) -> None:
        self._log(ctx, "TTS_END", "TTS completed")

    async def on_tts_error(self, ctx: RunContext, error: Exception) -> None:
        self._log(
            ctx,
            "TTS_ERROR",
            f"TTS error: {error}",
            level=logging.ERROR,
            error=str(error),
        )

    # ==================== Special Events ====================

    async def on_barge_in(self, ctx: RunContext) -> None:
        self._log(ctx, "BARGE_IN", "User interrupted (barge-in)")

    async def on_turn_start(self, ctx: RunContext) -> None:
        self._log(ctx, "TURN_START", "Conversation turn started")

    async def on_turn_end(self, ctx: RunContext) -> None:
        self._log(
            ctx,
            "TURN_END",
            f"Turn completed in {ctx.elapsed_ms:.1f}ms",
        )

    async def on_custom_event(
        self, ctx: RunContext, event_name: str, data: Any = None
    ) -> None:
        self._log(
            ctx,
            f"CUSTOM:{event_name}",
            f"Custom event: {event_name}",
            event_data=data,
        )
