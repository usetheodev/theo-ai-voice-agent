"""Tests for Voice Chains."""

from typing import AsyncIterator, Optional

import pytest

from voice_pipeline.chains import (
    ConversationChain,
    ConversationState,
    SimpleVoiceChain,
    StreamingVoiceChain,
    VoiceChain,
    VoiceChainBuilder,
    voice_chain,
)
from voice_pipeline.interfaces import (
    ASRInterface,
    AudioChunk,
    LLMChunk,
    LLMInterface,
    TranscriptionResult,
    TTSInterface,
)
from voice_pipeline.providers import reset_registry


# ==================== Mock Providers ====================


class MockASR(ASRInterface):
    """Mock ASR that returns fixed transcription."""

    def __init__(self, transcription: str = "Hello world"):
        self._transcription = transcription

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        async for _ in audio_stream:
            pass
        yield TranscriptionResult(text=self._transcription, is_final=True)


class MockLLM(LLMInterface):
    """Mock LLM that returns fixed response."""

    def __init__(self, response: str = "Hello! How can I help you?"):
        self._response = response

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        # Simulate streaming by yielding words
        words = self._response.split()
        for i, word in enumerate(words):
            is_final = i == len(words) - 1
            text = word if i == 0 else " " + word
            yield LLMChunk(text=text, is_final=is_final)


class MockTTS(TTSInterface):
    """Mock TTS that returns encoded text."""

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        async for text in text_stream:
            # Simulate audio by encoding text
            yield AudioChunk(
                data=text.encode("utf-8"),
                sample_rate=24000,
                channels=1,
                format="pcm16",
            )


# ==================== Fixtures ====================


@pytest.fixture
def mock_asr():
    return MockASR("Hello world")


@pytest.fixture
def mock_llm():
    return MockLLM("Hello! How can I help you?")


@pytest.fixture
def mock_tts():
    return MockTTS()


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry before each test."""
    reset_registry()
    yield
    reset_registry()


# ==================== Tests ====================


class TestVoiceChain:
    """Tests for VoiceChain."""

    @pytest.mark.asyncio
    async def test_basic_chain(self, mock_asr, mock_llm, mock_tts):
        """Test basic chain execution."""
        chain = VoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        result = await chain.ainvoke(b"audio data")

        assert isinstance(result, AudioChunk)
        assert len(result.data) > 0

    @pytest.mark.asyncio
    async def test_streaming(self, mock_asr, mock_llm, mock_tts):
        """Test streaming chain execution."""
        chain = VoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        chunks = [c async for c in chain.astream(b"audio")]
        assert len(chunks) > 0
        assert all(isinstance(c, AudioChunk) for c in chunks)

    @pytest.mark.asyncio
    async def test_conversation_history(self, mock_asr, mock_llm, mock_tts):
        """Test conversation history is maintained."""
        chain = VoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        await chain.ainvoke(b"audio1")
        assert len(chain.messages) == 2  # user + assistant

        await chain.ainvoke(b"audio2")
        assert len(chain.messages) == 4  # 2 turns

    @pytest.mark.asyncio
    async def test_reset(self, mock_asr, mock_llm, mock_tts):
        """Test conversation reset."""
        chain = VoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        await chain.ainvoke(b"audio")
        assert len(chain.messages) > 0

        chain.reset()
        assert len(chain.messages) == 0

    @pytest.mark.asyncio
    async def test_with_system_prompt(self, mock_asr, mock_llm, mock_tts):
        """Test chain with system prompt."""
        chain = VoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            system_prompt="You are a helpful assistant.",
        )

        await chain.ainvoke(b"audio")
        assert chain.system_prompt == "You are a helpful assistant."

    @pytest.mark.asyncio
    async def test_empty_transcription(self, mock_llm, mock_tts):
        """Test chain handles empty transcription."""
        empty_asr = MockASR(transcription="")

        chain = VoiceChain(
            asr=empty_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        chunks = [c async for c in chain.astream(b"audio")]
        assert len(chunks) == 0


class TestSimpleVoiceChain:
    """Tests for SimpleVoiceChain."""

    @pytest.mark.asyncio
    async def test_text_to_audio(self, mock_llm, mock_tts):
        """Test text-to-audio conversion."""
        chain = SimpleVoiceChain(
            llm=mock_llm,
            tts=mock_tts,
        )

        result = await chain.ainvoke("Hello!")

        assert isinstance(result, AudioChunk)
        assert len(result.data) > 0

    @pytest.mark.asyncio
    async def test_streaming(self, mock_llm, mock_tts):
        """Test streaming text-to-audio."""
        chain = SimpleVoiceChain(
            llm=mock_llm,
            tts=mock_tts,
        )

        chunks = [c async for c in chain.astream("Hello!")]
        assert len(chunks) > 0


class TestVoiceChainBuilder:
    """Tests for VoiceChainBuilder."""

    def test_builder_with_instances(self, mock_asr, mock_llm, mock_tts):
        """Test builder with provider instances."""
        chain = (
            voice_chain()
            .with_asr_instance(mock_asr)
            .with_llm_instance(mock_llm)
            .with_tts_instance(mock_tts)
            .build()
        )

        assert isinstance(chain, VoiceChain)
        assert chain.asr is mock_asr
        assert chain.llm is mock_llm
        assert chain.tts is mock_tts

    def test_builder_configuration(self, mock_asr, mock_llm, mock_tts):
        """Test builder configuration methods."""
        chain = (
            voice_chain()
            .with_asr_instance(mock_asr)
            .with_llm_instance(mock_llm)
            .with_tts_instance(mock_tts)
            .with_system_prompt("You are helpful.")
            .with_language("pt-BR")
            .with_voice("faber")
            .with_temperature(0.5)
            .with_max_tokens(100)
            .build()
        )

        assert chain.system_prompt == "You are helpful."
        assert chain.language == "pt-BR"
        assert chain.tts_voice == "faber"
        assert chain.llm_temperature == 0.5
        assert chain.llm_max_tokens == 100

    def test_builder_missing_asr_raises(self, mock_llm, mock_tts):
        """Test builder raises without ASR."""
        builder = (
            voice_chain()
            .with_llm_instance(mock_llm)
            .with_tts_instance(mock_tts)
        )

        with pytest.raises(ValueError, match="ASR"):
            builder.build()

    def test_builder_missing_llm_raises(self, mock_asr, mock_tts):
        """Test builder raises without LLM."""
        builder = (
            voice_chain()
            .with_asr_instance(mock_asr)
            .with_tts_instance(mock_tts)
        )

        with pytest.raises(ValueError, match="LLM"):
            builder.build()

    def test_builder_missing_tts_raises(self, mock_asr, mock_llm):
        """Test builder raises without TTS."""
        builder = (
            voice_chain()
            .with_asr_instance(mock_asr)
            .with_llm_instance(mock_llm)
        )

        with pytest.raises(ValueError, match="TTS"):
            builder.build()

    def test_voice_chain_builder_static(self, mock_asr, mock_llm, mock_tts):
        """Test VoiceChain.builder() static method."""
        chain = (
            VoiceChain.builder()
            .with_asr_instance(mock_asr)
            .with_llm_instance(mock_llm)
            .with_tts_instance(mock_tts)
            .build()
        )

        assert isinstance(chain, VoiceChain)


class TestConversationChain:
    """Tests for ConversationChain."""

    @pytest.mark.asyncio
    async def test_basic_conversation(self, mock_asr, mock_llm, mock_tts):
        """Test basic conversation."""
        chain = ConversationChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        chunks = [c async for c in chain.astream(b"audio")]
        assert len(chunks) > 0
        assert chain.turn_count == 1

    @pytest.mark.asyncio
    async def test_state_transitions(self, mock_asr, mock_llm, mock_tts):
        """Test state transitions during conversation."""
        states: list[ConversationState] = []

        chain = ConversationChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            on_state_change=lambda s: states.append(s),
        )

        await chain.ainvoke(b"audio")

        # Should have transitioned through states
        assert ConversationState.LISTENING in states
        assert ConversationState.PROCESSING in states
        assert ConversationState.SPEAKING in states
        assert chain.state == ConversationState.IDLE

    @pytest.mark.asyncio
    async def test_max_history(self, mock_asr, mock_llm, mock_tts):
        """Test conversation history limit."""
        chain = ConversationChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            max_history=4,
        )

        # Do multiple turns
        for _ in range(3):
            await chain.ainvoke(b"audio")

        # Should be limited to 4 messages
        assert len(chain.messages) <= 4

    @pytest.mark.asyncio
    async def test_reset(self, mock_asr, mock_llm, mock_tts):
        """Test conversation reset."""
        chain = ConversationChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        await chain.ainvoke(b"audio")
        assert chain.turn_count == 1
        assert len(chain.messages) > 0

        chain.reset()

        assert chain.turn_count == 0
        assert len(chain.messages) == 0
        assert chain.state == ConversationState.IDLE

    @pytest.mark.asyncio
    async def test_callbacks(self, mock_asr, mock_llm, mock_tts):
        """Test turn callbacks."""
        turn_starts = []
        turn_ends = []

        chain = ConversationChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            on_turn_start=lambda: turn_starts.append(True),
            on_turn_end=lambda: turn_ends.append(True),
        )

        await chain.ainvoke(b"audio")

        assert len(turn_starts) == 1
        assert len(turn_ends) == 1


class TestStreamingVoiceChain:
    """Tests for StreamingVoiceChain."""

    @pytest.mark.asyncio
    async def test_streaming_chain(self, mock_asr, mock_llm, mock_tts):
        """Test streaming voice chain."""
        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        chunks = [c async for c in chain.astream(b"audio")]
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_non_streaming_invoke(self, mock_asr, mock_llm, mock_tts):
        """Test non-streaming invoke."""
        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        result = await chain.ainvoke(b"audio")
        assert isinstance(result, AudioChunk)

    @pytest.mark.asyncio
    async def test_sentence_config(self, mock_asr, mock_llm, mock_tts):
        """Test sentence streamer configuration."""
        chain = StreamingVoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
            min_sentence_chars=10,
            max_sentence_chars=100,
        )

        assert chain.streamer_config.min_chars == 10
        assert chain.streamer_config.max_chars == 100


class TestChainRepr:
    """Tests for chain string representations."""

    def test_voice_chain_repr(self, mock_asr, mock_llm, mock_tts):
        """Test VoiceChain repr."""
        chain = VoiceChain(
            asr=mock_asr,
            llm=mock_llm,
            tts=mock_tts,
        )

        repr_str = repr(chain)
        assert "VoiceChain" in repr_str
        assert "MockASR" in repr_str
        assert "MockLLM" in repr_str
        assert "MockTTS" in repr_str
