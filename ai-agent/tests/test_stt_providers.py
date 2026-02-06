"""
Testes unitários para STT providers.

Testa FasterWhisperSTT, OpenAIWhisperSTT e factory.
Todos os testes usam mocks (não requerem modelos ou API keys reais).
"""

import asyncio
import io
import struct
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from dataclasses import dataclass

# Mock config antes de importar providers
import sys
import os

# Adiciona path do ai-agent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Mock de config para evitar dependência de .env
_mock_stt_config = {
    "provider": "faster-whisper",
    "model": "tiny",
    "device": "cpu",
    "compute_type": "int8",
    "language": "pt",
    "beam_size": 1,
    "vad_filter": False,
    "word_timestamps": False,
    "cpu_threads": 0,
    "num_workers": 1,
    "executor_workers": 2,
    "fallback_provider": "",
}

_mock_audio_config = {
    "sample_rate": 8000,
    "channels": 1,
    "sample_width": 2,
    "frame_duration_ms": 20,
    "vad_aggressiveness": 2,
    "silence_threshold_ms": 500,
    "min_speech_ms": 250,
    "energy_threshold": 500,
    "max_buffer_seconds": 60,
    "chunk_size_bytes": 1600,
    "max_pending_audio_ms": 30000,
}


@pytest.fixture(autouse=True)
def mock_configs(monkeypatch):
    """Mock configs para todos os testes."""
    monkeypatch.setattr("providers.stt.STT_CONFIG", _mock_stt_config)
    monkeypatch.setattr("providers.stt.AUDIO_CONFIG", _mock_audio_config)


def _generate_pcm_audio(duration_s: float = 0.5, sample_rate: int = 8000) -> bytes:
    """Gera áudio PCM 16-bit sintético (sine wave 440Hz)."""
    import math
    num_samples = int(duration_s * sample_rate)
    samples = []
    for i in range(num_samples):
        value = int(16000 * math.sin(2 * math.pi * 440 * i / sample_rate))
        samples.append(value)
    return struct.pack(f'<{len(samples)}h', *samples)


# ==================== FasterWhisperSTT Tests ====================

class TestFasterWhisperSTT:
    """Testes para FasterWhisperSTT provider."""

    @pytest.fixture
    def mock_whisper_model(self):
        """Mock do modelo faster-whisper."""
        model = MagicMock()
        # Mock transcribe retorna segments e info
        segment = MagicMock()
        segment.text = " olá, preciso de ajuda"
        info = MagicMock()
        info.language = "pt"
        info.language_probability = 0.95
        model.transcribe.return_value = ([segment], info)
        return model

    @pytest.fixture
    def stt_provider(self):
        """Cria instância FasterWhisperSTT sem conectar."""
        from providers.stt import FasterWhisperSTT
        return FasterWhisperSTT()

    @pytest.mark.asyncio
    async def test_connect_loads_model(self, stt_provider, mock_whisper_model):
        """Verifica que connect() carrega o modelo."""
        with patch("providers.stt.FasterWhisperSTT._load_model", return_value=mock_whisper_model):
            await stt_provider.connect()
            assert stt_provider._model is not None
            assert stt_provider.is_connected

    @pytest.mark.asyncio
    async def test_disconnect_releases_model(self, stt_provider, mock_whisper_model):
        """Verifica que disconnect() libera recursos."""
        with patch("providers.stt.FasterWhisperSTT._load_model", return_value=mock_whisper_model):
            await stt_provider.connect()
            await stt_provider.disconnect()
            assert stt_provider._model is None
            assert not stt_provider.is_connected

    @pytest.mark.asyncio
    async def test_transcribe_returns_text(self, stt_provider, mock_whisper_model):
        """Verifica que transcribe() retorna texto do áudio."""
        with patch("providers.stt.FasterWhisperSTT._load_model", return_value=mock_whisper_model):
            await stt_provider.connect()

            # Mock numpy import
            import numpy as np
            audio_data = _generate_pcm_audio(0.5)

            # Mock executor para rodar sync
            stt_provider._executor = MagicMock()

            async def mock_run_in_executor(executor, fn):
                return fn()

            with patch.object(asyncio.get_event_loop(), 'run_in_executor', side_effect=mock_run_in_executor):
                text = await stt_provider.transcribe(audio_data)
                assert "olá" in text

    @pytest.mark.asyncio
    async def test_transcribe_empty_model_returns_empty(self, stt_provider):
        """Verifica que transcribe() com modelo não carregado retorna vazio."""
        text = await stt_provider.transcribe(b"\x00" * 100)
        assert text == ""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, stt_provider, mock_whisper_model):
        """Verifica health check com modelo carregado."""
        stt_provider._model = mock_whisper_model
        stt_provider._connected = True
        stt_provider._executor = MagicMock()

        async def mock_run_in_executor(executor, fn):
            return fn()

        with patch.object(asyncio.get_event_loop(), 'run_in_executor', side_effect=mock_run_in_executor):
            result = await stt_provider.health_check()
            assert result.status.value == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_no_model(self, stt_provider):
        """Verifica health check sem modelo carregado."""
        stt_provider._model = None
        stt_provider._connected = True
        result = await stt_provider.health_check()
        assert result.status.value == "unhealthy"

    @pytest.mark.asyncio
    async def test_warmup_requires_model(self, stt_provider):
        """Verifica que warmup falha sem modelo."""
        stt_provider._model = None
        with pytest.raises(RuntimeError):
            await stt_provider.warmup()

    def test_sample_rate_from_config(self, stt_provider):
        """Verifica que sample_rate vem da config."""
        assert stt_provider.sample_rate == 8000

    @pytest.mark.asyncio
    async def test_device_fallback_reconnect(self, stt_provider, mock_whisper_model):
        """Verifica que reconnect_with_device muda device."""
        with patch("providers.stt.FasterWhisperSTT._load_model", return_value=mock_whisper_model):
            await stt_provider.connect()
            # Simula fallback GPU -> CPU
            await stt_provider.reconnect_with_device("cpu")
            assert stt_provider._stt_config.device == "cpu"
            assert stt_provider._stt_config.compute_type == "int8"

    @pytest.mark.asyncio
    async def test_transcribe_error_records_failure(self, stt_provider, mock_whisper_model):
        """Verifica que erro na transcrição é registrado nas métricas."""
        stt_provider._model = mock_whisper_model
        stt_provider._connected = True
        stt_provider._executor = MagicMock()

        mock_whisper_model.transcribe.side_effect = RuntimeError("model error")

        async def mock_run_in_executor(executor, fn):
            return fn()

        with patch.object(asyncio.get_event_loop(), 'run_in_executor', side_effect=mock_run_in_executor):
            text = await stt_provider.transcribe(_generate_pcm_audio())
            assert text == ""
            assert stt_provider.metrics.failed_requests > 0


# ==================== OpenAIWhisperSTT Tests ====================

class TestOpenAIWhisperSTT:
    """Testes para OpenAIWhisperSTT provider."""

    @pytest.fixture
    def stt_provider(self):
        """Cria instância OpenAIWhisperSTT."""
        from providers.stt import OpenAIWhisperSTT, OpenAIWhisperConfig
        config = OpenAIWhisperConfig(api_key="test-key", language="pt")
        return OpenAIWhisperSTT(config=config)

    @pytest.mark.asyncio
    async def test_connect_initializes_client(self, stt_provider):
        """Verifica que connect() inicializa cliente OpenAI."""
        mock_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_openai}):
            mock_openai.OpenAI.return_value = MagicMock()
            await stt_provider.connect()
            assert stt_provider.client is not None
            assert stt_provider.is_connected

    @pytest.mark.asyncio
    async def test_disconnect_clears_client(self, stt_provider):
        """Verifica que disconnect() limpa cliente."""
        stt_provider.client = MagicMock()
        stt_provider._connected = True
        await stt_provider.disconnect()
        assert stt_provider.client is None

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_no_client(self, stt_provider):
        """Verifica health check sem cliente."""
        stt_provider._connected = True
        result = await stt_provider.health_check()
        assert result.status.value == "unhealthy"

    @pytest.mark.asyncio
    async def test_transcribe_no_client_returns_empty(self, stt_provider):
        """Verifica que transcribe sem cliente retorna vazio."""
        text = await stt_provider.transcribe(b"\x00" * 100)
        assert text == ""


# ==================== Factory Tests ====================

class TestSTTFactory:
    """Testes para factory create_stt_provider."""

    def test_create_stt_instance_faster_whisper(self):
        """Verifica que factory cria FasterWhisperSTT."""
        from providers.stt import _create_stt_instance, FasterWhisperSTT
        stt = _create_stt_instance("faster-whisper")
        assert isinstance(stt, FasterWhisperSTT)

    def test_create_stt_instance_openai(self):
        """Verifica que factory cria OpenAIWhisperSTT."""
        from providers.stt import _create_stt_instance, OpenAIWhisperSTT
        stt = _create_stt_instance("openai")
        assert isinstance(stt, OpenAIWhisperSTT)

    def test_create_stt_instance_invalid_fallsback(self):
        """Verifica que provider inválido faz fallback."""
        from providers.stt import _create_stt_instance, FasterWhisperSTT
        stt = _create_stt_instance("nonexistent")
        assert isinstance(stt, FasterWhisperSTT)
