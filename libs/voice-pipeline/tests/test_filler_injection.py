"""Tests for filler sound injection.

Validates FillerInjector and FillerConfig from voice_pipeline.streaming.filler,
covering warmup, round-robin selection, max duration trim, fade-out, disabled
mode, and graceful error handling.
"""

import asyncio
from typing import AsyncIterator, Optional

import numpy as np
import pytest

from voice_pipeline.interfaces import AudioChunk
from voice_pipeline.interfaces.tts import TTSInterface
from voice_pipeline.streaming.filler import FillerConfig, FillerInjector


# =============================================================================
# Mock TTS Provider
# =============================================================================


class MockTTS(TTSInterface):
    """Mock TTS that generates a short 440 Hz sine wave for each text input."""

    name = "MockFillerTTS"

    def __init__(self, *, fail: bool = False, empty: bool = False):
        self.synthesized_texts: list[str] = []
        self._fail = fail
        self._empty = empty

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        async for text in text_stream:
            self.synthesized_texts.append(text)

            if self._fail:
                raise RuntimeError("TTS synthesis failed")

            if self._empty:
                return

            sr = 16000
            t = np.linspace(0, 0.3, int(sr * 0.3))
            samples = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
            yield AudioChunk(data=samples.tobytes(), sample_rate=sr)

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> bytes:
        self.synthesized_texts.append(text)

        if self._fail:
            raise RuntimeError("TTS synthesis failed")

        if self._empty:
            return b""

        sr = 16000
        t = np.linspace(0, 0.3, int(sr * 0.3))
        samples = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
        return samples.tobytes()


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tts() -> MockTTS:
    """Create a working MockTTS instance."""
    return MockTTS()


@pytest.fixture
def failing_tts() -> MockTTS:
    """Create a MockTTS that raises on every call."""
    return MockTTS(fail=True)


@pytest.fixture
def empty_tts() -> MockTTS:
    """Create a MockTTS that returns no audio data."""
    return MockTTS(empty=True)


# =============================================================================
# FillerConfig Tests
# =============================================================================


class TestFillerConfig:
    """Tests for FillerConfig defaults and customization."""

    def test_default_values(self):
        """Default config should have sane values."""
        config = FillerConfig()

        assert config.enabled is True
        assert config.language == "en"
        assert config.custom_fillers is None
        assert config.filler_voice is None
        assert config.max_filler_duration_ms == 800.0
        assert config.fade_out_ms == 50.0

    def test_custom_values(self):
        """Custom values should override defaults."""
        config = FillerConfig(
            enabled=False,
            language="pt",
            custom_fillers=["espera", "só um instante"],
            filler_voice="pf_dora",
            max_filler_duration_ms=500.0,
            fade_out_ms=100.0,
        )

        assert config.enabled is False
        assert config.language == "pt"
        assert config.custom_fillers == ["espera", "só um instante"]
        assert config.filler_voice == "pf_dora"
        assert config.max_filler_duration_ms == 500.0
        assert config.fade_out_ms == 100.0


# =============================================================================
# Warmup Tests
# =============================================================================


class TestFillerWarmup:
    """Tests for FillerInjector.warmup() method."""

    @pytest.mark.asyncio
    async def test_warmup_creates_fillers(self, tts: MockTTS):
        """Warmup should synthesize filler texts and store AudioChunks."""
        injector = FillerInjector(FillerConfig(language="en"))
        elapsed = await injector.warmup(tts)

        assert injector.is_ready is True
        assert elapsed > 0
        # English defaults: ["hmm", "one moment"]
        assert len(tts.synthesized_texts) == 2

    @pytest.mark.asyncio
    async def test_warmup_creates_fillers_pt(self, tts: MockTTS):
        """Warmup with Portuguese language should use PT filler texts."""
        injector = FillerInjector(FillerConfig(language="pt-BR"))
        await injector.warmup(tts)

        assert injector.is_ready is True
        assert "hmm" in tts.synthesized_texts
        assert "um momento" in tts.synthesized_texts

    @pytest.mark.asyncio
    async def test_warmup_with_custom_fillers(self, tts: MockTTS):
        """Warmup should use custom filler texts when provided."""
        config = FillerConfig(custom_fillers=["wait", "hold on", "let me think"])
        injector = FillerInjector(config)
        await injector.warmup(tts)

        assert injector.is_ready is True
        assert tts.synthesized_texts == ["wait", "hold on", "let me think"]

    @pytest.mark.asyncio
    async def test_warmup_returns_elapsed_time(self, tts: MockTTS):
        """Warmup should return the time taken in milliseconds."""
        injector = FillerInjector(FillerConfig())
        elapsed = await injector.warmup(tts)

        assert isinstance(elapsed, float)
        assert elapsed >= 0.0

    @pytest.mark.asyncio
    async def test_not_ready_before_warmup(self):
        """Injector should not be ready before warmup is called."""
        injector = FillerInjector(FillerConfig())

        assert injector.is_ready is False

    @pytest.mark.asyncio
    async def test_not_ready_before_warmup_get_filler_returns_none(self):
        """get_filler should return None before warmup."""
        injector = FillerInjector(FillerConfig())

        assert injector.get_filler() is None


# =============================================================================
# get_filler Tests
# =============================================================================


class TestGetFiller:
    """Tests for FillerInjector.get_filler() method."""

    @pytest.mark.asyncio
    async def test_get_filler_returns_audio_chunk(self, tts: MockTTS):
        """get_filler should return an AudioChunk after warmup."""
        injector = FillerInjector(FillerConfig(language="en"))
        await injector.warmup(tts)

        filler = injector.get_filler()

        assert filler is not None
        assert isinstance(filler, AudioChunk)
        assert isinstance(filler.data, bytes)
        assert len(filler.data) > 0
        assert filler.sample_rate == 16000

    @pytest.mark.asyncio
    async def test_round_robin_cycles_through_fillers(self, tts: MockTTS):
        """Multiple get_filler calls should cycle through fillers in order."""
        injector = FillerInjector(FillerConfig(language="en"))
        await injector.warmup(tts)

        # English defaults produce 2 fillers: "hmm" and "one moment"
        filler_0 = injector.get_filler()
        filler_1 = injector.get_filler()
        filler_2 = injector.get_filler()  # Should wrap around to index 0
        filler_3 = injector.get_filler()  # Should wrap around to index 1

        assert filler_0 is not None
        assert filler_1 is not None
        assert filler_2 is not None
        assert filler_3 is not None

        # Round-robin: index 0, 1, 0, 1
        assert filler_0.data == filler_2.data
        assert filler_1.data == filler_3.data

    @pytest.mark.asyncio
    async def test_round_robin_with_single_filler(self, tts: MockTTS):
        """Round-robin with a single filler should always return the same one."""
        config = FillerConfig(custom_fillers=["hmm"])
        injector = FillerInjector(config)
        await injector.warmup(tts)

        filler_a = injector.get_filler()
        filler_b = injector.get_filler()
        filler_c = injector.get_filler()

        assert filler_a is not None
        assert filler_a.data == filler_b.data == filler_c.data


# =============================================================================
# Disabled Injector Tests
# =============================================================================


class TestDisabledInjector:
    """Tests for FillerInjector with enabled=False."""

    @pytest.mark.asyncio
    async def test_disabled_warmup_returns_zero(self, tts: MockTTS):
        """Disabled injector warmup should return 0.0 ms."""
        config = FillerConfig(enabled=False)
        injector = FillerInjector(config)
        elapsed = await injector.warmup(tts)

        assert elapsed == 0.0
        assert injector.is_ready is False

    @pytest.mark.asyncio
    async def test_disabled_get_filler_returns_none(self, tts: MockTTS):
        """Disabled injector get_filler should return None even after warmup."""
        config = FillerConfig(enabled=False)
        injector = FillerInjector(config)
        await injector.warmup(tts)

        assert injector.get_filler() is None

    @pytest.mark.asyncio
    async def test_disabled_does_not_synthesize(self, tts: MockTTS):
        """Disabled injector should not call TTS at all."""
        config = FillerConfig(enabled=False)
        injector = FillerInjector(config)
        await injector.warmup(tts)

        assert len(tts.synthesized_texts) == 0

    def test_enabled_property_reflects_config(self):
        """enabled property should reflect config value."""
        assert FillerInjector(FillerConfig(enabled=True)).enabled is True
        assert FillerInjector(FillerConfig(enabled=False)).enabled is False


# =============================================================================
# Max Duration Trim Tests
# =============================================================================


class TestMaxDurationTrim:
    """Tests for max_filler_duration_ms trimming."""

    @pytest.mark.asyncio
    async def test_trim_applies_to_long_audio(self, tts: MockTTS):
        """Audio exceeding max_filler_duration_ms should be trimmed."""
        # MockTTS generates 300ms of audio at 16kHz.
        # Set max to 100ms to force trimming.
        config = FillerConfig(
            custom_fillers=["test"],
            max_filler_duration_ms=100.0,
            fade_out_ms=0.0,  # No fade to isolate trim behavior
        )
        injector = FillerInjector(config)
        await injector.warmup(tts)

        filler = injector.get_filler()
        assert filler is not None

        # At 16kHz, 100ms = 1600 samples = 3200 bytes (PCM16)
        expected_bytes = int(100.0 / 1000 * 16000) * 2
        assert len(filler.data) == expected_bytes

    @pytest.mark.asyncio
    async def test_no_trim_when_under_max_duration(self, tts: MockTTS):
        """Audio shorter than max_filler_duration_ms should not be trimmed."""
        # MockTTS generates 300ms. Set max to 1000ms (no trim needed).
        config = FillerConfig(
            custom_fillers=["test"],
            max_filler_duration_ms=1000.0,
            fade_out_ms=0.0,
        )
        injector = FillerInjector(config)
        await injector.warmup(tts)

        filler = injector.get_filler()
        assert filler is not None

        # 300ms at 16kHz = 4800 samples = 9600 bytes
        expected_bytes = int(0.3 * 16000) * 2
        assert len(filler.data) == expected_bytes


# =============================================================================
# Fade-Out Tests
# =============================================================================


class TestFadeOut:
    """Tests for fade-out at the end of filler audio."""

    @pytest.mark.asyncio
    async def test_fade_out_applies(self, tts: MockTTS):
        """Fade-out should reduce amplitude at the tail of the audio."""
        config = FillerConfig(
            custom_fillers=["test"],
            max_filler_duration_ms=1000.0,  # No trim
            fade_out_ms=50.0,
        )
        injector = FillerInjector(config)
        await injector.warmup(tts)

        filler = injector.get_filler()
        assert filler is not None

        samples = np.frombuffer(filler.data, dtype=np.int16)

        # The very last sample should be ~0 due to fade-out
        assert abs(samples[-1]) < 100  # near zero after fade

        # Samples before the fade region should have normal amplitude
        fade_samples = int(50.0 / 1000 * 16000)  # 800 samples
        pre_fade_region = samples[: -fade_samples]
        assert np.max(np.abs(pre_fade_region)) > 1000  # significant amplitude

    @pytest.mark.asyncio
    async def test_no_fade_when_zero(self, tts: MockTTS):
        """With fade_out_ms=0, audio tail should retain full amplitude."""
        config = FillerConfig(
            custom_fillers=["test"],
            max_filler_duration_ms=1000.0,
            fade_out_ms=0.0,
        )
        injector = FillerInjector(config)
        await injector.warmup(tts)

        filler = injector.get_filler()
        assert filler is not None

        samples = np.frombuffer(filler.data, dtype=np.int16)

        # Generate the expected raw sine wave for comparison
        sr = 16000
        t = np.linspace(0, 0.3, int(sr * 0.3))
        expected = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)

        np.testing.assert_array_equal(samples, expected)


# =============================================================================
# Graceful Error Handling Tests
# =============================================================================


class TestGracefulErrorHandling:
    """Tests for graceful handling of TTS failures and empty results."""

    @pytest.mark.asyncio
    async def test_failed_tts_does_not_crash(self, failing_tts: MockTTS):
        """If TTS raises, warmup should handle it gracefully."""
        injector = FillerInjector(FillerConfig(language="en"))
        elapsed = await injector.warmup(failing_tts)

        # Should complete without exception
        assert elapsed >= 0.0
        # No fillers synthesized, so not ready
        assert injector.is_ready is False
        assert injector.get_filler() is None

    @pytest.mark.asyncio
    async def test_empty_tts_does_not_crash(self, empty_tts: MockTTS):
        """If TTS returns no chunks, warmup should handle gracefully."""
        injector = FillerInjector(FillerConfig(language="en"))
        elapsed = await injector.warmup(empty_tts)

        assert elapsed >= 0.0
        assert injector.is_ready is False
        assert injector.get_filler() is None

    @pytest.mark.asyncio
    async def test_partial_failure_keeps_successful_fillers(self):
        """If some fillers fail and others succeed, keep the successful ones."""

        class PartialFailTTS(TTSInterface):
            """TTS that fails on the second text only."""

            name = "PartialFailTTS"

            def __init__(self):
                self._call_count = 0

            async def synthesize_stream(
                self,
                text_stream: AsyncIterator[str],
                voice: Optional[str] = None,
                speed: float = 1.0,
                **kwargs,
            ) -> AsyncIterator[AudioChunk]:
                async for text in text_stream:
                    self._call_count += 1
                    if self._call_count == 2:
                        raise RuntimeError("Second filler fails")

                    sr = 16000
                    t = np.linspace(0, 0.3, int(sr * 0.3))
                    samples = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
                    yield AudioChunk(data=samples.tobytes(), sample_rate=sr)

            async def synthesize(self, text, voice=None, speed=1.0, **kwargs):
                return b"\x00" * 100

        injector = FillerInjector(FillerConfig(language="en"))
        await injector.warmup(PartialFailTTS())

        # "hmm" succeeds (call 1), "one moment" fails (call 2)
        assert injector.is_ready is True
        filler = injector.get_filler()
        assert filler is not None
        assert isinstance(filler, AudioChunk)

    @pytest.mark.asyncio
    async def test_default_config_when_none_passed(self, tts: MockTTS):
        """FillerInjector(None) should use default FillerConfig."""
        injector = FillerInjector(None)
        await injector.warmup(tts)

        assert injector.is_ready is True
        assert injector.enabled is True
