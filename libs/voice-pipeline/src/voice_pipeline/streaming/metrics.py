"""Streaming metrics for measuring voice pipeline latency.

Provides dataclasses and utilities for measuring:
- TTFT (Time to First Token): Time until LLM generates first token
- TTFA (Time to First Audio): Time until TTS generates first audio chunk
- RTF (Real-Time Factor): Processing time / Audio duration
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StreamingMetrics:
    """Metrics for streaming voice pipeline.

    Attributes:
        ttft: Time to First Token (LLM)
        ttfa: Time to First Audio (TTS)
        total_time: Total pipeline time
        asr_time: ASR processing time
        llm_time: LLM generation time
        tts_time: TTS synthesis time
        sentences_count: Number of sentences processed
        tokens_count: Number of tokens generated
        audio_duration: Duration of generated audio (seconds)

    Example:
        >>> metrics = StreamingMetrics()
        >>> metrics.start()
        >>> # ... ASR processing ...
        >>> metrics.mark_asr_end()
        >>> # ... LLM generates first token ...
        >>> metrics.mark_first_token()
        >>> # ... TTS generates first audio ...
        >>> metrics.mark_first_audio()
        >>> # ... pipeline completes ...
        >>> metrics.end()
        >>> print(f"TTFA: {metrics.ttfa:.3f}s")
    """

    # Core latency metrics
    ttft: Optional[float] = None  # Time to First Token
    ttfa: Optional[float] = None  # Time to First Audio
    total_time: Optional[float] = None

    # Component times
    asr_time: Optional[float] = None
    llm_time: Optional[float] = None
    tts_time: Optional[float] = None

    # Counts
    sentences_count: int = 0
    tokens_count: int = 0
    audio_chunks_count: int = 0

    # Audio info
    audio_duration: float = 0.0  # seconds
    audio_bytes: int = 0

    # Internal timestamps (not exposed)
    _start_time: Optional[float] = field(default=None, repr=False)
    _asr_start: Optional[float] = field(default=None, repr=False)
    _llm_start: Optional[float] = field(default=None, repr=False)
    _tts_start: Optional[float] = field(default=None, repr=False)
    _first_token_time: Optional[float] = field(default=None, repr=False)
    _first_audio_time: Optional[float] = field(default=None, repr=False)

    def start(self) -> None:
        """Mark pipeline start."""
        self._start_time = time.perf_counter()

    def end(self) -> None:
        """Mark pipeline end and calculate total time."""
        if self._start_time:
            self.total_time = time.perf_counter() - self._start_time

    def mark_asr_start(self) -> None:
        """Mark ASR processing start."""
        self._asr_start = time.perf_counter()

    def mark_asr_end(self) -> None:
        """Mark ASR processing end."""
        if self._asr_start:
            self.asr_time = time.perf_counter() - self._asr_start

    def mark_llm_start(self) -> None:
        """Mark LLM generation start."""
        self._llm_start = time.perf_counter()

    def mark_llm_end(self) -> None:
        """Mark LLM generation end."""
        if self._llm_start:
            self.llm_time = time.perf_counter() - self._llm_start

    def mark_tts_start(self) -> None:
        """Mark TTS synthesis start."""
        self._tts_start = time.perf_counter()

    def mark_tts_end(self) -> None:
        """Mark TTS synthesis end."""
        if self._tts_start:
            self.tts_time = time.perf_counter() - self._tts_start

    def mark_first_token(self) -> None:
        """Mark first LLM token received."""
        if self._first_token_time is None and self._start_time:
            self._first_token_time = time.perf_counter()
            self.ttft = self._first_token_time - self._start_time

    def mark_first_audio(self) -> None:
        """Mark first audio chunk generated."""
        if self._first_audio_time is None and self._start_time:
            self._first_audio_time = time.perf_counter()
            self.ttfa = self._first_audio_time - self._start_time

    def add_token(self) -> None:
        """Increment token count."""
        self.tokens_count += 1

    def add_sentence(self) -> None:
        """Increment sentence count."""
        self.sentences_count += 1

    def add_audio_chunk(self, chunk_bytes: int, sample_rate: int = 24000) -> None:
        """Add audio chunk info.

        Args:
            chunk_bytes: Size of audio chunk in bytes
            sample_rate: Audio sample rate (default 24000)
        """
        self.audio_chunks_count += 1
        self.audio_bytes += chunk_bytes
        # Assuming 16-bit audio (2 bytes per sample)
        samples = chunk_bytes // 2
        self.audio_duration += samples / sample_rate

    @property
    def rtf(self) -> Optional[float]:
        """Real-Time Factor.

        RTF < 1.0 means faster than real-time.
        RTF > 1.0 means slower than real-time.
        """
        if self.total_time and self.audio_duration > 0:
            return self.total_time / self.audio_duration
        return None

    @property
    def is_realtime(self) -> bool:
        """Check if processing is faster than real-time."""
        rtf = self.rtf
        return rtf is not None and rtf < 1.0

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "ttft": self.ttft,
            "ttfa": self.ttfa,
            "total_time": self.total_time,
            "asr_time": self.asr_time,
            "llm_time": self.llm_time,
            "tts_time": self.tts_time,
            "sentences_count": self.sentences_count,
            "tokens_count": self.tokens_count,
            "audio_chunks_count": self.audio_chunks_count,
            "audio_duration": self.audio_duration,
            "audio_bytes": self.audio_bytes,
            "rtf": self.rtf,
            "is_realtime": self.is_realtime,
        }

    def __str__(self) -> str:
        """Human-readable summary."""
        parts = []
        if self.ttft is not None:
            parts.append(f"TTFT={self.ttft:.3f}s")
        if self.ttfa is not None:
            parts.append(f"TTFA={self.ttfa:.3f}s")
        if self.total_time is not None:
            parts.append(f"Total={self.total_time:.3f}s")
        if self.rtf is not None:
            parts.append(f"RTF={self.rtf:.2f}")
        if self.sentences_count > 0:
            parts.append(f"Sentences={self.sentences_count}")
        return f"StreamingMetrics({', '.join(parts)})"


class MetricsCollector:
    """Context manager for collecting streaming metrics.

    Example:
        >>> async with MetricsCollector() as metrics:
        ...     metrics.mark_asr_start()
        ...     transcription = await asr.ainvoke(audio)
        ...     metrics.mark_asr_end()
        ...     # ... rest of pipeline ...
        >>> print(metrics)
    """

    def __init__(self):
        self.metrics = StreamingMetrics()

    async def __aenter__(self) -> StreamingMetrics:
        self.metrics.start()
        return self.metrics

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.metrics.end()
        return False

    def __enter__(self) -> StreamingMetrics:
        self.metrics.start()
        return self.metrics

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.metrics.end()
        return False
