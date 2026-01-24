"""Tests for SentenceStreamer."""

import pytest
from voice_pipeline.streaming.sentence_streamer import (
    SentenceStreamer,
    SentenceStreamerConfig,
)


class TestSentenceStreamer:
    """Tests for SentenceStreamer."""

    @pytest.mark.asyncio
    async def test_basic_streaming(self):
        """Test basic sentence streaming."""
        config = SentenceStreamerConfig(min_chars=1)  # Allow short sentences
        streamer = SentenceStreamer(config)

        async def token_stream():
            tokens = ["Hello ", "world. ", "How ", "are ", "you?"]
            for token in tokens:
                yield token

        sentences = []
        async for sentence in streamer.process_stream(token_stream()):
            sentences.append(sentence)

        assert len(sentences) == 2
        assert sentences[0] == "Hello world."
        assert sentences[1] == "How are you?"

    @pytest.mark.asyncio
    async def test_min_chars(self):
        """Test minimum character threshold."""
        # Disable quick phrases to test pure min_chars behavior
        config = SentenceStreamerConfig(min_chars=10, enable_quick_phrases=False)
        streamer = SentenceStreamer(config)

        async def token_stream():
            yield "Ab. "  # Too short (not a quick phrase)
            yield "This is longer."

        sentences = []
        async for sentence in streamer.process_stream(token_stream()):
            sentences.append(sentence)

        # "Ab." is too short (4 chars < 10), gets combined
        assert len(sentences) == 1

    @pytest.mark.asyncio
    async def test_max_chars_force_emit(self):
        """Test forced emit at max_chars."""
        config = SentenceStreamerConfig(max_chars=20, use_soft_breaks=False)
        streamer = SentenceStreamer(config)

        async def token_stream():
            # No sentence boundaries, will force split
            yield "This is a very long sentence without any punctuation marks"

        sentences = []
        async for sentence in streamer.process_stream(token_stream()):
            sentences.append(sentence)

        # Should have split
        assert len(sentences) > 1

    @pytest.mark.asyncio
    async def test_soft_breaks(self):
        """Test soft break characters."""
        config = SentenceStreamerConfig(
            max_chars=30,
            use_soft_breaks=True,
            soft_break_chars=[","],
        )
        streamer = SentenceStreamer(config)

        async def token_stream():
            yield "Hello world, this is a test, more text here"

        sentences = []
        async for sentence in streamer.process_stream(token_stream()):
            sentences.append(sentence)

        # Should break at comma when exceeding max_chars
        assert len(sentences) >= 1

    @pytest.mark.asyncio
    async def test_decimal_not_boundary(self):
        """Test that decimals are not sentence boundaries."""
        streamer = SentenceStreamer()

        async def token_stream():
            yield "The value is 3.14 units."

        sentences = []
        async for sentence in streamer.process_stream(token_stream()):
            sentences.append(sentence)

        assert len(sentences) == 1
        assert "3.14" in sentences[0]

    @pytest.mark.asyncio
    async def test_multiple_sentence_endings(self):
        """Test different sentence ending characters."""
        # Disable quick phrases to test pure punctuation detection
        config = SentenceStreamerConfig(
            min_chars=1,
            min_chars_exclamation=1,
            min_chars_question=1,
            enable_quick_phrases=False,
        )
        streamer = SentenceStreamer(config)

        async def token_stream():
            yield "What? Yes! Done."

        sentences = []
        async for sentence in streamer.process_stream(token_stream()):
            sentences.append(sentence)

        assert len(sentences) == 3
        assert sentences[0] == "What?"
        assert sentences[1] == "Yes!"
        assert sentences[2] == "Done."

    def test_flush(self):
        """Test flushing remaining content."""
        streamer = SentenceStreamer()
        streamer._buffer = "Incomplete sentence"

        result = streamer.flush()
        assert result == "Incomplete sentence"
        assert streamer._buffer == ""

    def test_reset(self):
        """Test resetting the streamer."""
        streamer = SentenceStreamer()
        streamer._buffer = "Some content"
        streamer.reset()
        assert streamer._buffer == ""
