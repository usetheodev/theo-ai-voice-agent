"""Integration tests for Pipeline."""

import pytest
import asyncio
from typing import AsyncIterator, Optional

from voice_pipeline import (
    Pipeline,
    PipelineConfig,
    ASRInterface,
    TranscriptionResult,
    LLMInterface,
    LLMChunk,
    TTSInterface,
    AudioChunk,
    VADInterface,
    VADEvent,
    SpeechState,
    PipelineEventType,
)


class MockASR(ASRInterface):
    """Mock ASR for testing."""

    def __init__(self, response: str = "Hello world"):
        self.response = response

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        # Consume audio stream
        async for _ in audio_stream:
            pass
        yield TranscriptionResult(text=self.response, is_final=True)


class MockLLM(LLMInterface):
    """Mock LLM for testing."""

    def __init__(self, response: str = "I'm doing great!"):
        self.response = response

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        # Stream word by word
        words = self.response.split()
        for i, word in enumerate(words):
            text = word + (" " if i < len(words) - 1 else "")
            yield LLMChunk(text=text)


class MockTTS(TTSInterface):
    """Mock TTS for testing."""

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        async for text in text_stream:
            # Generate fake audio (1 sample per character)
            audio_data = b"\x00\x00" * len(text)
            yield AudioChunk(data=audio_data, sample_rate=16000)


class MockVAD(VADInterface):
    """Mock VAD for testing."""

    def __init__(self, speech_frames: int = 10):
        self.speech_frames = speech_frames
        self.frame_count = 0

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        self.frame_count += 1
        is_speech = self.frame_count <= self.speech_frames
        return VADEvent(
            is_speech=is_speech,
            confidence=0.9 if is_speech else 0.1,
            state=SpeechState.SPEECH if is_speech else SpeechState.SILENCE,
        )

    def reset(self) -> None:
        self.frame_count = 0


class TestPipelineCreation:
    """Tests for Pipeline creation."""

    def test_create_pipeline(self):
        """Test creating a pipeline with mock providers."""
        config = PipelineConfig(
            system_prompt="You are a test assistant.",
            language="en",
        )

        pipeline = Pipeline(
            config=config,
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        assert pipeline is not None
        assert pipeline.config.system_prompt == "You are a test assistant."
        assert pipeline.state_machine.is_idle

    def test_event_registration(self):
        """Test registering event handlers."""
        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        events_received = []

        def handler(event):
            events_received.append(event.type)

        pipeline.on(PipelineEventType.TRANSCRIPTION, handler)
        pipeline.on_all(lambda e: None)  # Should not fail

    def test_reset_pipeline(self):
        """Test resetting pipeline state."""
        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        # Modify some state
        pipeline.context.messages.append({"role": "user", "content": "test"})
        pipeline.metrics.barge_in_count = 5

        pipeline.reset()

        assert len(pipeline.context.messages) == 0
        assert pipeline.metrics.barge_in_count == 0
        assert pipeline.state_machine.is_idle

    def test_get_metrics(self):
        """Test getting pipeline metrics."""
        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        metrics = pipeline.get_metrics()

        assert metrics.total_latency_ms == 0.0
        assert metrics.barge_in_count == 0


class TestMockProviders:
    """Tests for mock providers used in integration tests."""

    @pytest.mark.asyncio
    async def test_mock_asr(self):
        """Test MockASR produces transcription."""
        asr = MockASR(response="Test transcription")

        async def audio_stream():
            yield b"\x00\x00" * 100

        results = []
        async for result in asr.transcribe_stream(audio_stream()):
            results.append(result)

        assert len(results) == 1
        assert results[0].text == "Test transcription"
        assert results[0].is_final

    @pytest.mark.asyncio
    async def test_mock_llm(self):
        """Test MockLLM produces chunks."""
        llm = MockLLM(response="Hello world test")

        chunks = []
        async for chunk in llm.generate_stream([]):
            chunks.append(chunk.text)

        assert "Hello" in "".join(chunks)
        assert "world" in "".join(chunks)

    @pytest.mark.asyncio
    async def test_mock_tts(self):
        """Test MockTTS produces audio."""
        tts = MockTTS()

        async def text_stream():
            yield "Hello"
            yield "World"

        chunks = []
        async for chunk in tts.synthesize_stream(text_stream()):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert all(isinstance(c.data, bytes) for c in chunks)

    @pytest.mark.asyncio
    async def test_mock_vad(self):
        """Test MockVAD detects speech."""
        vad = MockVAD(speech_frames=3)

        events = []
        for _ in range(5):
            event = await vad.process(b"\x00\x00", 16000)
            events.append(event)

        # First 3 should be speech
        assert events[0].is_speech
        assert events[1].is_speech
        assert events[2].is_speech
        # Last 2 should be silence
        assert not events[3].is_speech
        assert not events[4].is_speech
