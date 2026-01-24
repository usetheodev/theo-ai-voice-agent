"""
Callbacks for Voice Pipeline observability.

This module provides a flexible callback system for monitoring
and instrumenting voice pipeline execution.

Quick Start:
    >>> from voice_pipeline.callbacks import run_with_callbacks, MetricsHandler

    >>> async with run_with_callbacks([MetricsHandler()]) as ctx:
    ...     result = await chain.ainvoke(audio)
    ...     print(f"Latency: {ctx.elapsed_ms}ms")

Built-in Handlers:
- LoggingHandler: Structured logging
- MetricsHandler: Performance metrics
- StdOutHandler: Simple debugging output
- OpenTelemetryHandler: Distributed tracing

Custom Handler:
    >>> from voice_pipeline.callbacks import VoiceCallbackHandler, RunContext

    >>> class MyHandler(VoiceCallbackHandler):
    ...     async def on_asr_end(self, ctx: RunContext, result):
    ...         print(f"Transcribed: {result.text}")
    ...
    ...     async def on_llm_token(self, ctx: RunContext, token: str):
    ...         print(token, end="", flush=True)
"""

from voice_pipeline.callbacks.base import (
    CallbackManager,
    RunContext,
    VoiceCallbackHandler,
)
from voice_pipeline.callbacks.context import (
    child_run,
    emit_asr_end,
    emit_asr_start,
    emit_custom_event,
    emit_llm_end,
    emit_llm_start,
    emit_llm_token,
    emit_tts_chunk,
    emit_tts_end,
    emit_tts_start,
    get_callback_manager,
    get_run_context,
    run_with_callbacks,
    run_with_context,
    set_callback_manager,
    set_run_context,
)
from voice_pipeline.callbacks.handlers import (
    OTEL_AVAILABLE,
    ComponentMetrics,
    LoggingHandler,
    MetricsHandler,
    OpenTelemetryHandler,
    PipelineMetrics,
    StdOutHandler,
    create_otel_handler,
)

__all__ = [
    # Base classes
    "VoiceCallbackHandler",
    "CallbackManager",
    "RunContext",
    # Context management
    "run_with_callbacks",
    "run_with_context",
    "child_run",
    "get_callback_manager",
    "get_run_context",
    "set_callback_manager",
    "set_run_context",
    # Emit helpers
    "emit_asr_start",
    "emit_asr_end",
    "emit_llm_start",
    "emit_llm_token",
    "emit_llm_end",
    "emit_tts_start",
    "emit_tts_chunk",
    "emit_tts_end",
    "emit_custom_event",
    # Handlers
    "LoggingHandler",
    "MetricsHandler",
    "StdOutHandler",
    "OpenTelemetryHandler",
    "create_otel_handler",
    "OTEL_AVAILABLE",
    # Metrics types
    "PipelineMetrics",
    "ComponentMetrics",
]
