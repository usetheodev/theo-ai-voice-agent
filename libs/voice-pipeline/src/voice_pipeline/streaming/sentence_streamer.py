"""Sentence-level streaming for LLM → TTS.

Buffers LLM tokens and emits complete sentences for TTS synthesis.
This reduces latency by starting TTS before the full LLM response is ready.

Optimizations for low-latency voice applications:
- Quick phrases (Olá!, Sim., Não.) are emitted immediately
- Adaptive min_chars based on punctuation type
- Timeout-based emission for long pauses
- Configurable via builder pattern
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Set


# Common short phrases that should be emitted immediately
# These are typical conversational responses that don't need buffering
QUICK_PHRASES_PT = {
    "olá", "oi", "sim", "não", "ok", "certo", "claro", "entendi",
    "obrigado", "obrigada", "tchau", "adeus", "bem", "bom", "ótimo",
    "legal", "beleza", "pronto", "feito", "perfeito",
}

QUICK_PHRASES_EN = {
    "hi", "hello", "yes", "no", "ok", "okay", "sure", "right",
    "thanks", "bye", "goodbye", "well", "good", "great", "nice",
    "cool", "done", "perfect", "got it", "i see",
}

QUICK_PHRASES = QUICK_PHRASES_PT | QUICK_PHRASES_EN


@dataclass
class SentenceStreamerConfig:
    """Configuration for sentence streaming.

    Attributes:
        sentence_end_chars: Characters that end sentences (., !, ?, newline).
        soft_break_chars: Softer boundaries for long sentences (;, :, ,).
        min_chars: Minimum characters before emitting (default 20).
        min_chars_exclamation: Min chars for ! sentences (default 5).
        min_chars_question: Min chars for ? sentences (default 8).
        max_chars: Maximum characters before forcing emit (default 200).
        use_soft_breaks: Use soft breaks after max_chars (default True).
        timeout_ms: Emit buffer after this many ms without punctuation (default 500).
        enable_quick_phrases: Emit common short phrases immediately (default True).
        quick_phrases: Set of quick phrases to detect (lowercase).

    Example:
        >>> config = SentenceStreamerConfig(
        ...     min_chars=10,
        ...     timeout_ms=300,
        ...     enable_quick_phrases=True,
        ... )
        >>> streamer = SentenceStreamer(config)
    """

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

    # Adaptive min_chars for different punctuation
    min_chars_exclamation: int = 5   # ! sentences can be shorter (Olá!)
    min_chars_question: int = 8      # ? sentences (Sim?)

    # Maximum characters before forcing emit
    max_chars: int = 200

    # Use soft breaks only after max_chars
    use_soft_breaks: bool = True

    # Timeout: emit buffer after this many ms without punctuation
    # Set to 0 to disable timeout-based emission
    timeout_ms: int = 500

    # Quick phrases: emit immediately without waiting for min_chars
    enable_quick_phrases: bool = True

    # Custom quick phrases (lowercase, without punctuation)
    quick_phrases: Set[str] = field(default_factory=lambda: QUICK_PHRASES.copy())


class SentenceStreamer:
    """Buffers text tokens and emits complete sentences.

    This is the "PunctuatedBufferStreamer" pattern from the research paper,
    optimized for low-latency voice applications.

    Features:
    - Detects sentence boundaries (., !, ?, newline)
    - Quick phrases ("Olá!", "Sim.") emitted immediately
    - Adaptive min_chars based on punctuation type
    - Timeout-based emission for long pauses
    - Soft breaks (;, :, ,) for very long sentences

    Example (streaming):
        streamer = SentenceStreamer()

        async for sentence in streamer.process_stream(llm_token_stream):
            # Each sentence is ready for TTS
            audio = await tts.synthesize(sentence)

    Example (token-by-token):
        streamer = SentenceStreamer()

        for token in tokens:
            sentences = streamer.process(token)
            for sentence in sentences:
                # Process each complete sentence
                pass
        # Don't forget to flush at the end
        remaining = streamer.flush()

    Example (with timeout):
        # For real-time applications where you need emission even without punctuation
        streamer = SentenceStreamer(SentenceStreamerConfig(timeout_ms=300))

        async for sentence in streamer.process_stream_with_timeout(token_stream):
            print(sentence)  # Emits after 300ms pause even without punctuation
    """

    def __init__(self, config: Optional[SentenceStreamerConfig] = None):
        """Initialize streamer.

        Args:
            config: Streaming configuration.
        """
        self.config = config or SentenceStreamerConfig()
        self._buffer = ""
        self._last_token_time: Optional[float] = None

    def reset(self) -> None:
        """Reset buffer state."""
        self._buffer = ""
        self._last_token_time = None

    @property
    def buffer_length(self) -> int:
        """Current buffer length in characters."""
        return len(self._buffer)

    @property
    def buffer_content(self) -> str:
        """Current buffer content (for debugging)."""
        return self._buffer

    def process(self, token: str) -> list[str]:
        """Process a single token and return any complete sentences.

        This is the synchronous API for token-by-token processing,
        useful when you're already iterating over tokens yourself.

        Args:
            token: A text token to add to the buffer.

        Returns:
            List of complete sentences ready for TTS (may be empty).
        """
        self._buffer += token
        self._last_token_time = time.perf_counter()
        return self._extract_sentences()

    async def process_stream(
        self,
        token_stream: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Process a token stream and yield complete sentences.

        This is the async API for processing entire token streams.

        Args:
            token_stream: Async iterator of text tokens/chunks.

        Yields:
            Complete sentences ready for TTS.
        """
        self._buffer = ""

        async for token in token_stream:
            self._buffer += token
            self._last_token_time = time.perf_counter()

            # Check for sentence boundaries
            sentences = self._extract_sentences()

            for sentence in sentences:
                if sentence.strip():
                    yield sentence.strip()

        # Yield remaining buffer
        if self._buffer.strip():
            yield self._buffer.strip()
            self._buffer = ""

    async def process_stream_with_timeout(
        self,
        token_stream: AsyncIterator[str],
    ) -> AsyncIterator[str]:
        """Process a token stream with timeout-based emission.

        Similar to process_stream(), but also emits the buffer if no tokens
        arrive within timeout_ms milliseconds. This is useful for real-time
        applications where the LLM may pause mid-sentence.

        Args:
            token_stream: Async iterator of text tokens/chunks.

        Yields:
            Complete sentences ready for TTS.
        """
        self._buffer = ""
        timeout_sec = self.config.timeout_ms / 1000.0

        if timeout_sec <= 0:
            # No timeout, use regular processing
            async for sentence in self.process_stream(token_stream):
                yield sentence
            return

        # Create an async queue to handle tokens with timeout
        token_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        stream_done = False

        async def token_producer():
            nonlocal stream_done
            try:
                async for token in token_stream:
                    await token_queue.put(token)
                await token_queue.put(None)  # Signal end
            finally:
                stream_done = True
                await token_queue.put(None)

        # Start producer
        producer_task = asyncio.create_task(token_producer())

        try:
            while True:
                try:
                    token = await asyncio.wait_for(
                        token_queue.get(),
                        timeout=timeout_sec,
                    )

                    if token is None:
                        # Stream ended
                        break

                    self._buffer += token
                    self._last_token_time = time.perf_counter()

                    # Check for sentence boundaries
                    sentences = self._extract_sentences()
                    for sentence in sentences:
                        if sentence.strip():
                            yield sentence.strip()

                except asyncio.TimeoutError:
                    # Timeout: emit buffer if not empty
                    if self._buffer.strip():
                        yield self._buffer.strip()
                        self._buffer = ""

                    # Check if stream is done
                    if stream_done:
                        break

            # Yield remaining buffer
            if self._buffer.strip():
                yield self._buffer.strip()
                self._buffer = ""

        finally:
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass

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
                # Check if we should force emit due to max_chars
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
            end_char = self._buffer[boundary_pos]

            # Get adaptive min_chars based on punctuation
            min_chars = self._get_min_chars(end_char, sentence)

            # Check minimum length
            if len(sentence.strip()) >= min_chars:
                sentences.append(sentence)
                self._buffer = self._buffer[boundary_pos + 1 :]
            else:
                # Too short, keep buffering
                break

        return sentences

    def _get_min_chars(self, end_char: str, sentence: str) -> int:
        """Get adaptive min_chars based on punctuation and content.

        Args:
            end_char: The sentence-ending character.
            sentence: The complete sentence.

        Returns:
            Minimum characters required for this sentence.
        """
        # Check for quick phrases first
        if self.config.enable_quick_phrases:
            # Extract word without punctuation
            word = sentence.strip().rstrip(".!?").lower()
            if word in self.config.quick_phrases:
                return 1  # Emit immediately

        # Adaptive min_chars based on punctuation
        if end_char == "!":
            return self.config.min_chars_exclamation
        elif end_char == "?":
            return self.config.min_chars_question
        else:
            return self.config.min_chars

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

    def time_since_last_token(self) -> Optional[float]:
        """Get time in seconds since last token was received.

        Returns:
            Time in seconds, or None if no tokens received yet.
        """
        if self._last_token_time is None:
            return None
        return time.perf_counter() - self._last_token_time

    def should_emit_timeout(self) -> bool:
        """Check if buffer should be emitted due to timeout.

        Returns:
            True if timeout_ms has passed since last token and buffer is not empty.
        """
        if self.config.timeout_ms <= 0:
            return False
        if not self._buffer.strip():
            return False
        elapsed = self.time_since_last_token()
        if elapsed is None:
            return False
        return elapsed * 1000 >= self.config.timeout_ms
