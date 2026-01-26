"""Streaming utilities for the voice pipeline."""

from .sentence_streamer import SentenceStreamer, SentenceStreamerConfig
from .buffer import AudioBuffer, TextBuffer, AsyncQueue
from .metrics import StreamingMetrics, MetricsCollector
from .optimized_buffer import (
    RingBuffer,
    RingBufferConfig,
    BufferPool,
    pcm16_to_float_np,
    float_to_pcm16_np,
    calculate_rms_np,
    calculate_rms_from_array,
    calculate_db_np,
    resample_audio_np,
    mix_audio_np,
    apply_gain_np,
    normalize_audio_np,
)
from .strategy import StreamingGranularity, StreamingStrategy
from .sentence_strategy import SentenceStreamingStrategy
from .clause_strategy import ClauseStreamingStrategy
from .word_strategy import WordStreamingStrategy
from .adaptive_strategy import AdaptiveStreamingStrategy
from .filler import FillerInjector, FillerConfig

__all__ = [
    # Sentence streaming
    "SentenceStreamer",
    "SentenceStreamerConfig",
    # Streaming strategies (pluggable granularity)
    "StreamingStrategy",
    "StreamingGranularity",
    "SentenceStreamingStrategy",
    "ClauseStreamingStrategy",
    "WordStreamingStrategy",
    "AdaptiveStreamingStrategy",
    # Basic buffers
    "AudioBuffer",
    "TextBuffer",
    "AsyncQueue",
    # Metrics
    "StreamingMetrics",
    "MetricsCollector",
    # Optimized buffers
    "RingBuffer",
    "RingBufferConfig",
    "BufferPool",
    # Optimized audio functions
    "pcm16_to_float_np",
    "float_to_pcm16_np",
    "calculate_rms_np",
    "calculate_rms_from_array",
    "calculate_db_np",
    "resample_audio_np",
    "mix_audio_np",
    "apply_gain_np",
    "normalize_audio_np",
    # Filler injection
    "FillerInjector",
    "FillerConfig",
]
