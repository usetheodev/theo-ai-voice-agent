"""Adaptive streaming strategy.

Combines word-level streaming for the first chunk (lowest TTFA)
with clause-level streaming for subsequent chunks (natural prosody).

Inspired by ChipChat's SpeakStream architecture, which uses
word-level output for the first TTS chunk and switches to
larger units for natural speech flow.

Phases:
  1. WORD: Emit first ~3 words as the initial chunk -> TTS starts early
  2. CLAUSE: After first chunk, switch to clause-level for naturalness

This achieves the best of both worlds:
  - TTFA comparable to word-level (~100-200ms)
  - Naturalness comparable to clause-level for the rest of the response
"""

import enum
from typing import Optional

from voice_pipeline.streaming.clause_strategy import ClauseStreamingStrategy
from voice_pipeline.streaming.strategy import StreamingGranularity, StreamingStrategy
from voice_pipeline.streaming.word_strategy import WordStreamingStrategy


class _Phase(enum.Enum):
    """Internal phase of the adaptive strategy."""
    WORD = "word"
    CLAUSE = "clause"


class AdaptiveStreamingStrategy(StreamingStrategy):
    """Adaptive strategy: word-level first chunk, clause-level after.

    The strategy starts in WORD phase using WordStreamingStrategy with
    group_size (default 3) to emit the first few words quickly. After
    the first chunk is emitted, it transitions to CLAUSE phase using
    ClauseStreamingStrategy for natural prosody.

    Buffer migration: when switching phases, any remaining content in
    the word strategy's buffer is flushed and injected into the clause
    strategy to avoid losing text.

    Args:
        first_chunk_words: Number of words for the first chunk.
            Default: 3 (e.g., "Hello, I am" -> TTS starts).
        clause_min_chars: Minimum characters for clause emission.
            Default: 10.
        clause_max_chars: Maximum characters for clause emission.
            Default: 150.
        language: Language for clause conjunction detection.
            Default: "en".

    Example:
        >>> strategy = AdaptiveStreamingStrategy()
        >>> # Phase WORD: emit first 3 words
        >>> strategy.process("Hello, ")
        []
        >>> strategy.process("I ")
        []
        >>> strategy.process("am ")
        ["Hello, I am"]  # First chunk! TTS starts here
        >>> # Phase CLAUSE: now uses clause-level
        >>> strategy.process("a voice assistant, ")
        []
        >>> strategy.process("and I can help.")
        ["a voice assistant,"]
        >>> strategy.flush()
        "and I can help."
    """

    def __init__(
        self,
        first_chunk_words: int = 3,
        clause_min_chars: int = 10,
        clause_max_chars: int = 150,
        language: str = "en",
    ):
        self.first_chunk_words = first_chunk_words
        self._phase = _Phase.WORD
        self._word_strategy = WordStreamingStrategy(group_size=first_chunk_words)
        self._clause_strategy = ClauseStreamingStrategy(
            min_chars=clause_min_chars,
            max_chars=clause_max_chars,
            language=language,
        )

    def process(self, token: str) -> list[str]:
        """Process token using the current phase strategy."""
        if self._phase == _Phase.WORD:
            chunks = self._word_strategy.process(token)
            if chunks:
                # First chunk emitted -> transition to clause phase
                self._transition_to_clause()
            return chunks
        else:
            return self._clause_strategy.process(token)

    def _transition_to_clause(self) -> None:
        """Switch from WORD to CLAUSE phase with buffer migration."""
        self._phase = _Phase.CLAUSE

        # Migrate remaining buffer from word strategy to clause strategy
        remaining = self._word_strategy.flush()
        if remaining:
            # Inject remaining text into clause strategy's buffer
            self._clause_strategy._buffer += remaining

    def flush(self) -> Optional[str]:
        """Flush the active strategy's buffer."""
        if self._phase == _Phase.WORD:
            return self._word_strategy.flush()
        else:
            return self._clause_strategy.flush()

    def reset(self) -> None:
        """Reset to initial WORD phase."""
        self._phase = _Phase.WORD
        self._word_strategy.reset()
        self._clause_strategy.reset()

    @property
    def phase(self) -> str:
        """Current phase name (for diagnostics)."""
        return self._phase.value

    @property
    def granularity(self) -> StreamingGranularity:
        """Reports CLAUSE as the primary granularity."""
        return StreamingGranularity.CLAUSE

    @property
    def name(self) -> str:
        """Human-readable name."""
        return f"AdaptiveStreamingStrategy({self._phase.value})"
