"""Tests for Provider Registry."""

from typing import AsyncIterator, Optional

import pytest

from voice_pipeline.interfaces import (
    ASRInterface,
    LLMChunk,
    LLMInterface,
    TTSInterface,
    AudioChunk,
    TranscriptionResult,
    VADEvent,
    VADInterface,
    SpeechState,
)
from voice_pipeline.providers import (
    ASRCapabilities,
    LLMCapabilities,
    ProviderInfo,
    ProviderRegistry,
    ProviderType,
    TTSCapabilities,
    VADCapabilities,
    get_registry,
    register_asr,
    register_llm,
    register_tts,
    register_vad,
    reset_registry,
)


# ==================== Mock Providers ====================


class MockASR(ASRInterface):
    """Mock ASR for testing."""

    def __init__(self, model: str = "base", language: str = "en"):
        self.model = model
        self.language = language

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        async for chunk in audio_stream:
            yield TranscriptionResult(
                text=f"Mock transcription ({self.model})",
                is_final=True,
            )


class MockLLM(LLMInterface):
    """Mock LLM for testing."""

    def __init__(self, model: str = "test", temperature: float = 0.7):
        self.model = model
        self.temperature = temperature

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[LLMChunk]:
        yield LLMChunk(text=f"Mock response ({self.model})", is_final=True)


class MockTTS(TTSInterface):
    """Mock TTS for testing."""

    def __init__(self, voice: str = "default", speed: float = 1.0):
        self.voice = voice
        self.speed = speed

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        async for text in text_stream:
            yield AudioChunk(
                data=text.encode("utf-8"),
                sample_rate=24000,
            )


class MockVAD(VADInterface):
    """Mock VAD for testing."""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    async def process(
        self,
        audio_chunk: bytes,
        sample_rate: int,
    ) -> VADEvent:
        return VADEvent(
            is_speech=True,
            confidence=0.9,
            state=SpeechState.SPEECH,
        )


# ==================== Fixtures ====================


@pytest.fixture
def fresh_registry():
    """Provide a fresh registry for each test."""
    reset_registry()
    registry = get_registry()
    yield registry
    reset_registry()


# ==================== Tests ====================


class TestProviderRegistry:
    """Tests for ProviderRegistry."""

    def test_singleton(self):
        """Test registry is singleton."""
        r1 = ProviderRegistry()
        r2 = ProviderRegistry()
        assert r1 is r2

    def test_get_registry(self):
        """Test get_registry returns singleton."""
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_reset_registry(self, fresh_registry):
        """Test reset_registry clears all providers."""
        registry = fresh_registry
        registry.register_asr("test", MockASR)

        reset_registry()
        registry = get_registry()

        assert len(registry.list_asr()) == 0


class TestRegistration:
    """Tests for provider registration."""

    def test_register_asr(self, fresh_registry):
        """Test ASR registration."""
        registry = fresh_registry
        caps = ASRCapabilities(streaming=True, languages=["en", "pt"])

        registry.register_asr(
            name="mock-asr",
            provider_class=MockASR,
            capabilities=caps,
            description="Test ASR",
            tags=["test", "mock"],
        )

        assert "mock-asr" in registry.list_asr()
        info = registry.get_info("mock-asr", ProviderType.ASR)
        assert info is not None
        assert info.capabilities.streaming is True
        assert "pt" in info.capabilities.languages

    def test_register_llm(self, fresh_registry):
        """Test LLM registration."""
        registry = fresh_registry
        caps = LLMCapabilities(function_calling=True, context_window=8192)

        registry.register_llm(
            name="mock-llm",
            provider_class=MockLLM,
            capabilities=caps,
        )

        assert "mock-llm" in registry.list_llm()
        caps = registry.get_capabilities("mock-llm", ProviderType.LLM)
        assert caps.function_calling is True
        assert caps.context_window == 8192

    def test_register_tts(self, fresh_registry):
        """Test TTS registration."""
        registry = fresh_registry
        caps = TTSCapabilities(
            voices=["voice-a", "voice-b"],
            ssml=True,
        )

        registry.register_tts(
            name="mock-tts",
            provider_class=MockTTS,
            capabilities=caps,
        )

        assert "mock-tts" in registry.list_tts()

    def test_register_vad(self, fresh_registry):
        """Test VAD registration."""
        registry = fresh_registry
        caps = VADCapabilities(frame_size_ms=20)

        registry.register_vad(
            name="mock-vad",
            provider_class=MockVAD,
            capabilities=caps,
        )

        assert "mock-vad" in registry.list_vad()

    def test_register_with_aliases(self, fresh_registry):
        """Test registration with aliases."""
        registry = fresh_registry

        registry.register_asr(
            name="whisper-local",
            provider_class=MockASR,
            aliases=["whisper", "local-asr"],
        )

        # Can get by main name
        assert registry.get_info("whisper-local", ProviderType.ASR) is not None

        # Can get by alias
        assert registry.get_info("whisper", ProviderType.ASR) is not None
        assert registry.get_info("local-asr", ProviderType.ASR) is not None


class TestProviderInstantiation:
    """Tests for getting provider instances."""

    def test_get_asr(self, fresh_registry):
        """Test getting ASR instance."""
        registry = fresh_registry
        registry.register_asr("mock-asr", MockASR)

        asr = registry.get_asr("mock-asr", model="large")

        assert isinstance(asr, MockASR)
        assert asr.model == "large"

    def test_get_llm(self, fresh_registry):
        """Test getting LLM instance."""
        registry = fresh_registry
        registry.register_llm("mock-llm", MockLLM)

        llm = registry.get_llm("mock-llm", model="gpt-4")

        assert isinstance(llm, MockLLM)
        assert llm.model == "gpt-4"

    def test_get_tts(self, fresh_registry):
        """Test getting TTS instance."""
        registry = fresh_registry
        registry.register_tts("mock-tts", MockTTS)

        tts = registry.get_tts("mock-tts", voice="amy")

        assert isinstance(tts, MockTTS)
        assert tts.voice == "amy"

    def test_get_vad(self, fresh_registry):
        """Test getting VAD instance."""
        registry = fresh_registry
        registry.register_vad("mock-vad", MockVAD)

        vad = registry.get_vad("mock-vad", threshold=0.7)

        assert isinstance(vad, MockVAD)
        assert vad.threshold == 0.7

    def test_get_nonexistent_raises(self, fresh_registry):
        """Test getting nonexistent provider raises KeyError."""
        registry = fresh_registry

        with pytest.raises(KeyError, match="not found"):
            registry.get_asr("does-not-exist")

    def test_get_with_default_config(self, fresh_registry):
        """Test getting provider with default config."""
        registry = fresh_registry
        registry.register_asr(
            name="mock-asr",
            provider_class=MockASR,
            default_config={"model": "medium"},
        )

        # Without override - uses default
        asr = registry.get_asr("mock-asr")
        assert asr.model == "medium"

        # With override - uses provided
        asr = registry.get_asr("mock-asr", model="large")
        assert asr.model == "large"


class TestListing:
    """Tests for listing providers."""

    def test_list_all_providers(self, fresh_registry):
        """Test listing all providers by type."""
        registry = fresh_registry
        registry.register_asr("asr1", MockASR)
        registry.register_asr("asr2", MockASR)
        registry.register_llm("llm1", MockLLM)
        registry.register_tts("tts1", MockTTS)

        all_providers = registry.list_providers()

        assert isinstance(all_providers, dict)
        assert set(all_providers["asr"]) == {"asr1", "asr2"}
        assert all_providers["llm"] == ["llm1"]
        assert all_providers["tts"] == ["tts1"]
        assert all_providers["vad"] == []

    def test_list_by_type_string(self, fresh_registry):
        """Test listing by type with string."""
        registry = fresh_registry
        registry.register_asr("asr1", MockASR)
        registry.register_asr("asr2", MockASR)

        asr_providers = registry.list_providers("asr")
        assert set(asr_providers) == {"asr1", "asr2"}


class TestCapabilitySearch:
    """Tests for finding providers by capability."""

    def test_find_by_capability(self, fresh_registry):
        """Test finding providers by capability."""
        registry = fresh_registry

        registry.register_asr(
            "streaming-asr",
            MockASR,
            capabilities=ASRCapabilities(streaming=True),
        )
        registry.register_asr(
            "batch-asr",
            MockASR,
            capabilities=ASRCapabilities(streaming=False),
        )

        streaming = registry.find_by_capability(
            ProviderType.ASR, streaming=True
        )
        assert "streaming-asr" in streaming
        assert "batch-asr" not in streaming

    def test_find_by_language(self, fresh_registry):
        """Test finding ASR by language support."""
        registry = fresh_registry

        registry.register_asr(
            "english-asr",
            MockASR,
            capabilities=ASRCapabilities(languages=["en"]),
        )
        registry.register_asr(
            "multilang-asr",
            MockASR,
            capabilities=ASRCapabilities(languages=["en", "pt", "es"]),
        )

        portuguese = registry.find_by_capability(
            ProviderType.ASR, languages="pt"
        )
        assert "multilang-asr" in portuguese
        assert "english-asr" not in portuguese

    def test_find_by_tag(self, fresh_registry):
        """Test finding providers by tag."""
        registry = fresh_registry

        registry.register_asr(
            "local-asr",
            MockASR,
            tags=["local", "fast"],
        )
        registry.register_asr(
            "cloud-asr",
            MockASR,
            tags=["cloud", "accurate"],
        )

        local = registry.find_by_tag(ProviderType.ASR, ["local"])
        assert "local-asr" in local
        assert "cloud-asr" not in local

    def test_find_by_multiple_tags(self, fresh_registry):
        """Test finding providers by multiple tags."""
        registry = fresh_registry

        registry.register_asr("both", MockASR, tags=["local", "fast"])
        registry.register_asr("local-only", MockASR, tags=["local"])
        registry.register_asr("fast-only", MockASR, tags=["fast"])

        # Match all
        both_tags = registry.find_by_tag(
            ProviderType.ASR, ["local", "fast"], match_all=True
        )
        assert "both" in both_tags
        assert "local-only" not in both_tags
        assert "fast-only" not in both_tags

        # Match any
        any_tag = registry.find_by_tag(
            ProviderType.ASR, ["local", "fast"], match_all=False
        )
        assert "both" in any_tag
        assert "local-only" in any_tag
        assert "fast-only" in any_tag


class TestDecorators:
    """Tests for registration decorators."""

    def test_register_asr_decorator(self, fresh_registry):
        """Test @register_asr decorator."""

        @register_asr("decorated-asr", capabilities=ASRCapabilities(streaming=True))
        class DecoratedASR(ASRInterface):
            async def transcribe_stream(self, audio_stream, language=None):
                async for chunk in audio_stream:
                    yield TranscriptionResult(text="Decorated", is_final=True)

        registry = fresh_registry
        assert "decorated-asr" in registry.list_asr()
        assert hasattr(DecoratedASR, "_voice_pipeline_name")
        assert DecoratedASR._voice_pipeline_name == "decorated-asr"

    def test_register_llm_decorator(self, fresh_registry):
        """Test @register_llm decorator."""

        @register_llm("decorated-llm")
        class DecoratedLLM(LLMInterface):
            async def generate_stream(self, messages, **kwargs):
                yield LLMChunk(text="Decorated", is_final=True)

        registry = fresh_registry
        assert "decorated-llm" in registry.list_llm()

    def test_register_tts_decorator(self, fresh_registry):
        """Test @register_tts decorator."""

        @register_tts("decorated-tts", capabilities=TTSCapabilities(ssml=True))
        class DecoratedTTS(TTSInterface):
            async def synthesize_stream(self, text_stream, **kwargs):
                async for text in text_stream:
                    yield AudioChunk(data=b"audio")

        registry = fresh_registry
        assert "decorated-tts" in registry.list_tts()

    def test_register_vad_decorator(self, fresh_registry):
        """Test @register_vad decorator."""

        @register_vad("decorated-vad")
        class DecoratedVAD(VADInterface):
            async def process(self, audio_chunk, sample_rate):
                return VADEvent(is_speech=True, state=SpeechState.SPEECH)

        registry = fresh_registry
        assert "decorated-vad" in registry.list_vad()


class TestProviderInfo:
    """Tests for ProviderInfo."""

    def test_provider_info_repr(self):
        """Test ProviderInfo string representation."""
        info = ProviderInfo(
            name="test-provider",
            provider_type=ProviderType.ASR,
            provider_class=MockASR,
            capabilities=ASRCapabilities(),
        )

        repr_str = repr(info)
        assert "test-provider" in repr_str
        assert "asr" in repr_str
        assert "MockASR" in repr_str


class TestCapabilities:
    """Tests for capability dataclasses."""

    def test_asr_capabilities_defaults(self):
        """Test ASRCapabilities defaults."""
        caps = ASRCapabilities()
        assert caps.streaming is True
        assert caps.languages == ["en"]
        assert caps.word_timestamps is False

    def test_llm_capabilities_defaults(self):
        """Test LLMCapabilities defaults."""
        caps = LLMCapabilities()
        assert caps.streaming is True
        assert caps.function_calling is False
        assert caps.context_window == 4096

    def test_tts_capabilities_defaults(self):
        """Test TTSCapabilities defaults."""
        caps = TTSCapabilities()
        assert caps.streaming is True
        assert caps.ssml is False
        assert caps.speed_control is True

    def test_vad_capabilities_defaults(self):
        """Test VADCapabilities defaults."""
        caps = VADCapabilities()
        assert caps.frame_size_ms == 30
        assert caps.confidence_scores is True
