"""Sentence-level streaming strategy.

Wraps the existing SentenceStreamer as a StreamingStrategy,
maintaining full backwards compatibility while conforming
to the pluggable strategy interface.

This is the default strategy, providing the most natural
speech prosody at the cost of higher TTFA (~600-800ms).
"""

from typing import Optional

from voice_pipeline.streaming.sentence_streamer import SentenceStreamer, SentenceStreamerConfig
from voice_pipeline.streaming.strategy import StreamingGranularity, StreamingStrategy


class SentenceStreamingStrategy(StreamingStrategy):
    """Sentence-level streaming using the existing SentenceStreamer.

    Buffers LLM tokens and emits complete sentences based on
    punctuation detection, adaptive min_chars, quick phrases,
    and timeout-based fallback.

    This is a thin wrapper around SentenceStreamer that implements
    the StreamingStrategy interface for pluggability.

    Args:
        config: SentenceStreamer configuration. If None, uses defaults.

    Example:
        >>> strategy = SentenceStreamingStrategy()
        >>> chunks = strategy.process("Olá! ")
        >>> # → ["Olá!"]
        >>> chunks = strategy.process("Como vai")
        >>> # → []
        >>> chunks = strategy.process(" você?")
        >>> # → ["Como vai você?"]
    """

    def __init__(self, config: Optional[SentenceStreamerConfig] = None):
        self._streamer = SentenceStreamer(config)

    def process(self, token: str) -> list[str]:
        """Process token through SentenceStreamer."""
        return self._streamer.process(token)

    def flush(self) -> Optional[str]:
        """Flush remaining buffer."""
        return self._streamer.flush()

    def reset(self) -> None:
        """Reset streamer state."""
        self._streamer.reset()

    @property
    def granularity(self) -> StreamingGranularity:
        return StreamingGranularity.SENTENCE

    @property
    def config(self) -> SentenceStreamerConfig:
        """Access the underlying SentenceStreamer config."""
        return self._streamer.config
