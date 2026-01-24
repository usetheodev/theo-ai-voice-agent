"""Tests for provider system."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.providers.base import (
    ASRProvider,
    LLMProvider,
    TTSProvider,
    VADProvider,
    TranscriptionResult,
    LLMResponse,
    AudioChunk,
    VADResult,
)
from src.providers.asr import OpenAIWhisperASR, DeepgramASR
from src.providers.llm import OpenAILLM, OllamaLLM, GroqLLM
from src.providers.tts import OpenAITTS, ElevenLabsTTS
from src.providers.vad import SileroVAD, EnergyVAD
from src.providers.exceptions import (
    ProviderError,
    ProviderConnectionError,
    ProviderAuthError,
)


class TestDataTypes:
    """Tests for provider data types."""

    def test_transcription_result(self):
        result = TranscriptionResult(
            text="Hello world",
            is_final=True,
            confidence=0.95,
            language="en",
        )
        assert result.text == "Hello world"
        assert result.is_final is True
        assert result.confidence == 0.95

    def test_llm_response(self):
        response = LLMResponse(
            text="Hi there!",
            is_complete=True,
            finish_reason="stop",
        )
        assert response.text == "Hi there!"
        assert response.is_complete is True

    def test_audio_chunk(self):
        chunk = AudioChunk(
            data=b"\x00\x00\x01\x00",
            sample_rate=24000,
            channels=1,
            format="pcm16",
        )
        assert len(chunk.data) == 4
        assert chunk.sample_rate == 24000

    def test_vad_result(self):
        result = VADResult(
            is_speech=True,
            confidence=0.8,
        )
        assert result.is_speech is True
        assert result.confidence == 0.8


class TestOpenAIWhisperASR:
    """Tests for OpenAI Whisper ASR provider."""

    def test_init(self):
        provider = OpenAIWhisperASR(
            api_base="https://api.openai.com/v1",
            api_key="sk-test",
            model="whisper-1",
        )
        assert provider.name == "openai-whisper"
        assert provider.supports_streaming is False
        assert provider.api_base == "https://api.openai.com/v1"

    def test_init_local(self):
        provider = OpenAIWhisperASR(
            api_base="http://localhost:8000/v1",
        )
        assert provider.api_key is None

    @pytest.mark.asyncio
    async def test_transcribe_mock(self):
        provider = OpenAIWhisperASR(
            api_base="https://api.openai.com/v1",
            api_key="sk-test",
        )

        # Mock httpx
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"text": "Hello world"}
            mock_response.raise_for_status = MagicMock()

            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )

            result = await provider.transcribe(b"fake audio", language="en")

            assert result.text == "Hello world"
            assert result.is_final is True


class TestDeepgramASR:
    """Tests for Deepgram ASR provider."""

    def test_init(self):
        provider = DeepgramASR(
            api_key="test-key",
            model="nova-2",
        )
        assert provider.name == "deepgram"
        assert provider.supports_streaming is True
        assert provider.model == "nova-2"

    def test_build_query_params(self):
        provider = DeepgramASR(api_key="test", model="nova-2")
        params = provider._build_query_params(language="pt-BR", diarize=True)

        assert params["model"] == "nova-2"
        assert params["language"] == "pt-BR"
        assert params["diarize"] == "true"


class TestOpenAILLM:
    """Tests for OpenAI LLM provider."""

    def test_init(self):
        provider = OpenAILLM(
            api_key="sk-test",
            model="gpt-4o",
        )
        assert provider.name == "openai"
        assert provider.supports_streaming is True
        assert provider.model == "gpt-4o"

    def test_build_messages(self):
        provider = OpenAILLM(api_key="test")
        messages = provider._build_messages(
            [{"role": "user", "content": "Hello"}],
            system_prompt="You are helpful.",
        )

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"


class TestOllamaLLM:
    """Tests for Ollama LLM provider."""

    def test_init(self):
        provider = OllamaLLM(
            api_base="http://localhost:11434",
            model="llama3:8b",
        )
        assert provider.name == "ollama"
        assert provider.supports_streaming is True
        assert provider.model == "llama3:8b"

    def test_default_timeout(self):
        provider = OllamaLLM()
        assert provider.timeout == 120.0  # Longer for local models


class TestGroqLLM:
    """Tests for Groq LLM provider."""

    def test_init(self):
        provider = GroqLLM(
            api_key="gsk-test",
            model="llama3-70b-8192",
        )
        assert provider.name == "groq"
        assert provider.supports_streaming is True
        assert provider.model == "llama3-70b-8192"


class TestOpenAITTS:
    """Tests for OpenAI TTS provider."""

    def test_init(self):
        provider = OpenAITTS(
            api_key="sk-test",
            default_voice="nova",
        )
        assert provider.name == "openai-tts"
        assert provider.supports_streaming is True
        assert provider.default_voice == "nova"

    def test_available_voices(self):
        provider = OpenAITTS()
        voices = provider.available_voices
        assert "alloy" in voices
        assert "nova" in voices


class TestElevenLabsTTS:
    """Tests for ElevenLabs TTS provider."""

    def test_init(self):
        provider = ElevenLabsTTS(
            api_key="test-key",
            default_voice="rachel",
        )
        assert provider.name == "elevenlabs"
        assert provider.supports_streaming is True
        assert provider.default_voice == "rachel"


class TestEnergyVAD:
    """Tests for Energy-based VAD provider."""

    def test_init(self):
        provider = EnergyVAD(
            threshold=0.02,
            min_speech_duration_ms=200,
        )
        assert provider.name == "energy"
        assert provider.threshold == 0.02

    def test_calculate_rms(self):
        provider = EnergyVAD()

        # Silent audio (zeros)
        silent = bytes(100)
        assert provider._calculate_rms(silent) == 0.0

        # Loud audio (max values)
        # Create PCM16 with alternating max values
        import struct
        loud = struct.pack("<" + "h" * 50, *([32767, -32767] * 25))
        rms = provider._calculate_rms(loud)
        assert rms > 0.9  # Should be close to 1.0

    @pytest.mark.asyncio
    async def test_process_silent(self):
        provider = EnergyVAD(threshold=0.02)

        # Process silent audio
        silent = bytes(3200)  # 100ms at 16kHz
        result = await provider.process(silent, sample_rate=16000)

        assert result.is_speech is False

    @pytest.mark.asyncio
    async def test_reset(self):
        provider = EnergyVAD()

        # Process some audio
        await provider.process(bytes(3200))

        # Reset
        provider.reset()

        assert provider._speech_start is None
        assert provider._is_speaking is False
        assert len(provider._energy_history) == 0


class TestSileroVAD:
    """Tests for Silero VAD provider."""

    def test_init_local(self):
        provider = SileroVAD(threshold=0.5)
        assert provider.name == "silero"
        assert provider._local_mode is True

    def test_init_api(self):
        provider = SileroVAD(api_base="http://localhost:8000/vad")
        assert provider._local_mode is False

    def test_reset(self):
        provider = SileroVAD()
        provider._speech_start = 1.0
        provider._sample_count = 1000

        provider.reset()

        assert provider._speech_start is None
        assert provider._sample_count == 0


class TestProviderExceptions:
    """Tests for provider exceptions."""

    def test_provider_error(self):
        error = ProviderError("Test error", provider="test")
        assert "test" in str(error)
        assert "Test error" in str(error)

    def test_connection_error(self):
        error = ProviderConnectionError("Connection failed", provider="openai")
        assert error.provider == "openai"

    def test_auth_error(self):
        error = ProviderAuthError("Invalid key", provider="deepgram")
        assert error.provider == "deepgram"
