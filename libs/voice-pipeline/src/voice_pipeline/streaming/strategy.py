"""Streaming strategy interface for pluggable streaming granularity.

Defines how LLM tokens are buffered and emitted to TTS.
Different granularities trade off latency vs. speech naturalness:

- Word-level: ~45ms TTFA, less natural prosody
- Clause-level: ~200-400ms TTFA, good balance
- Sentence-level: ~600-800ms TTFA, most natural (current default)

References:
- ChipChat (Apple): SpeakStream word-level TTS with DML tokenization
- Pipecat: SentenceAggregator pattern
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional


class StreamingGranularity(Enum):
    """Streaming granularity level.

    Controls the size of text chunks sent to TTS.
    Smaller chunks = lower latency but potentially less natural speech.
    """

    WORD = "word"
    """Emit individual words. Lowest latency (~45ms TTFA).
    Best for TTS engines that handle single-word synthesis well."""

    CLAUSE = "clause"
    """Emit at clause boundaries (commas, conjunctions).
    Good balance of latency (~200-400ms) and naturalness."""

    SENTENCE = "sentence"
    """Emit complete sentences. Most natural prosody (~600-800ms TTFA).
    Default behavior, works best with most TTS engines."""


class StreamingStrategy(ABC):
    """Abstract interface for text streaming strategies.

    Implementations buffer incoming LLM tokens and emit text chunks
    suitable for TTS synthesis. The strategy determines when to emit
    based on the chosen granularity.

    The interface has two methods:
    - process(token): Add a token and get any ready chunks
    - flush(): Get remaining buffered text at end of generation

    Example implementation:
        class MyStrategy(StreamingStrategy):
            def process(self, token: str) -> list[str]:
                self._buffer += token
                chunks = self._extract_ready_chunks()
                return chunks

            def flush(self) -> Optional[str]:
                result = self._buffer.strip()
                self._buffer = ""
                return result or None

    Example usage with builder:
        agent = (
            VoiceAgent.builder()
            .asr("faster-whisper")
            .llm("ollama")
            .tts("kokoro")
            .streaming(True)
            .streaming_granularity("clause")
            .build()
        )
    """

    @abstractmethod
    def process(self, token: str) -> list[str]:
        """Process a single token and return any ready text chunks.

        Called for each token emitted by the LLM. The implementation
        should buffer tokens and emit chunks when appropriate boundaries
        are detected.

        Args:
            token: A text token from the LLM stream.

        Returns:
            List of text chunks ready for TTS (may be empty).
            Each chunk should be a complete unit suitable for synthesis.
        """
        ...

    @abstractmethod
    def flush(self) -> Optional[str]:
        """Flush any remaining buffered text.

        Called at the end of LLM generation to emit any text that
        hasn't been emitted yet. Must also reset the internal buffer.

        Returns:
            Remaining text, or None if buffer is empty.
        """
        ...

    def reset(self) -> None:
        """Reset internal state for a new generation.

        Called before starting a new LLM generation. Override if
        your implementation maintains state beyond the buffer.
        """
        pass

    @property
    @abstractmethod
    def granularity(self) -> StreamingGranularity:
        """The granularity level of this strategy."""
        ...

    @property
    def name(self) -> str:
        """Human-readable name for this strategy."""
        return f"{self.__class__.__name__}({self.granularity.value})"
