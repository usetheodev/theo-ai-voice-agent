"""Tests for Kokoro TTS provider."""

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from voice_pipeline.interfaces.tts import AudioChunk
from voice_pipeline.providers.base import (
    HealthCheckResult,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.tts import KokoroTTSProvider, KokoroTTSConfig


class TestKokoroTTSConfig:
    """Tests for KokoroTTSConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = KokoroTTSConfig()

        assert config.lang_code == "a"
        assert config.voice == "af_bella"
        assert config.speed == 1.0
        assert config.sample_rate == 24000
        assert config.device is None
        assert config.split_pattern == r"\n+"
        assert config.repo_id is None

    def test_custom_values(self):
        """Test custom configuration values."""
        config = KokoroTTSConfig(
            lang_code="p",
            voice="pf_dora",
            speed=1.2,
            sample_rate=22050,
            device="cuda",
            split_pattern=r"\. ",
            repo_id="hexgrad/Kokoro-82M",
        )

        assert config.lang_code == "p"
        assert config.voice == "pf_dora"
        assert config.speed == 1.2
        assert config.sample_rate == 22050
        assert config.device == "cuda"
        assert config.split_pattern == r"\. "
        assert config.repo_id == "hexgrad/Kokoro-82M"


class TestKokoroTTSProviderInit:
    """Tests for KokoroTTSProvider initialization."""

    def test_default_initialization(self):
        """Test provider with default config."""
        provider = KokoroTTSProvider()

        assert provider.provider_name == "kokoro-tts"
        assert provider.name == "KokoroTTS"
        assert provider._tts_config.lang_code == "a"
        assert provider._tts_config.voice == "af_bella"
        assert provider.is_connected is False

    def test_initialization_with_config(self):
        """Test provider with custom config."""
        config = KokoroTTSConfig(
            lang_code="b",
            voice="bf_emma",
            speed=0.9,
        )
        provider = KokoroTTSProvider(config=config)

        assert provider._tts_config.lang_code == "b"
        assert provider._tts_config.voice == "bf_emma"
        assert provider._tts_config.speed == 0.9

    def test_initialization_with_shortcuts(self):
        """Test provider with shortcut parameters."""
        provider = KokoroTTSProvider(
            lang_code="p",
            voice="pm_alex",
            speed=1.5,
            device="cpu",
        )

        assert provider._tts_config.lang_code == "p"
        assert provider._tts_config.voice == "pm_alex"
        assert provider._tts_config.speed == 1.5
        assert provider._tts_config.device == "cpu"

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = KokoroTTSConfig(lang_code="a", voice="af_bella")
        provider = KokoroTTSProvider(
            config=config,
            lang_code="b",
            voice="bf_emma",
        )

        assert provider._tts_config.lang_code == "b"
        assert provider._tts_config.voice == "bf_emma"

    def test_sample_rate_property(self):
        """Test sample_rate property."""
        provider = KokoroTTSProvider()
        assert provider.sample_rate == 24000

        config = KokoroTTSConfig(sample_rate=22050)
        provider = KokoroTTSProvider(config=config)
        assert provider.sample_rate == 22050

    def test_channels_property(self):
        """Test channels property (always mono)."""
        provider = KokoroTTSProvider()
        assert provider.channels == 1

    def test_repr(self):
        """Test string representation."""
        provider = KokoroTTSProvider(lang_code="a", voice="af_bella")
        repr_str = repr(provider)

        assert "KokoroTTSProvider" in repr_str
        assert "af_bella" in repr_str
        assert "connected=False" in repr_str


class TestKokoroTTSProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_creates_pipeline(self):
        """Test that connect creates Kokoro pipeline."""
        provider = KokoroTTSProvider()

        with patch("kokoro.KPipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline_class.return_value = mock_pipeline

            await provider.connect()

            mock_pipeline_class.assert_called_once()
            assert provider.is_connected is True
            assert provider._pipeline is mock_pipeline

    @pytest.mark.asyncio
    async def test_connect_with_device(self):
        """Test connect with specific device."""
        provider = KokoroTTSProvider(device="cuda")

        with patch("kokoro.KPipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline_class.return_value = mock_pipeline

            await provider.connect()

            call_kwargs = mock_pipeline_class.call_args[1]
            assert call_kwargs["device"] == "cuda"

    @pytest.mark.asyncio
    async def test_connect_raises_without_kokoro(self):
        """Test that connect raises ImportError without kokoro package."""
        provider = KokoroTTSProvider()

        with patch.dict("sys.modules", {"kokoro": None}):
            with patch(
                "builtins.__import__",
                side_effect=ImportError("No module named 'kokoro'"),
            ):
                with pytest.raises(ImportError, match="kokoro is required"):
                    await provider.connect()

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        """Test that disconnect cleans up resources."""
        provider = KokoroTTSProvider()

        mock_pipeline = MagicMock()
        mock_executor = MagicMock()
        provider._pipeline = mock_pipeline
        provider._executor = mock_executor
        provider._connected = True

        await provider.disconnect()

        mock_executor.shutdown.assert_called_once_with(wait=False)
        assert provider._pipeline is None
        assert provider._executor is None
        assert provider.is_connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        provider = KokoroTTSProvider()

        with patch("kokoro.KPipeline") as mock_pipeline_class:
            mock_pipeline = MagicMock()
            mock_pipeline_class.return_value = mock_pipeline

            async with provider as p:
                assert p.is_connected is True

            assert provider.is_connected is False


class TestKokoroTTSProviderHealthCheck:
    """Tests for health check functionality."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = KokoroTTSProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_synthesis_works(self):
        """Test health check returns healthy when synthesis works."""
        provider = KokoroTTSProvider()

        # Mock pipeline
        mock_result = MagicMock()
        mock_result.audio = np.zeros(1000, dtype=np.float32)

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [mock_result]

        provider._pipeline = mock_pipeline
        provider._executor = MagicMock()

        # Mock run_in_executor to run synchronously
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(return_value=True)

            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY
            assert "af_bella" in result.message

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on synthesis error."""
        provider = KokoroTTSProvider()

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                side_effect=Exception("Synthesis failed")
            )

            result = await provider.health_check()

            assert result.status == ProviderHealth.UNHEALTHY
            assert "error" in result.message.lower()


class TestKokoroTTSProviderListVoices:
    """Tests for list_voices functionality."""

    def test_list_voices_default_language(self):
        """Test list_voices returns voices for default language."""
        provider = KokoroTTSProvider(lang_code="a")

        voices = provider.list_voices()

        assert "af_bella" in voices
        assert "am_adam" in voices

    def test_list_voices_specific_language(self):
        """Test list_voices returns voices for specific language."""
        provider = KokoroTTSProvider(lang_code="a")

        voices = provider.list_voices("p")

        assert "pf_dora" in voices
        assert "pm_alex" in voices

    def test_list_voices_unknown_language(self):
        """Test list_voices returns empty list for unknown language."""
        provider = KokoroTTSProvider()

        voices = provider.list_voices("x")

        assert voices == []


class TestKokoroTTSProviderSynthesizeStream:
    """Tests for streaming synthesis."""

    @pytest.mark.asyncio
    async def test_synthesize_stream_raises_without_pipeline(self):
        """Test synthesize_stream raises error when not connected."""
        provider = KokoroTTSProvider()

        async def text_gen():
            yield "Hello"

        with pytest.raises(RuntimeError, match="not connected"):
            async for _ in provider.synthesize_stream(text_gen()):
                pass

    @pytest.mark.asyncio
    async def test_synthesize_stream_basic(self):
        """Test basic streaming synthesis."""
        provider = KokoroTTSProvider()

        # Mock pipeline result
        mock_result = MagicMock()
        mock_result.audio = np.random.randn(24000).astype(np.float32)  # 1 second

        mock_pipeline = MagicMock()
        mock_pipeline.return_value = [mock_result]

        provider._pipeline = mock_pipeline
        provider._executor = MagicMock()

        async def text_gen():
            yield "Hello, world!"

        # Mock run_in_executor
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=[mock_result]
            )

            chunks = []
            async for chunk in provider.synthesize_stream(text_gen()):
                chunks.append(chunk)

            assert len(chunks) == 1
            assert isinstance(chunks[0], AudioChunk)
            assert chunks[0].sample_rate == 24000
            assert chunks[0].channels == 1
            assert chunks[0].format == "pcm16"
            assert len(chunks[0].data) > 0

    @pytest.mark.asyncio
    async def test_synthesize_stream_skips_empty_text(self):
        """Test that empty text is skipped in stream."""
        provider = KokoroTTSProvider()

        mock_result = MagicMock()
        mock_result.audio = np.random.randn(1000).astype(np.float32)

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        async def text_gen():
            yield ""
            yield "   "
            yield "Hello"

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=[mock_result]
            )

            chunks = []
            async for chunk in provider.synthesize_stream(text_gen()):
                chunks.append(chunk)

            # Only non-empty text should produce chunks
            assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_synthesize_stream_with_voice(self):
        """Test streaming with custom voice."""
        provider = KokoroTTSProvider()

        mock_result = MagicMock()
        mock_result.audio = np.random.randn(1000).astype(np.float32)

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        async def text_gen():
            yield "Hello"

        with patch("asyncio.get_event_loop") as mock_loop:
            async def run_executor(executor, func):
                return func()

            mock_loop.return_value.run_in_executor = run_executor

            # Track what voice is used
            provider._pipeline.return_value = [mock_result]

            chunks = []
            async for chunk in provider.synthesize_stream(
                text_gen(),
                voice="am_adam",
            ):
                chunks.append(chunk)

            # Check that custom voice was passed
            call_kwargs = provider._pipeline.call_args[1]
            assert call_kwargs["voice"] == "am_adam"

    @pytest.mark.asyncio
    async def test_synthesize_stream_records_metrics(self):
        """Test that streaming records metrics."""
        provider = KokoroTTSProvider()

        mock_result = MagicMock()
        mock_result.audio = np.random.randn(1000).astype(np.float32)

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        async def text_gen():
            yield "Hello"

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=[mock_result]
            )

            async for _ in provider.synthesize_stream(text_gen()):
                pass

            assert provider.metrics.successful_requests == 1
            assert provider.metrics.total_requests == 1


class TestKokoroTTSProviderSynthesize:
    """Tests for non-streaming synthesis."""

    @pytest.mark.asyncio
    async def test_synthesize_raises_without_pipeline(self):
        """Test synthesize raises error when not connected."""
        provider = KokoroTTSProvider()

        with pytest.raises(RuntimeError, match="not connected"):
            await provider.synthesize("Hello")

    @pytest.mark.asyncio
    async def test_synthesize_basic(self):
        """Test basic non-streaming synthesis."""
        provider = KokoroTTSProvider()

        # Mock pipeline result
        mock_result = MagicMock()
        mock_result.audio = np.random.randn(24000).astype(np.float32)

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        # Expected PCM16 bytes
        expected_audio = (mock_result.audio * 32767).astype(np.int16).tobytes()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=expected_audio
            )

            result = await provider.synthesize("Hello, world!")

            assert isinstance(result, bytes)
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_synthesize_with_options(self):
        """Test synthesis with custom options."""
        provider = KokoroTTSProvider()

        mock_result = MagicMock()
        mock_result.audio = np.random.randn(1000).astype(np.float32)

        provider._pipeline = MagicMock()
        provider._pipeline.return_value = [mock_result]
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            async def run_executor(executor, func):
                return func()

            mock_loop.return_value.run_in_executor = run_executor

            await provider.synthesize(
                "Hello",
                voice="bf_emma",
                speed=1.5,
            )

            call_kwargs = provider._pipeline.call_args[1]
            assert call_kwargs["voice"] == "bf_emma"
            assert call_kwargs["speed"] == 1.5


class TestKokoroTTSProviderErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_retryable_error_cuda_oom(self):
        """Test CUDA OOM error is retryable."""
        provider = KokoroTTSProvider()

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                side_effect=Exception("CUDA out of memory")
            )

            with pytest.raises(RetryableError):
                await provider.synthesize("Hello")

    @pytest.mark.asyncio
    async def test_non_retryable_error_invalid_voice(self):
        """Test invalid voice error is non-retryable."""
        provider = KokoroTTSProvider()

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                side_effect=Exception("Invalid voice: xyz_unknown")
            )

            with pytest.raises(NonRetryableError):
                await provider.synthesize("Hello")

    @pytest.mark.asyncio
    async def test_error_records_metrics(self):
        """Test that errors are recorded in metrics."""
        provider = KokoroTTSProvider()

        provider._pipeline = MagicMock()
        provider._executor = MagicMock()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                side_effect=Exception("Some error")
            )

            try:
                await provider.synthesize("Hello")
            except Exception:
                pass

            assert provider.metrics.failed_requests == 1
            assert provider.metrics.last_error is not None


class TestKokoroTTSProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_string(self):
        """Test ainvoke with string input."""
        provider = KokoroTTSProvider()

        mock_result = MagicMock()
        mock_result.audio = np.random.randn(1000).astype(np.float32)

        provider._pipeline = MagicMock()
        provider._pipeline.return_value = [mock_result]
        provider._executor = MagicMock()

        expected_audio = (mock_result.audio * 32767).astype(np.int16).tobytes()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=expected_audio
            )

            result = await provider.ainvoke("Hello")

            assert isinstance(result, AudioChunk)
            assert result.sample_rate == 24000
            assert result.channels == 1

    @pytest.mark.asyncio
    async def test_ainvoke_with_llm_chunk(self):
        """Test ainvoke with LLMChunk-like object."""
        provider = KokoroTTSProvider()

        mock_result = MagicMock()
        mock_result.audio = np.random.randn(1000).astype(np.float32)

        provider._pipeline = MagicMock()
        provider._pipeline.return_value = [mock_result]
        provider._executor = MagicMock()

        expected_audio = (mock_result.audio * 32767).astype(np.int16).tobytes()

        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.run_in_executor = AsyncMock(
                return_value=expected_audio
            )

            # Object with .text attribute
            class FakeLLMChunk:
                text = "Hello from LLM"

            result = await provider.ainvoke(FakeLLMChunk())

            assert isinstance(result, AudioChunk)


def _check_kokoro_available():
    """Check if Kokoro is available for integration tests."""
    try:
        from kokoro import KPipeline
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _check_kokoro_available(),
    reason="Kokoro not installed"
)
class TestKokoroTTSProviderIntegration:
    """Integration tests (requires Kokoro installed).

    These tests are skipped if Kokoro is not installed.
    """

    @pytest.mark.asyncio
    async def test_real_synthesis(self):
        """Test real synthesis with Kokoro."""
        provider = KokoroTTSProvider(
            lang_code="a",
            voice="af_bella",
        )

        try:
            await provider.connect()

            health = await provider.health_check()
            if health.status != ProviderHealth.HEALTHY:
                pytest.skip(f"Kokoro not ready: {health.message}")

            result = await provider.synthesize("Hello, world!")

            assert isinstance(result, bytes)
            assert len(result) > 0
            # PCM16 mono at 24kHz: should have some audio
            assert len(result) > 1000

        finally:
            await provider.disconnect()

    @pytest.mark.asyncio
    async def test_real_streaming(self):
        """Test real streaming with Kokoro."""
        provider = KokoroTTSProvider(
            lang_code="a",
            voice="af_bella",
        )

        try:
            await provider.connect()

            health = await provider.health_check()
            if health.status != ProviderHealth.HEALTHY:
                pytest.skip(f"Kokoro not ready: {health.message}")

            async def text_gen():
                yield "Hello."
                yield "How are you today?"

            chunks = []
            async for chunk in provider.synthesize_stream(text_gen()):
                chunks.append(chunk)

            assert len(chunks) >= 1
            for chunk in chunks:
                assert isinstance(chunk, AudioChunk)
                assert len(chunk.data) > 0

        finally:
            await provider.disconnect()
