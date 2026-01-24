"""
Metrics callback handler for Voice Pipeline.

Collects latency and performance metrics for pipeline components.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from voice_pipeline.callbacks.base import RunContext, VoiceCallbackHandler
from voice_pipeline.interfaces import (
    AudioChunk,
    LLMChunk,
    TranscriptionResult,
    VADEvent,
)


@dataclass
class ComponentMetrics:
    """Metrics for a single component (ASR, LLM, TTS)."""

    start_time: Optional[float] = None
    end_time: Optional[float] = None
    first_result_time: Optional[float] = None
    item_count: int = 0
    byte_count: int = 0
    error_count: int = 0

    @property
    def latency_ms(self) -> Optional[float]:
        """Total latency from start to end."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None

    @property
    def time_to_first_ms(self) -> Optional[float]:
        """Time to first result (TTFR/TTFT/TTFA)."""
        if self.start_time and self.first_result_time:
            return (self.first_result_time - self.start_time) * 1000
        return None


@dataclass
class PipelineMetrics:
    """Aggregated metrics for a pipeline run."""

    run_id: str
    run_name: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    # Component metrics
    asr: ComponentMetrics = field(default_factory=ComponentMetrics)
    llm: ComponentMetrics = field(default_factory=ComponentMetrics)
    tts: ComponentMetrics = field(default_factory=ComponentMetrics)
    vad: ComponentMetrics = field(default_factory=ComponentMetrics)

    # Counters
    barge_in_count: int = 0
    turn_count: int = 0
    error_count: int = 0

    @property
    def total_latency_ms(self) -> Optional[float]:
        """Total pipeline latency."""
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return None

    @property
    def e2e_latency_ms(self) -> Optional[float]:
        """End-to-end latency from ASR start to first TTS audio."""
        if self.asr.start_time and self.tts.first_result_time:
            return (self.tts.first_result_time - self.asr.start_time) * 1000
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "total_latency_ms": self.total_latency_ms,
            "e2e_latency_ms": self.e2e_latency_ms,
            "asr": {
                "latency_ms": self.asr.latency_ms,
                "time_to_first_ms": self.asr.time_to_first_ms,
                "item_count": self.asr.item_count,
            },
            "llm": {
                "latency_ms": self.llm.latency_ms,
                "ttft_ms": self.llm.time_to_first_ms,
                "token_count": self.llm.item_count,
            },
            "tts": {
                "latency_ms": self.tts.latency_ms,
                "ttfa_ms": self.tts.time_to_first_ms,
                "chunk_count": self.tts.item_count,
                "byte_count": self.tts.byte_count,
            },
            "barge_in_count": self.barge_in_count,
            "turn_count": self.turn_count,
            "error_count": self.error_count,
        }


class MetricsHandler(VoiceCallbackHandler):
    """
    Callback handler that collects performance metrics.

    Tracks latencies, throughput, and error rates for pipeline components.

    Example:
        handler = MetricsHandler(
            on_metrics=lambda m: print(f"TTFT: {m.llm.time_to_first_ms}ms")
        )

        async with run_with_callbacks([handler]) as ctx:
            result = await chain.ainvoke(audio)

        # Access final metrics
        metrics = handler.get_metrics(ctx.run_id)
        print(f"E2E latency: {metrics.e2e_latency_ms}ms")
    """

    def __init__(
        self,
        on_metrics: Optional[Callable[[PipelineMetrics], None]] = None,
        collect_component_metrics: bool = True,
        max_stored_runs: int = 100,
    ):
        """
        Initialize the metrics handler.

        Args:
            on_metrics: Callback called when pipeline completes with metrics.
            collect_component_metrics: Track per-component metrics.
            max_stored_runs: Maximum number of runs to keep in memory.
        """
        self.on_metrics_callback = on_metrics
        self.collect_component_metrics = collect_component_metrics
        self.max_stored_runs = max_stored_runs

        # Storage for metrics by run_id
        self._metrics: dict[str, PipelineMetrics] = {}
        self._run_order: list[str] = []

    def _get_or_create(self, ctx: RunContext) -> PipelineMetrics:
        """Get or create metrics for a run."""
        if ctx.run_id not in self._metrics:
            metrics = PipelineMetrics(
                run_id=ctx.run_id,
                run_name=ctx.run_name,
                start_time=ctx.start_time,
            )
            self._metrics[ctx.run_id] = metrics
            self._run_order.append(ctx.run_id)

            # Cleanup old runs
            while len(self._run_order) > self.max_stored_runs:
                old_id = self._run_order.pop(0)
                self._metrics.pop(old_id, None)

        return self._metrics[ctx.run_id]

    def get_metrics(self, run_id: str) -> Optional[PipelineMetrics]:
        """Get metrics for a specific run."""
        return self._metrics.get(run_id)

    def get_all_metrics(self) -> list[PipelineMetrics]:
        """Get all stored metrics."""
        return list(self._metrics.values())

    def clear(self) -> None:
        """Clear all stored metrics."""
        self._metrics.clear()
        self._run_order.clear()

    # ==================== Pipeline Lifecycle ====================

    async def on_pipeline_start(self, ctx: RunContext) -> None:
        self._get_or_create(ctx)

    async def on_pipeline_end(self, ctx: RunContext, output: Any = None) -> None:
        metrics = self._get_or_create(ctx)
        metrics.end_time = time.time()

        if self.on_metrics_callback:
            self.on_metrics_callback(metrics)

    async def on_pipeline_error(self, ctx: RunContext, error: Exception) -> None:
        metrics = self._get_or_create(ctx)
        metrics.end_time = time.time()
        metrics.error_count += 1

        if self.on_metrics_callback:
            self.on_metrics_callback(metrics)

    # ==================== VAD Events ====================

    async def on_vad_speech_start(self, ctx: RunContext, event: VADEvent) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        if metrics.vad.start_time is None:
            metrics.vad.start_time = time.time()

    async def on_vad_speech_end(self, ctx: RunContext, event: VADEvent) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        metrics.vad.end_time = time.time()

    # ==================== ASR Events ====================

    async def on_asr_start(self, ctx: RunContext, input: bytes) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        metrics.asr.start_time = time.time()
        metrics.asr.byte_count = len(input)

    async def on_asr_partial(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        if metrics.asr.first_result_time is None:
            metrics.asr.first_result_time = time.time()
        metrics.asr.item_count += 1

    async def on_asr_end(
        self, ctx: RunContext, result: TranscriptionResult
    ) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        metrics.asr.end_time = time.time()
        if metrics.asr.first_result_time is None:
            metrics.asr.first_result_time = time.time()
        metrics.asr.item_count += 1

    async def on_asr_error(self, ctx: RunContext, error: Exception) -> None:
        metrics = self._get_or_create(ctx)
        metrics.asr.error_count += 1

    # ==================== LLM Events ====================

    async def on_llm_start(
        self, ctx: RunContext, messages: list[dict[str, str]]
    ) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        metrics.llm.start_time = time.time()

    async def on_llm_token(self, ctx: RunContext, token: str) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        if metrics.llm.first_result_time is None:
            metrics.llm.first_result_time = time.time()
        metrics.llm.item_count += 1

    async def on_llm_chunk(self, ctx: RunContext, chunk: LLMChunk) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        if metrics.llm.first_result_time is None:
            metrics.llm.first_result_time = time.time()

    async def on_llm_end(self, ctx: RunContext, response: str) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        metrics.llm.end_time = time.time()
        metrics.llm.byte_count = len(response.encode("utf-8"))

    async def on_llm_error(self, ctx: RunContext, error: Exception) -> None:
        metrics = self._get_or_create(ctx)
        metrics.llm.error_count += 1

    # ==================== TTS Events ====================

    async def on_tts_start(self, ctx: RunContext, text: str) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        metrics.tts.start_time = time.time()

    async def on_tts_chunk(self, ctx: RunContext, chunk: AudioChunk) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        if metrics.tts.first_result_time is None:
            metrics.tts.first_result_time = time.time()
        metrics.tts.item_count += 1
        metrics.tts.byte_count += len(chunk.data)

    async def on_tts_end(self, ctx: RunContext) -> None:
        if not self.collect_component_metrics:
            return

        metrics = self._get_or_create(ctx)
        metrics.tts.end_time = time.time()

    async def on_tts_error(self, ctx: RunContext, error: Exception) -> None:
        metrics = self._get_or_create(ctx)
        metrics.tts.error_count += 1

    # ==================== Special Events ====================

    async def on_barge_in(self, ctx: RunContext) -> None:
        metrics = self._get_or_create(ctx)
        metrics.barge_in_count += 1

    async def on_turn_start(self, ctx: RunContext) -> None:
        metrics = self._get_or_create(ctx)
        metrics.turn_count += 1

    async def on_turn_end(self, ctx: RunContext) -> None:
        pass  # Turn end doesn't need additional tracking
