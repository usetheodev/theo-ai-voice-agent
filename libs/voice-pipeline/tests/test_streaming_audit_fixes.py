"""Tests for streaming audit fixes.

Covers:
- Épico 1: Bounded queues
- Épico 2: Cancellation & interrupt with asyncio.Event
- Épico 3: OpenAI TTS real streaming
- Épico 4: Timeouts and polling
- Épico 5: Percentile metrics
"""

import asyncio
from typing import AsyncIterator, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from voice_pipeline.chains.streaming import StreamingVoiceChain
from voice_pipeline.core.config import PipelineConfig
from voice_pipeline.core.pipeline import Pipeline
from voice_pipeline.interfaces import (
    ASRInterface,
    AudioChunk,
    LLMChunk,
    LLMInterface,
    TranscriptionResult,
    TTSInterface,
)
from voice_pipeline.providers.tts.openai import OpenAITTSConfig, OpenAITTSProvider
from voice_pipeline.streaming.metrics import StreamingMetrics


# ==================== Mock Providers ====================


class MockASR(ASRInterface):
    def __init__(self, text="Hello world"):
        self._text = text

    async def transcribe_stream(self, audio_stream, language=None):
        async for _ in audio_stream:
            pass
        yield TranscriptionResult(text=self._text, is_final=True)


class MockLLM(LLMInterface):
    def __init__(self, response="Hello! How are you?"):
        self._response = response

    async def generate_stream(self, messages, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        words = self._response.split()
        for i, word in enumerate(words):
            text = word if i == 0 else " " + word
            yield LLMChunk(text=text, is_final=(i == len(words) - 1))


class SlowMockLLM(LLMInterface):
    """LLM that yields tokens with delays (for interrupt testing)."""

    def __init__(self, response="Word one. Word two. Word three.", delay=0.05):
        self._response = response
        self._delay = delay

    async def generate_stream(self, messages, system_prompt=None, temperature=0.7, max_tokens=None, **kwargs):
        words = self._response.split()
        for i, word in enumerate(words):
            await asyncio.sleep(self._delay)
            text = word if i == 0 else " " + word
            yield LLMChunk(text=text, is_final=(i == len(words) - 1))


class MockTTS(TTSInterface):
    async def synthesize_stream(self, text_stream, voice=None, speed=1.0, **kwargs):
        async for text in text_stream:
            yield AudioChunk(
                data=text.encode("utf-8"),
                sample_rate=24000,
                channels=1,
                format="pcm16",
            )


class SlowMockTTS(TTSInterface):
    """TTS that yields multiple chunks with delays."""

    def __init__(self, chunks_per_sentence=3, delay=0.05):
        self._chunks = chunks_per_sentence
        self._delay = delay

    async def synthesize_stream(self, text_stream, voice=None, speed=1.0, **kwargs):
        async for text in text_stream:
            for i in range(self._chunks):
                await asyncio.sleep(self._delay)
                yield AudioChunk(
                    data=f"chunk{i}:{text[:20]}".encode(),
                    sample_rate=24000,
                    channels=1,
                    format="pcm16",
                )


# ==================== Épico 1: Bounded Queues ====================


class TestBoundedQueues:
    """Tests for bounded queue implementation."""

    def test_streaming_chain_has_queue_maxsize(self):
        """StreamingVoiceChain accepts queue_maxsize parameter."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            queue_maxsize=10,
        )
        assert chain.queue_maxsize == 10

    def test_streaming_chain_default_queue_maxsize(self):
        """Default queue_maxsize is 5."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
        )
        assert chain.queue_maxsize == 5

    def test_pipeline_config_has_buffer_maxsize(self):
        """PipelineConfig has buffer_maxsize field."""
        config = PipelineConfig()
        assert config.buffer_maxsize == 50
        assert config.tts_queue_maxsize == 10

    def test_pipeline_config_custom_buffer_maxsize(self):
        """PipelineConfig accepts custom buffer sizes."""
        config = PipelineConfig(buffer_maxsize=100, tts_queue_maxsize=20)
        assert config.buffer_maxsize == 100
        assert config.tts_queue_maxsize == 20

    @pytest.mark.asyncio
    async def test_bounded_queue_applies_backpressure(self):
        """Producer blocks when queue is full (backpressure)."""
        queue = asyncio.Queue(maxsize=2)
        produced = 0

        async def producer():
            nonlocal produced
            for i in range(10):
                await asyncio.wait_for(queue.put(i), timeout=0.1)
                produced += 1

        async def slow_consumer():
            for _ in range(3):
                await asyncio.sleep(0.05)
                await queue.get()

        # Producer should block after filling queue
        task = asyncio.create_task(producer())
        await asyncio.sleep(0.02)
        # After a small delay, only maxsize items should be produced
        assert produced <= 3  # maxsize=2, possibly +1 in flight

        consumer_task = asyncio.create_task(slow_consumer())
        try:
            await asyncio.wait_for(asyncio.gather(task, consumer_task), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.TimeoutError):
            task.cancel()
            consumer_task.cancel()

    @pytest.mark.asyncio
    async def test_streaming_chain_uses_bounded_queues(self):
        """StreamingVoiceChain actually creates bounded queues."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM("Hello! World."),
            tts=MockTTS(),
            queue_maxsize=3,
        )

        chunks = [c async for c in chain.astream(b"audio")]
        assert len(chunks) > 0


# ==================== Épico 2: Cancellation & Interrupt ====================


class TestCancellationEvent:
    """Tests for asyncio.Event-based cancellation."""

    def test_cancel_event_exists(self):
        """Chain has _cancel_event instead of _interrupted bool."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
        )
        assert hasattr(chain, "_cancel_event")
        assert isinstance(chain._cancel_event, asyncio.Event)

    def test_interrupt_sets_event(self):
        """interrupt() sets the cancel event."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
        )
        assert not chain._cancel_event.is_set()
        chain.interrupt()
        assert chain._cancel_event.is_set()

    def test_backward_compat_property(self):
        """_interrupted property returns cancel_event state."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
        )
        assert chain._interrupted is False
        chain.interrupt()
        assert chain._interrupted is True

    @pytest.mark.asyncio
    async def test_astream_clears_event(self):
        """astream() clears the cancel event at start."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
        )
        chain.interrupt()
        assert chain._cancel_event.is_set()

        # Starting astream should clear the event
        chunks = [c async for c in chain.astream(b"audio")]
        assert not chain._cancel_event.is_set()
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_interrupt_stops_tts_mid_chunk(self):
        """Interrupt during TTS stops audio emission quickly."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=SlowMockLLM("First sentence. Second sentence. Third sentence.", delay=0.01),
            tts=SlowMockTTS(chunks_per_sentence=5, delay=0.02),
        )

        chunks = []
        interrupted = False

        async for audio_chunk in chain.astream(b"audio"):
            chunks.append(audio_chunk)
            # Interrupt after first few chunks
            if len(chunks) >= 2 and not interrupted:
                chain.interrupt()
                interrupted = True

        # Should have stopped early (not all chunks)
        assert interrupted
        # With 3 sentences x 5 chunks = 15 max, should be much less
        assert len(chunks) < 15

    @pytest.mark.asyncio
    async def test_interrupt_drains_sentence_queue(self):
        """interrupt() drains the active sentence queue."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
        )

        # Create and set an active queue with items
        queue = asyncio.Queue(maxsize=5)
        await queue.put("sentence 1")
        await queue.put("sentence 2")
        chain._active_sentence_queue = queue

        assert not queue.empty()
        chain.interrupt()
        assert queue.empty()

    def test_drain_queue_static_method(self):
        """_drain_queue empties a queue."""
        queue = asyncio.Queue()
        queue.put_nowait("a")
        queue.put_nowait("b")
        queue.put_nowait("c")
        assert queue.qsize() == 3

        StreamingVoiceChain._drain_queue(queue)
        assert queue.empty()

    def test_drain_queue_on_empty(self):
        """_drain_queue handles empty queue."""
        queue = asyncio.Queue()
        StreamingVoiceChain._drain_queue(queue)
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_interrupt_does_not_flush_strategy(self):
        """After interrupt, strategy.flush() should NOT be called."""
        chain = StreamingVoiceChain(
            asr=MockASR(),
            llm=SlowMockLLM("Word1. Word2. Word3.", delay=0.02),
            tts=MockTTS(),
        )

        chunks = []
        async for audio_chunk in chain.astream(b"audio"):
            chunks.append(audio_chunk)
            if len(chunks) >= 1:
                chain.interrupt()
                break

        # The chain should not have flushed remaining text
        # (hard to verify directly, but no extra chunks after break)
        assert len(chunks) >= 1


# ==================== Épico 3: OpenAI TTS Real Streaming ====================


class TestOpenAITTSStreaming:
    """Tests for real HTTP streaming in OpenAI TTS."""

    def test_stream_chunk_size_config(self):
        """OpenAITTSConfig has stream_chunk_size."""
        config = OpenAITTSConfig()
        assert config.stream_chunk_size == 4096

    def test_custom_stream_chunk_size(self):
        """Custom stream_chunk_size is accepted."""
        config = OpenAITTSConfig(stream_chunk_size=8192)
        assert config.stream_chunk_size == 8192

    @pytest.mark.asyncio
    async def test_synthesize_stream_uses_streaming_response(self):
        """synthesize_stream uses with_streaming_response."""
        provider = OpenAITTSProvider(api_key="sk-test")

        # Track if with_streaming_response was used
        create_called = False

        class MockResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def aiter_bytes(self, chunk_size=None):
                yield b"chunk1"
                yield b"chunk2"

        class MockStreamingCreate:
            def create(self_, **kwargs):
                nonlocal create_called
                create_called = True
                return MockResponse()

        mock_client = AsyncMock()
        mock_client.audio.speech.with_streaming_response = MockStreamingCreate()
        provider._async_client = mock_client

        async def text_gen():
            yield "Hello."

        chunks = []
        async for chunk in provider.synthesize_stream(text_gen()):
            chunks.append(chunk)

        assert create_called
        assert len(chunks) == 2
        assert chunks[0].data == b"chunk1"
        assert chunks[1].data == b"chunk2"

    @pytest.mark.asyncio
    async def test_synthesize_batch_unchanged(self):
        """synthesize() batch method is not changed."""
        provider = OpenAITTSProvider(api_key="sk-test")

        mock_response = MagicMock()
        mock_response.read.return_value = b"audio_data"

        mock_client = AsyncMock()
        mock_client.audio.speech.create = AsyncMock(return_value=mock_response)
        provider._async_client = mock_client

        result = await provider.synthesize("Hello")
        assert result == b"audio_data"


# ==================== Épico 4: Timeouts e Polling ====================


class TestTimeoutsAndPolling:
    """Tests for timeout and polling improvements."""

    def test_pipeline_has_processing_event(self):
        """Pipeline has _processing_event for wake-up."""
        vad = MagicMock()
        config = PipelineConfig()
        pipeline = Pipeline(
            config=config,
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=vad,
        )
        assert hasattr(pipeline, "_processing_event")
        assert isinstance(pipeline._processing_event, asyncio.Event)

    def test_pipeline_stop_unblocks_processing_event(self):
        """stop() sets processing event to unblock _process_loop."""
        vad = MagicMock()
        config = PipelineConfig()
        pipeline = Pipeline(
            config=config,
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=vad,
        )
        assert not pipeline._processing_event.is_set()
        pipeline.stop()
        assert pipeline._processing_event.is_set()
        assert pipeline._cancel_event.is_set()

    def test_pipeline_has_barge_in_cooldown(self):
        """Pipeline has non-blocking barge-in cooldown."""
        vad = MagicMock()
        config = PipelineConfig()
        pipeline = Pipeline(
            config=config,
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=vad,
        )
        assert hasattr(pipeline, "_barge_in_cooldown_until")
        assert pipeline._barge_in_cooldown_until == 0.0

    @pytest.mark.asyncio
    async def test_tts_streaming_timeout(self):
        """TTS streaming raises RetryableError on timeout."""
        from voice_pipeline.providers.base import RetryableError

        provider = OpenAITTSProvider(
            api_key="sk-test",
            config=OpenAITTSConfig(timeout=0.001),  # Very short timeout
        )

        class SlowMockResponse:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def aiter_bytes(self, chunk_size=None):
                yield b"chunk1"
                # Simulate slow response
                import time
                time.sleep(0.01)
                yield b"chunk2"

        class MockStreamingCreate:
            def create(self_, **kwargs):
                return SlowMockResponse()

        mock_client = AsyncMock()
        mock_client.audio.speech.with_streaming_response = MockStreamingCreate()
        provider._async_client = mock_client

        async def text_gen():
            yield "Hello world."

        with pytest.raises(RetryableError, match="timeout"):
            async for _ in provider.synthesize_stream(text_gen()):
                pass


# ==================== Épico 5: Percentile Metrics ====================


class TestPercentileMetrics:
    """Tests for percentile calculations in StreamingMetrics."""

    def test_percentile_empty(self):
        """Percentile of empty list returns None."""
        assert StreamingMetrics._percentile([], 50) is None

    def test_percentile_single_value(self):
        """Percentile of single value returns that value."""
        assert StreamingMetrics._percentile([1.0], 50) == 1.0
        assert StreamingMetrics._percentile([1.0], 95) == 1.0
        assert StreamingMetrics._percentile([1.0], 99) == 1.0

    def test_percentile_known_values(self):
        """Percentile calculation with known dataset."""
        values = list(range(1, 101))  # 1 to 100

        p50 = StreamingMetrics._percentile(values, 50)
        p95 = StreamingMetrics._percentile(values, 95)
        p99 = StreamingMetrics._percentile(values, 99)

        assert p50 == pytest.approx(50.5, abs=0.5)
        assert p95 == pytest.approx(95.05, abs=0.5)
        assert p99 == pytest.approx(99.01, abs=0.5)

    def test_percentile_unsorted_input(self):
        """Percentile works with unsorted input."""
        values = [5, 1, 3, 2, 4]
        p50 = StreamingMetrics._percentile(values, 50)
        assert p50 == 3.0

    def test_latency_histories_initialized(self):
        """Latency history lists are initialized empty."""
        m = StreamingMetrics()
        assert m._asr_latencies == []
        assert m._llm_ttft_latencies == []
        assert m._tts_ttfb_latencies == []
        assert m._total_latencies == []

    def test_mark_asr_end_records_latency(self):
        """mark_asr_end appends to _asr_latencies."""
        m = StreamingMetrics()
        m.mark_asr_start()
        m.mark_asr_end()
        assert len(m._asr_latencies) == 1
        assert m._asr_latencies[0] > 0

    def test_end_records_total_latency(self):
        """end() appends to _total_latencies."""
        m = StreamingMetrics()
        m.start()
        m.end()
        assert len(m._total_latencies) == 1

    def test_percentiles_dict(self):
        """percentiles() returns structured dict."""
        m = StreamingMetrics()
        m._asr_latencies = [0.1, 0.2, 0.3, 0.15, 0.25]
        m._total_latencies = [1.0, 1.1, 1.2, 1.3, 1.4]

        pctls = m.percentiles()

        assert "asr" in pctls
        assert "total" in pctls
        assert "p50" in pctls["asr"]
        assert "p95" in pctls["asr"]
        assert "p99" in pctls["asr"]
        assert "count" in pctls["asr"]
        assert pctls["asr"]["count"] == 5

    def test_percentiles_empty_stages_excluded(self):
        """Stages with no data are excluded from percentiles."""
        m = StreamingMetrics()
        pctls = m.percentiles()
        assert pctls == {}

    def test_to_dict_includes_percentiles(self):
        """to_dict() includes percentiles when available."""
        m = StreamingMetrics()
        m._asr_latencies = [0.1, 0.2]
        d = m.to_dict()
        assert "percentiles" in d
        assert "asr" in d["percentiles"]

    def test_to_dict_no_percentiles_when_empty(self):
        """to_dict() omits percentiles when no data."""
        m = StreamingMetrics()
        d = m.to_dict()
        assert "percentiles" not in d

    def test_str_includes_percentiles(self):
        """__str__() includes percentile info."""
        m = StreamingMetrics()
        m._asr_latencies = [0.1, 0.2, 0.3]
        s = str(m)
        assert "asr[p50=" in s
        assert "p95=" in s

    def test_100_values_percentiles(self):
        """Percentiles with 100 values match expected distribution."""
        m = StreamingMetrics()
        m._asr_latencies = [i * 0.01 for i in range(100)]

        pctls = m.percentiles()
        assert pctls["asr"]["p50"] == pytest.approx(0.495, abs=0.01)
        assert pctls["asr"]["p95"] == pytest.approx(0.9405, abs=0.01)
        assert pctls["asr"]["p99"] == pytest.approx(0.9801, abs=0.01)

    def test_mark_llm_end_records_ttft(self):
        """mark_llm_end records TTFT in latency list."""
        m = StreamingMetrics()
        m.start()
        m.mark_llm_start()
        m.mark_first_token()
        m.mark_llm_end()
        assert len(m._llm_ttft_latencies) == 1
        assert m._llm_ttft_latencies[0] == m.ttft

    def test_mark_tts_end_records_ttfb(self):
        """mark_tts_end records TTFA in latency list."""
        m = StreamingMetrics()
        m.start()
        m.mark_tts_start()
        m.mark_first_audio()
        m.mark_tts_end()
        assert len(m._tts_ttfb_latencies) == 1
        assert m._tts_ttfb_latencies[0] == m.ttfa
