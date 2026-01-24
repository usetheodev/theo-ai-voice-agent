"""Sentence-level streaming for LLM → TTS.

Buffers LLM tokens and emits complete sentences for TTS synthesis.
This reduces latency by starting TTS before the full LLM response is ready.
"""

from dataclasses import dataclass, field
from typing import AsyncIterator, Optional
import asyncio


@dataclass
class SentenceStreamerConfig:
    """Configuration for sentence streaming."""

    # Sentence boundaries
    sentence_end_chars: list[str] = field(
        default_factory=lambda: [".", "!", "?", "\n"]
    )

    # Also break on these (softer boundaries)
    soft_break_chars: list[str] = field(
        default_factory=lambda: [";", ":", ","]
    )

    # Minimum characters before emitting (avoid tiny chunks)
    min_chars: int = 20

    # Maximum characters before forcing emit
    max_chars: int = 200

    # Use soft breaks only after max_chars
    use_soft_breaks: bool = True


class SentenceStreamer:
    """Buffers text tokens and emits complete sentences.

    This is the "PunctuatedBufferStreamer" pattern from the research paper.

    Example:
        streamer = SentenceStreamer()

        async for sentence in streamer.process(llm_token_stream):
            # Each sentence is ready for TTS
            audio = await tts.synthesize(sentence)

    The streamer:
    1. Buffers incoming tokens
    2. Detects sentence boundaries (., !, ?, etc.)
    3. Emits complete sentences immediately
    4. Forces emit after max_chars to avoid long waits
    """

    def __init__(self, config: Optional[SentenceStreamerConfig] = None):
        """Initialize streamer.

        Args:
            config: Streaming configuration.
        """
        self.config = config or SentenceStreamerConfig()
        self._buffer = ""

    def reset(self) -> None:
        """Reset buffer state."""
        self._buffer = ""

    async def process(
        self,
        token_stream: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Process token stream and yield complete sentences.

        Args:
            token_stream: Async iterator of text tokens/chunks.

        Yields:
            Complete sentences ready for TTS.
        """
        self._buffer = ""

        async for token in token_stream:
            self._buffer += token

            # Check for sentence boundaries
            sentences = self._extract_sentences()

            for sentence in sentences:
                if sentence.strip():
                    yield sentence.strip()

        # Yield remaining buffer
        if self._buffer.strip():
            yield self._buffer.strip()
            self._buffer = ""

    def _extract_sentences(self) -> list[str]:
        """Extract complete sentences from buffer.

        Returns:
            List of complete sentences. Buffer is updated to contain
            only the incomplete trailing portion.
        """
        sentences = []

        while True:
            # Find next sentence boundary
            boundary_pos = self._find_boundary()

            if boundary_pos is None:
                # No boundary found
                # Check if we should force emit
                if len(self._buffer) >= self.config.max_chars:
                    # Find soft break or just split
                    soft_pos = self._find_soft_break()
                    if soft_pos and self.config.use_soft_breaks:
                        sentences.append(self._buffer[: soft_pos + 1])
                        self._buffer = self._buffer[soft_pos + 1 :]
                    else:
                        # Force split at word boundary
                        split_pos = self._find_word_boundary()
                        if split_pos:
                            sentences.append(self._buffer[:split_pos])
                            self._buffer = self._buffer[split_pos:]
                        else:
                            # No good split point, emit all
                            sentences.append(self._buffer)
                            self._buffer = ""
                break

            # Extract sentence
            sentence = self._buffer[: boundary_pos + 1]

            # Check minimum length
            if len(sentence.strip()) >= self.config.min_chars:
                sentences.append(sentence)
                self._buffer = self._buffer[boundary_pos + 1 :]
            else:
                # Too short, keep buffering
                break

        return sentences

    def _find_boundary(self) -> Optional[int]:
        """Find position of sentence boundary in buffer."""
        for i, char in enumerate(self._buffer):
            if char in self.config.sentence_end_chars:
                # Make sure it's not in the middle of something
                # like a number (3.14) or abbreviation (Dr.)
                if self._is_valid_boundary(i):
                    return i
        return None

    def _is_valid_boundary(self, pos: int) -> bool:
        """Check if position is a valid sentence boundary."""
        if pos >= len(self._buffer):
            return False

        char = self._buffer[pos]

        # Period might be decimal or abbreviation
        if char == ".":
            # Check if followed by space/newline/end
            if pos + 1 < len(self._buffer):
                next_char = self._buffer[pos + 1]
                if next_char.isdigit():
                    return False  # Decimal number
                if next_char.isalpha() and not next_char.isupper():
                    return False  # Abbreviation like "Dr."
            return True

        # Other punctuation is usually valid
        return True

    def _find_soft_break(self) -> Optional[int]:
        """Find position of soft break (comma, semicolon, etc.)."""
        for i in range(len(self._buffer) - 1, -1, -1):
            if self._buffer[i] in self.config.soft_break_chars:
                return i
        return None

    def _find_word_boundary(self) -> Optional[int]:
        """Find position of word boundary (space)."""
        # Find last space
        for i in range(len(self._buffer) - 1, -1, -1):
            if self._buffer[i] == " ":
                return i
        return None

    def flush(self) -> Optional[str]:
        """Flush remaining buffer content.

        Returns:
            Remaining text or None if empty.
        """
        if self._buffer.strip():
            result = self._buffer.strip()
            self._buffer = ""
            return result
        return None
