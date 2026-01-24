"""Audio and text buffers for streaming."""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AudioBuffer:
    """Thread-safe audio buffer for streaming.

    Accumulates audio chunks and provides them for processing.
    """

    sample_rate: int = 16000
    max_duration_seconds: float = 30.0
    _chunks: deque = field(default_factory=deque)
    _total_samples: int = 0

    @property
    def max_samples(self) -> int:
        """Maximum number of samples to buffer."""
        return int(self.sample_rate * self.max_duration_seconds)

    @property
    def duration_seconds(self) -> float:
        """Current buffer duration in seconds."""
        return self._total_samples / self.sample_rate

    @property
    def is_empty(self) -> bool:
        """Whether buffer is empty."""
        return len(self._chunks) == 0

    def append(self, chunk: bytes) -> None:
        """Append audio chunk to buffer.

        Args:
            chunk: PCM16 audio bytes.
        """
        # Calculate samples (16-bit = 2 bytes per sample)
        samples = len(chunk) // 2

        # Check if we need to drop old data
        while self._total_samples + samples > self.max_samples and self._chunks:
            old_chunk = self._chunks.popleft()
            self._total_samples -= len(old_chunk) // 2

        self._chunks.append(chunk)
        self._total_samples += samples

    def get_all(self) -> bytes:
        """Get all buffered audio and clear buffer.

        Returns:
            All audio as single bytes object.
        """
        if not self._chunks:
            return b""

        result = b"".join(self._chunks)
        self.clear()
        return result

    def peek_all(self) -> bytes:
        """Get all buffered audio without clearing.

        Returns:
            All audio as single bytes object.
        """
        if not self._chunks:
            return b""
        return b"".join(self._chunks)

    def clear(self) -> None:
        """Clear the buffer."""
        self._chunks.clear()
        self._total_samples = 0


class TextBuffer:
    """Buffer for accumulating text with sentence detection."""

    def __init__(
        self,
        sentence_end_chars: Optional[list[str]] = None,
        min_chars: int = 1,
    ):
        """Initialize text buffer.

        Args:
            sentence_end_chars: Characters that end a sentence.
            min_chars: Minimum characters for a valid sentence.
        """
        self.sentence_end_chars = sentence_end_chars or [".", "!", "?", "\n"]
        self.min_chars = min_chars
        self._buffer = ""

    @property
    def content(self) -> str:
        """Current buffer content."""
        return self._buffer

    @property
    def is_empty(self) -> bool:
        """Whether buffer is empty."""
        return len(self._buffer.strip()) == 0

    def append(self, text: str) -> None:
        """Append text to buffer.

        Args:
            text: Text to append.
        """
        self._buffer += text

    def extract_sentences(self) -> list[str]:
        """Extract complete sentences from buffer.

        Returns:
            List of complete sentences. Incomplete sentence
            remains in buffer.
        """
        sentences = []
        last_boundary = -1

        for i, char in enumerate(self._buffer):
            if char in self.sentence_end_chars:
                sentence = self._buffer[last_boundary + 1 : i + 1].strip()
                if len(sentence) >= self.min_chars:
                    sentences.append(sentence)
                    last_boundary = i

        # Update buffer to contain only unprocessed text
        self._buffer = self._buffer[last_boundary + 1 :]

        return sentences

    def flush(self) -> Optional[str]:
        """Flush remaining content.

        Returns:
            Remaining text or None if empty.
        """
        if self._buffer.strip():
            result = self._buffer.strip()
            self._buffer = ""
            return result
        return None

    def clear(self) -> None:
        """Clear the buffer."""
        self._buffer = ""


class AsyncQueue:
    """Simple async queue wrapper with timeout support."""

    def __init__(self, maxsize: int = 0):
        """Initialize queue.

        Args:
            maxsize: Maximum queue size (0 = unlimited).
        """
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def put(self, item: any, timeout: Optional[float] = None) -> None:
        """Put item in queue.

        Args:
            item: Item to add.
            timeout: Optional timeout in seconds.
        """
        if timeout:
            await asyncio.wait_for(self._queue.put(item), timeout=timeout)
        else:
            await self._queue.put(item)

    async def get(self, timeout: Optional[float] = None) -> any:
        """Get item from queue.

        Args:
            timeout: Optional timeout in seconds.

        Returns:
            Item from queue.

        Raises:
            asyncio.TimeoutError: If timeout exceeded.
        """
        if timeout:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        else:
            return await self._queue.get()

    def get_nowait(self) -> any:
        """Get item without waiting.

        Returns:
            Item from queue.

        Raises:
            asyncio.QueueEmpty: If queue is empty.
        """
        return self._queue.get_nowait()

    def put_nowait(self, item: any) -> None:
        """Put item without waiting.

        Args:
            item: Item to add.

        Raises:
            asyncio.QueueFull: If queue is full.
        """
        self._queue.put_nowait(item)

    @property
    def empty(self) -> bool:
        """Whether queue is empty."""
        return self._queue.empty()

    @property
    def qsize(self) -> int:
        """Current queue size."""
        return self._queue.qsize()
