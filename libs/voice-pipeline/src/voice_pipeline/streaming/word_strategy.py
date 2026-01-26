"""Word-level streaming strategy.

Emits individual words for minimum TTFA (~45ms).
Inspired by ChipChat's SpeakStream architecture.

This strategy provides the lowest possible latency at the cost
of potentially less natural prosody, since TTS engines receive
words one at a time instead of complete phrases.

Best used with:
- TTS engines that handle incremental synthesis well
- Applications where latency is critical (real-time telephony)
- TTS with DML-style tokenization (parallel prediction)

Not recommended for:
- TTS engines that need full sentences for prosody
- Applications where natural speech quality is paramount
"""

from typing import Optional

from voice_pipeline.streaming.strategy import StreamingGranularity, StreamingStrategy


class WordStreamingStrategy(StreamingStrategy):
    """Word-level streaming for minimum TTFA.

    Emits each word as soon as it's complete (detected by whitespace).
    Optional minimum word length prevents emitting very short words
    (articles, prepositions) individually.

    With word grouping (group_size > 1), emits groups of N words
    together for slightly better prosody while maintaining low latency.

    Args:
        min_word_length: Minimum character length for a word to be
            emitted independently. Shorter words are grouped with
            the next word. Default: 1 (emit all words).
        group_size: Number of words to group before emitting.
            1 = true word-level (lowest latency).
            2-3 = small groups (better prosody, slightly higher latency).
            Default: 1.

    Example:
        >>> strategy = WordStreamingStrategy()
        >>> strategy.process("Hello ")
        ["Hello"]
        >>> strategy.process("world!")
        []
        >>> strategy.flush()
        "mundo!"

        >>> # With grouping
        >>> strategy = WordStreamingStrategy(group_size=2)
        >>> strategy.process("Eu gosto ")
        []
        >>> strategy.process("de café")
        ["Eu gosto"]
        >>> strategy.flush()
        "de café"
    """

    def __init__(
        self,
        min_word_length: int = 1,
        group_size: int = 1,
    ):
        self.min_word_length = min_word_length
        self.group_size = max(1, group_size)
        self._buffer = ""
        self._word_buffer: list[str] = []

    def process(self, token: str) -> list[str]:
        """Process token and emit completed words."""
        self._buffer += token
        chunks: list[str] = []

        # Extract complete words (terminated by whitespace)
        while " " in self._buffer or "\n" in self._buffer:
            # Find first whitespace
            space_idx = len(self._buffer)
            for i, c in enumerate(self._buffer):
                if c in (" ", "\n", "\t"):
                    space_idx = i
                    break

            if space_idx == len(self._buffer):
                break

            word = self._buffer[:space_idx]
            self._buffer = self._buffer[space_idx + 1:]

            if not word:
                continue

            self._word_buffer.append(word)

            # Emit when we have enough words
            if len(self._word_buffer) >= self.group_size:
                chunk = " ".join(self._word_buffer)
                # Check min_word_length for single words
                if self.group_size == 1 and len(word) < self.min_word_length:
                    # Too short, keep in buffer for next group
                    continue
                chunks.append(chunk)
                self._word_buffer = []

        return chunks

    def flush(self) -> Optional[str]:
        """Flush remaining buffer and word buffer."""
        parts = []

        if self._word_buffer:
            parts.append(" ".join(self._word_buffer))
            self._word_buffer = []

        if self._buffer.strip():
            parts.append(self._buffer.strip())
            self._buffer = ""
        else:
            self._buffer = ""

        result = " ".join(parts).strip()
        return result if result else None

    def reset(self) -> None:
        """Reset all buffers."""
        self._buffer = ""
        self._word_buffer = []

    @property
    def granularity(self) -> StreamingGranularity:
        return StreamingGranularity.WORD
