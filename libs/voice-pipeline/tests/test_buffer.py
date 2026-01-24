"""Tests for buffer utilities."""

import pytest
from voice_pipeline.streaming.buffer import AudioBuffer, TextBuffer, AsyncQueue


class TestAudioBuffer:
    """Tests for AudioBuffer."""

    def test_empty_buffer(self):
        """Test empty buffer properties."""
        buffer = AudioBuffer()
        assert buffer.is_empty
        assert buffer.duration_seconds == 0.0
        assert buffer.get_all() == b""

    def test_append_and_get(self):
        """Test appending and getting audio."""
        buffer = AudioBuffer(sample_rate=16000)

        # 1 second of audio = 16000 samples = 32000 bytes
        chunk = b"\x00" * 32000
        buffer.append(chunk)

        assert not buffer.is_empty
        assert buffer.duration_seconds == 1.0

        result = buffer.get_all()
        assert result == chunk
        assert buffer.is_empty

    def test_peek_all(self):
        """Test peeking without clearing."""
        buffer = AudioBuffer()
        chunk = b"\x01\x02\x03\x04"
        buffer.append(chunk)

        result = buffer.peek_all()
        assert result == chunk
        assert not buffer.is_empty  # Still has data

    def test_max_duration_overflow(self):
        """Test that old data is dropped when max duration exceeded."""
        buffer = AudioBuffer(sample_rate=16000, max_duration_seconds=1.0)

        # Add 0.5 seconds
        chunk1 = b"\x01" * 16000  # 0.5s
        buffer.append(chunk1)
        assert buffer.duration_seconds == 0.5

        # Add 0.7 seconds (total would be 1.2s, exceeds max)
        chunk2 = b"\x02" * 22400  # 0.7s
        buffer.append(chunk2)

        # Should have dropped old data
        assert buffer.duration_seconds <= 1.0

    def test_clear(self):
        """Test clearing the buffer."""
        buffer = AudioBuffer()
        buffer.append(b"\x00" * 1000)
        buffer.clear()
        assert buffer.is_empty


class TestTextBuffer:
    """Tests for TextBuffer."""

    def test_empty_buffer(self):
        """Test empty buffer."""
        buffer = TextBuffer()
        assert buffer.is_empty
        assert buffer.content == ""

    def test_append(self):
        """Test appending text."""
        buffer = TextBuffer()
        buffer.append("Hello ")
        buffer.append("world")
        assert buffer.content == "Hello world"

    def test_extract_sentences(self):
        """Test sentence extraction."""
        buffer = TextBuffer()
        buffer.append("Hello world. How are you? I am fine!")

        sentences = buffer.extract_sentences()
        assert len(sentences) == 3
        assert sentences[0] == "Hello world."
        assert sentences[1] == "How are you?"
        assert sentences[2] == "I am fine!"

    def test_extract_partial(self):
        """Test extracting with incomplete sentence."""
        buffer = TextBuffer()
        buffer.append("First sentence. Incomplete")

        sentences = buffer.extract_sentences()
        assert len(sentences) == 1
        assert sentences[0] == "First sentence."
        assert buffer.content == " Incomplete"

    def test_flush(self):
        """Test flushing remaining content."""
        buffer = TextBuffer()
        buffer.append("Some text without period")

        result = buffer.flush()
        assert result == "Some text without period"
        assert buffer.is_empty

    def test_flush_empty(self):
        """Test flushing empty buffer."""
        buffer = TextBuffer()
        assert buffer.flush() is None


class TestAsyncQueue:
    """Tests for AsyncQueue."""

    @pytest.mark.asyncio
    async def test_put_get(self):
        """Test basic put and get."""
        queue = AsyncQueue()
        await queue.put("item1")
        result = await queue.get()
        assert result == "item1"

    @pytest.mark.asyncio
    async def test_put_nowait_get_nowait(self):
        """Test non-blocking operations."""
        queue = AsyncQueue()
        queue.put_nowait("item")
        result = queue.get_nowait()
        assert result == "item"

    def test_empty(self):
        """Test empty property."""
        queue = AsyncQueue()
        assert queue.empty
        queue.put_nowait("item")
        assert not queue.empty

    def test_qsize(self):
        """Test queue size."""
        queue = AsyncQueue()
        assert queue.qsize == 0
        queue.put_nowait("item1")
        queue.put_nowait("item2")
        assert queue.qsize == 2
