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


# ==============================================================================
# PipelineBuilder Integration Tests
# ==============================================================================


class TestPipelineBuilderIntegration:
    """Tests for PipelineBuilder integration."""

    def test_build_pipeline_with_builder(self):
        """Test building pipeline with builder."""
        from voice_pipeline import PipelineBuilder

        pipeline = (
            PipelineBuilder()
            .with_config(system_prompt="Builder test")
            .with_asr(MockASR())
            .with_llm(MockLLM())
            .with_tts(MockTTS())
            .with_vad(MockVAD())
            .build()
        )

        assert pipeline.config.system_prompt == "Builder test"

    def test_build_chain_with_builder(self):
        """Test building chain with builder."""
        from voice_pipeline import PipelineBuilder

        chain = (
            PipelineBuilder()
            .with_asr(MockASR())
            .with_llm(MockLLM())
            .with_tts(MockTTS())
            .build_chain()
        )

        assert chain is not None


# ==============================================================================
# Sentence Extraction Tests
# ==============================================================================


class TestSentenceExtraction:
    """Tests for sentence extraction in pipeline.

    Note: _extract_sentences always returns a list where the last element
    is the incomplete/remaining text (which may be empty).
    """

    def test_extract_sentences_basic(self):
        """Test basic sentence extraction (min_tts_chars=5 for testing)."""
        pipeline = Pipeline(
            config=PipelineConfig(min_tts_chars=5),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        sentences = pipeline._extract_sentences("Hello. World.")
        # Last element is the remaining text (empty in this case)
        assert len(sentences) >= 2
        assert sentences[0] == "Hello."
        assert sentences[1] == "World."

    def test_extract_sentences_question(self):
        """Test sentence extraction with question mark."""
        pipeline = Pipeline(
            config=PipelineConfig(min_tts_chars=5),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        sentences = pipeline._extract_sentences("How are you? I am fine.")
        # Complete sentences are extracted, last may be empty
        assert sentences[0] == "How are you?"
        assert sentences[1] == "I am fine."

    def test_extract_sentences_incomplete(self):
        """Test sentence extraction with incomplete sentence."""
        pipeline = Pipeline(
            config=PipelineConfig(min_tts_chars=5),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        sentences = pipeline._extract_sentences("Hello. This is")
        assert len(sentences) == 2
        assert sentences[0] == "Hello."
        assert "This is" in sentences[1]

    def test_extract_sentences_long_text(self):
        """Test sentence extraction with longer text (default min_tts_chars)."""
        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        text = "This is a longer sentence. And this is another one."
        sentences = pipeline._extract_sentences(text)
        # Should have complete sentences plus remaining (empty)
        assert sentences[0] == "This is a longer sentence."
        assert sentences[1] == "And this is another one."


# ==============================================================================
# Pipeline Configuration Tests
# ==============================================================================


class TestPipelineConfiguration:
    """Tests for pipeline configuration options."""

    def test_barge_in_configuration(self):
        """Test barge-in configuration."""
        pipeline = Pipeline(
            config=PipelineConfig(
                enable_barge_in=True,
                barge_in_threshold_ms=200,
                barge_in_backoff_ms=100,
            ),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        assert pipeline.config.enable_barge_in is True
        assert pipeline.config.barge_in_threshold_ms == 200
        assert pipeline.config.barge_in_backoff_ms == 100

    def test_vad_configuration(self):
        """Test VAD configuration."""
        pipeline = Pipeline(
            config=PipelineConfig(
                vad_silence_ms=500,
            ),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        assert pipeline.config.vad_silence_ms == 500

    def test_llm_configuration(self):
        """Test LLM configuration."""
        pipeline = Pipeline(
            config=PipelineConfig(
                llm_temperature=0.3,
                llm_max_tokens=1000,
            ),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        assert pipeline.config.llm_temperature == 0.3
        assert pipeline.config.llm_max_tokens == 1000


# ==============================================================================
# State Machine Integration Tests
# ==============================================================================


class TestStateMachineIntegration:
    """Tests for state machine integration in pipeline."""

    def test_initial_state(self):
        """Test pipeline starts in IDLE state."""
        from voice_pipeline.core.state_machine import ConversationState

        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        assert pipeline.state_machine.state == ConversationState.IDLE

    def test_transition_to_listening(self):
        """Test manual transition to LISTENING."""
        from voice_pipeline.core.state_machine import ConversationState

        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        pipeline.state_machine.transition_to(ConversationState.LISTENING)
        assert pipeline.state_machine.state == ConversationState.LISTENING

    def test_reset_to_idle(self):
        """Test reset returns to IDLE."""
        from voice_pipeline.core.state_machine import ConversationState

        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        pipeline.state_machine.transition_to(ConversationState.PROCESSING)
        pipeline.reset()
        assert pipeline.state_machine.state == ConversationState.IDLE


# ==============================================================================
# Context Management Tests
# ==============================================================================


class TestContextManagement:
    """Tests for conversation context management."""

    def test_empty_context(self):
        """Test context starts empty."""
        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        assert len(pipeline.context.messages) == 0
        assert pipeline.context.current_transcription == ""

    def test_context_cleared_on_reset(self):
        """Test context is cleared on reset."""
        pipeline = Pipeline(
            config=PipelineConfig(),
            asr=MockASR(),
            llm=MockLLM(),
            tts=MockTTS(),
            vad=MockVAD(),
        )

        pipeline.context.messages.append({"role": "user", "content": "Hi"})
        pipeline.context.current_transcription = "Hi"

        pipeline.reset()

        assert len(pipeline.context.messages) == 0
        assert pipeline.context.current_transcription == ""
