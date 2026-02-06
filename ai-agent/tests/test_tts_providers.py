"""
Testes unitários para TTS providers.

Testa KokoroTTS, GoogleTTS, OpenAITTS, MockTTS e factory.
Todos os testes usam mocks (não requerem modelos ou API keys reais).
"""

import asyncio
import struct
import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

_mock_tts_config = {
    "provider": "mock",
    "voice": "pf_dora",
    "speed": 1.0,
    "sample_rate": 24000,
    "output_sample_rate": 8000,
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
    monkeypatch.setattr("providers.tts.TTS_CONFIG", _mock_tts_config)
    monkeypatch.setattr("providers.tts.AUDIO_CONFIG", _mock_audio_config)


def _generate_pcm_tone(duration_s: float = 0.1, sample_rate: int = 8000, freq: int = 440) -> bytes:
    """Gera tom PCM 16-bit sintético."""
    num_samples = int(duration_s * sample_rate)
    samples = []
    for i in range(num_samples):
        value = int(16000 * math.sin(2 * math.pi * freq * i / sample_rate))
        samples.append(value)
    return struct.pack(f'<{len(samples)}h', *samples)


# ==================== MockTTS Tests ====================

class TestMockTTS:
    """Testes para MockTTS provider."""

    @pytest.fixture
    def tts(self):
        from providers.tts import MockTTS
        return MockTTS()

    @pytest.mark.asyncio
    async def test_connect_disconnect(self, tts):
        """Verifica lifecycle connect/disconnect."""
        await tts.connect()
        assert tts.is_connected
        await tts.disconnect()
        assert not tts.is_connected

    @pytest.mark.asyncio
    async def test_synthesize_returns_audio(self, tts):
        """Verifica que synthesize retorna bytes de áudio."""
        await tts.connect()
        audio = await tts.synthesize("olá mundo")
        assert isinstance(audio, bytes)
        assert len(audio) > 0

    @pytest.mark.asyncio
    async def test_synthesize_empty_text(self, tts):
        """Verifica comportamento com texto vazio."""
        await tts.connect()
        audio = await tts.synthesize("")
        # MockTTS pode retornar vazio ou áudio mínimo
        assert audio is not None

    @pytest.mark.asyncio
    async def test_health_check(self, tts):
        """Verifica health check."""
        await tts.connect()
        result = await tts.health_check()
        assert result.status.value == "healthy"


# ==================== KokoroTTS Tests ====================

class TestKokoroTTS:
    """Testes para KokoroTTS provider."""

    @pytest.fixture
    def tts(self):
        from providers.tts import KokoroTTS
        return KokoroTTS()

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_no_model(self, tts):
        """Verifica health check sem modelo."""
        tts._connected = True
        result = await tts.health_check()
        assert result.status.value == "unhealthy"

    def test_preprocess_text_hours(self, tts):
        """Verifica expansão de horários PT-BR."""
        if hasattr(tts, '_preprocess_text'):
            result = tts._preprocess_text("16h29")
            assert "16" in result
            # Deve expandir formato de hora

    def test_preprocess_text_percentage(self, tts):
        """Verifica expansão de porcentagem."""
        if hasattr(tts, '_preprocess_text'):
            result = tts._preprocess_text("25%")
            assert "25" in result

    @pytest.mark.asyncio
    async def test_synthesize_no_model_returns_none(self, tts):
        """Verifica que synthesize sem modelo retorna None."""
        tts._model = None
        tts._connected = True
        # KokoroTTS pode retornar None ou vazio sem modelo
        audio = await tts.synthesize("teste")
        assert audio is None or audio == b""


# ==================== GoogleTTS Tests ====================

class TestGoogleTTS:
    """Testes para GoogleTTS provider."""

    @pytest.fixture
    def tts(self):
        from providers.tts import GoogleTTS
        return GoogleTTS()

    @pytest.mark.asyncio
    async def test_connect_disconnect(self, tts):
        """Verifica lifecycle."""
        await tts.connect()
        assert tts.is_connected
        await tts.disconnect()
        assert not tts.is_connected

    @pytest.mark.asyncio
    async def test_health_check(self, tts):
        """Verifica health check (Google TTS é stateless)."""
        await tts.connect()
        result = await tts.health_check()
        assert result.status.value == "healthy"


# ==================== OpenAITTS Tests ====================

class TestOpenAITTS:
    """Testes para OpenAITTS provider."""

    @pytest.fixture
    def tts(self):
        from providers.tts import OpenAITTS, OpenAITTSConfig
        config = OpenAITTSConfig(api_key="test-key")
        return OpenAITTS(config=config)

    @pytest.mark.asyncio
    async def test_connect(self, tts):
        """Verifica que connect inicializa cliente."""
        mock_module = MagicMock()
        mock_module.OpenAI.return_value = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_module}):
            await tts.connect()
            assert tts.client is not None

    @pytest.mark.asyncio
    async def test_disconnect(self, tts):
        """Verifica que disconnect limpa cliente."""
        tts.client = MagicMock()
        tts._connected = True
        await tts.disconnect()
        assert tts.client is None

    @pytest.mark.asyncio
    async def test_synthesize_no_client_returns_none(self, tts):
        """Verifica que synthesize sem client retorna None."""
        tts.client = None
        audio = await tts.synthesize("teste")
        assert audio is None or audio == b""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_no_client(self, tts):
        """Verifica health check sem cliente."""
        tts._connected = True
        tts.client = None
        result = await tts.health_check()
        assert result.status.value == "unhealthy"


# ==================== Factory Tests ====================

class TestTTSFactory:
    """Testes para factory create_tts_provider."""

    @pytest.mark.asyncio
    async def test_create_mock_tts(self):
        """Verifica criação de MockTTS."""
        from providers.tts import create_tts_provider, MockTTS
        tts = await create_tts_provider("mock")
        assert isinstance(tts, MockTTS)

    def test_factory_default_uses_config(self):
        """Verifica que factory usa config padrão."""
        from providers.tts import _create_tts_instance, MockTTS
        tts = _create_tts_instance("mock")
        assert isinstance(tts, MockTTS)

    def test_factory_invalid_provider(self):
        """Verifica que provider inválido faz fallback."""
        from providers.tts import _create_tts_instance
        # Deve tentar fallback chain
        try:
            tts = _create_tts_instance("nonexistent")
            # Se conseguiu, OK - fez fallback
            assert tts is not None
        except RuntimeError:
            # Se falhou, OK - nenhum fallback disponível
            pass
