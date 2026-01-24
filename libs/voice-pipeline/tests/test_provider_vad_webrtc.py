"""Tests for WebRTC VAD provider."""

import asyncio
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from voice_pipeline.providers.vad.webrtc import (
    WebRTCVADProvider,
    WebRTCVADConfig,
)
from voice_pipeline.providers.base import ProviderHealth
from voice_pipeline.interfaces.vad import VADEvent, SpeechState


# =============================================================================
# Test Configuration
# =============================================================================


class TestWebRTCVADConfig:
    """Tests for WebRTCVADConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = WebRTCVADConfig()

        assert config.mode == 2
        assert config.frame_duration_ms == 30
        assert config.min_speech_frames == 2
        assert config.min_silence_frames == 15
        assert config.sample_rate == 16000

    def test_custom_values(self):
        """Test custom configuration values."""
        config = WebRTCVADConfig(
            mode=3,
            frame_duration_ms=20,
            min_speech_frames=3,
            min_silence_frames=20,
            sample_rate=8000,
        )

        assert config.mode == 3
        assert config.frame_duration_ms == 20
        assert config.min_speech_frames == 3
        assert config.min_silence_frames == 20
        assert config.sample_rate == 8000


# =============================================================================
# Test Provider Initialization
# =============================================================================


class TestWebRTCVADProviderInit:
    """Tests for WebRTCVADProvider initialization."""

    def test_default_initialization(self):
        """Test initialization with default config."""
        provider = WebRTCVADProvider()

        assert provider._vad_config.mode == 2
        assert provider._vad_config.frame_duration_ms == 30
        assert provider._vad is None
        assert provider.provider_name == "webrtc-vad"
        assert provider.name == "WebRTCVAD"

    def test_initialization_with_config(self):
        """Test initialization with custom config."""
        config = WebRTCVADConfig(
            mode=1,
            frame_duration_ms=10,
            min_speech_frames=5,
        )
        provider = WebRTCVADProvider(config=config)

        assert provider._vad_config.mode == 1
        assert provider._vad_config.frame_duration_ms == 10
        assert provider._vad_config.min_speech_frames == 5

    def test_initialization_with_shortcuts(self):
        """Test initialization with shortcut parameters."""
        provider = WebRTCVADProvider(
            mode=3,
            frame_duration_ms=20,
            min_silence_frames=25,
        )

        assert provider._vad_config.mode == 3
        assert provider._vad_config.frame_duration_ms == 20
        assert provider._vad_config.min_silence_frames == 25

    def test_shortcuts_override_config(self):
        """Test that shortcuts override config values."""
        config = WebRTCVADConfig(mode=1, frame_duration_ms=10)
        provider = WebRTCVADProvider(
            config=config,
            mode=3,
            frame_duration_ms=30,
        )

        assert provider._vad_config.mode == 3
        assert provider._vad_config.frame_duration_ms == 30

    def test_frame_size_ms_property(self):
        """Test frame_size_ms property."""
        provider = WebRTCVADProvider(frame_duration_ms=20)
        assert provider.frame_size_ms == 20

    def test_repr(self):
        """Test string representation."""
        provider = WebRTCVADProvider(mode=2, frame_duration_ms=30)
        repr_str = repr(provider)

        assert "WebRTCVADProvider" in repr_str
        assert "mode=2" in repr_str
        assert "frame_duration_ms=30" in repr_str


# =============================================================================
# Test Provider Lifecycle
# =============================================================================


class TestWebRTCVADProviderLifecycle:
    """Tests for provider lifecycle (connect/disconnect)."""

    @pytest.mark.asyncio
    async def test_connect_initializes_vad(self):
        """Test that connect initializes the VAD."""
        provider = WebRTCVADProvider()

        mock_vad = MagicMock()

        with patch(
            "webrtcvad.Vad",
            return_value=mock_vad,
        ):
            await provider.connect()

            assert provider._vad is mock_vad
            assert provider._connected is True

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_mode(self):
        """Test connect with specific mode."""
        provider = WebRTCVADProvider(mode=3)

        with patch("webrtcvad.Vad") as MockVad:
            await provider.connect()
            MockVad.assert_called_once_with(3)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_connect_raises_without_webrtcvad(self):
        """Test that connect raises ImportError if webrtcvad not installed."""
        provider = WebRTCVADProvider()

        # Temporarily hide webrtcvad module
        import sys
        original_module = sys.modules.get("webrtcvad")
        sys.modules["webrtcvad"] = None

        try:
            with pytest.raises((ImportError, TypeError)):
                await provider.connect()
        finally:
            # Restore original module
            if original_module is not None:
                sys.modules["webrtcvad"] = original_module
            else:
                sys.modules.pop("webrtcvad", None)

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        """Test that disconnect cleans up resources."""
        provider = WebRTCVADProvider()

        with patch("webrtcvad.Vad"):
            await provider.connect()
            assert provider._vad is not None

            await provider.disconnect()

            assert provider._vad is None
            assert provider._connected is False

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager protocol."""
        provider = WebRTCVADProvider()

        with patch("webrtcvad.Vad"):
            async with provider:
                assert provider._connected is True
                assert provider._vad is not None

            assert provider._connected is False
            assert provider._vad is None


# =============================================================================
# Test Health Check
# =============================================================================


class TestWebRTCVADProviderHealthCheck:
    """Tests for provider health check."""

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_when_not_connected(self):
        """Test health check returns unhealthy when not connected."""
        provider = WebRTCVADProvider()

        result = await provider.health_check()

        assert result.status == ProviderHealth.UNHEALTHY
        assert "not initialized" in result.message.lower()

    @pytest.mark.asyncio
    async def test_health_check_healthy_when_vad_works(self):
        """Test health check returns healthy when VAD is working."""
        provider = WebRTCVADProvider(mode=2)

        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = False

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()
            result = await provider.health_check()

            assert result.status == ProviderHealth.HEALTHY
            assert "2" in result.message  # mode
            mock_vad.is_speech.assert_called()

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_health_check_unhealthy_on_error(self):
        """Test health check returns unhealthy on error."""
        provider = WebRTCVADProvider()

        mock_vad = MagicMock()
        mock_vad.is_speech.side_effect = Exception("VAD error")

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()
            result = await provider.health_check()

            assert result.status == ProviderHealth.UNHEALTHY
            assert "failed" in result.message.lower()

        await provider.disconnect()


# =============================================================================
# Test Frame Size Calculation
# =============================================================================


class TestWebRTCVADProviderFrameSize:
    """Tests for frame size calculation."""

    def test_calculate_frame_size_16khz_30ms(self):
        """Test frame size for 16kHz, 30ms."""
        provider = WebRTCVADProvider(
            sample_rate=16000,
            frame_duration_ms=30,
        )
        assert provider._calculate_frame_size(16000) == 480  # 16000 * 0.030

    def test_calculate_frame_size_16khz_20ms(self):
        """Test frame size for 16kHz, 20ms."""
        provider = WebRTCVADProvider(
            sample_rate=16000,
            frame_duration_ms=20,
        )
        assert provider._calculate_frame_size(16000) == 320  # 16000 * 0.020

    def test_calculate_frame_size_8khz_10ms(self):
        """Test frame size for 8kHz, 10ms."""
        provider = WebRTCVADProvider(
            sample_rate=8000,
            frame_duration_ms=10,
        )
        assert provider._calculate_frame_size(8000) == 80  # 8000 * 0.010

    def test_calculate_frame_size_48khz_30ms(self):
        """Test frame size for 48kHz, 30ms."""
        provider = WebRTCVADProvider(
            sample_rate=48000,
            frame_duration_ms=30,
        )
        assert provider._calculate_frame_size(48000) == 1440  # 48000 * 0.030


# =============================================================================
# Test Process Method
# =============================================================================


class TestWebRTCVADProviderProcess:
    """Tests for process method."""

    @pytest.mark.asyncio
    async def test_process_raises_without_vad(self):
        """Test that process raises when not connected."""
        provider = WebRTCVADProvider()

        with pytest.raises(RuntimeError, match="not initialized"):
            await provider.process(b"\x00" * 960, 16000)

    @pytest.mark.asyncio
    async def test_process_rejects_invalid_sample_rate(self):
        """Test that process rejects invalid sample rate."""
        provider = WebRTCVADProvider()

        mock_vad = MagicMock()
        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            with pytest.raises(ValueError, match="Unsupported sample rate"):
                await provider.process(b"\x00" * 960, 44100)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_process_rejects_invalid_frame_size(self):
        """Test that process rejects invalid frame size."""
        provider = WebRTCVADProvider(frame_duration_ms=30)

        mock_vad = MagicMock()
        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            # 30ms at 16kHz = 480 samples = 960 bytes
            # Send wrong size
            with pytest.raises(ValueError, match="Invalid frame size"):
                await provider.process(b"\x00" * 100, 16000)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_process_silence(self):
        """Test processing silence."""
        provider = WebRTCVADProvider(frame_duration_ms=30)

        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = False

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            # 30ms at 16kHz = 480 samples = 960 bytes
            audio_data = bytes(960)
            event = await provider.process(audio_data, 16000)

            assert isinstance(event, VADEvent)
            assert event.is_speech is False
            assert event.state == SpeechState.SILENCE

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_process_speech_detection(self):
        """Test detecting speech start."""
        provider = WebRTCVADProvider(
            frame_duration_ms=30,
            min_speech_frames=2,
        )

        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = True

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            audio_data = bytes(960)  # 30ms at 16kHz

            # First speech frame - uncertain
            event1 = await provider.process(audio_data, 16000)
            assert event1.is_speech is False  # Not enough consecutive frames
            assert event1.state == SpeechState.UNCERTAIN

            # Second speech frame - triggers speech start
            event2 = await provider.process(audio_data, 16000)
            assert event2.is_speech is True
            assert event2.state == SpeechState.SPEECH
            assert event2.speech_start_ms is not None

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_process_speech_end_detection(self):
        """Test detecting speech end."""
        provider = WebRTCVADProvider(
            frame_duration_ms=30,
            min_speech_frames=1,
            min_silence_frames=2,
        )

        mock_vad = MagicMock()

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            audio_data = bytes(960)

            # Start speech
            mock_vad.is_speech.return_value = True
            await provider.process(audio_data, 16000)
            assert provider._is_speaking is True

            # First silence frame
            mock_vad.is_speech.return_value = False
            event1 = await provider.process(audio_data, 16000)
            assert event1.is_speech is True  # Still speaking (not enough silence)

            # Second silence frame - triggers speech end
            event2 = await provider.process(audio_data, 16000)
            assert event2.is_speech is False
            assert event2.state == SpeechState.SILENCE
            assert event2.speech_end_ms is not None

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_process_records_metrics(self):
        """Test that process records metrics."""
        provider = WebRTCVADProvider(frame_duration_ms=30)

        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = False

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            audio_data = bytes(960)
            await provider.process(audio_data, 16000)

            assert provider.metrics.total_requests == 1
            assert provider.metrics.successful_requests == 1

        await provider.disconnect()


# =============================================================================
# Test Reset
# =============================================================================


class TestWebRTCVADProviderReset:
    """Tests for reset method."""

    def test_reset_clears_state(self):
        """Test that reset clears internal state."""
        provider = WebRTCVADProvider()

        # Set some state
        provider._is_speaking = True
        provider._speech_start_time = 1234567890.0
        provider._speech_frame_count = 5
        provider._silence_frame_count = 3

        provider.reset()

        assert provider._is_speaking is False
        assert provider._speech_start_time is None
        assert provider._speech_frame_count == 0
        assert provider._silence_frame_count == 0


# =============================================================================
# Test Set Mode
# =============================================================================


class TestWebRTCVADProviderSetMode:
    """Tests for set_mode method."""

    def test_set_mode_valid(self):
        """Test setting valid mode."""
        provider = WebRTCVADProvider(mode=1)

        mock_vad = MagicMock()
        provider._vad = mock_vad

        provider.set_mode(3)

        assert provider._vad_config.mode == 3
        mock_vad.set_mode.assert_called_once_with(3)

    def test_set_mode_invalid(self):
        """Test setting invalid mode raises error."""
        provider = WebRTCVADProvider()

        with pytest.raises(ValueError, match="must be 0, 1, 2, or 3"):
            provider.set_mode(5)


# =============================================================================
# Test Is Speech (sync method)
# =============================================================================


class TestWebRTCVADProviderIsSpeech:
    """Tests for is_speech sync method."""

    def test_is_speech_raises_without_vad(self):
        """Test that is_speech raises when not connected."""
        provider = WebRTCVADProvider()

        with pytest.raises(RuntimeError, match="not initialized"):
            provider.is_speech(b"\x00" * 960, 16000)

    def test_is_speech_returns_boolean(self):
        """Test that is_speech returns boolean."""
        provider = WebRTCVADProvider()

        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = True
        provider._vad = mock_vad

        result = provider.is_speech(b"\x00" * 960, 16000)

        assert result is True
        mock_vad.is_speech.assert_called_once()


# =============================================================================
# Test VoiceRunnable Interface
# =============================================================================


class TestWebRTCVADProviderVoiceRunnable:
    """Tests for VoiceRunnable interface."""

    @pytest.mark.asyncio
    async def test_ainvoke_with_bytes(self):
        """Test ainvoke with audio bytes."""
        provider = WebRTCVADProvider(frame_duration_ms=30)

        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = False

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            audio_data = bytes(960)
            result = await provider.ainvoke(audio_data)

            assert isinstance(result, VADEvent)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_astream(self):
        """Test astream method."""
        provider = WebRTCVADProvider(frame_duration_ms=30)

        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = False

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            audio_data = bytes(960)

            results = []
            async for result in provider.astream(audio_data):
                results.append(result)

            assert len(results) == 1
            assert isinstance(results[0], VADEvent)

        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_process_stream(self):
        """Test process_stream method."""
        provider = WebRTCVADProvider(frame_duration_ms=30)

        mock_vad = MagicMock()
        mock_vad.is_speech.side_effect = [False, True, True, False]

        with patch("webrtcvad.Vad", return_value=mock_vad):
            await provider.connect()

            async def audio_gen():
                for _ in range(4):
                    yield bytes(960)

            results = []
            async for event in provider.process_stream(audio_gen(), 16000):
                results.append(event)

            assert len(results) == 4

        await provider.disconnect()


# =============================================================================
# Integration Tests (require webrtcvad installed)
# =============================================================================


@pytest.mark.integration
class TestWebRTCVADProviderIntegration:
    """Integration tests with real WebRTC VAD.

    These tests require webrtcvad to be installed.
    """

    @pytest.mark.asyncio
    async def test_real_vad_silence(self):
        """Test real VAD with silence."""
        pytest.importorskip("webrtcvad")

        provider = WebRTCVADProvider(
            mode=2,
            frame_duration_ms=30,
        )

        try:
            await provider.connect()

            # Create silence (30ms at 16kHz)
            audio_data = bytes(960)  # All zeros = silence

            event = await provider.process(audio_data, 16000)

            assert isinstance(event, VADEvent)
            assert event.is_speech is False

        finally:
            await provider.disconnect()

    @pytest.mark.asyncio
    async def test_real_vad_with_noise(self):
        """Test real VAD with white noise (might trigger speech)."""
        pytest.importorskip("webrtcvad")

        provider = WebRTCVADProvider(
            mode=0,  # Least aggressive
            frame_duration_ms=30,
            min_speech_frames=1,
        )

        try:
            await provider.connect()

            # Create white noise
            np.random.seed(42)
            noise = np.random.randint(-5000, 5000, 480, dtype=np.int16)
            audio_data = noise.tobytes()

            event = await provider.process(audio_data, 16000)

            assert isinstance(event, VADEvent)
            # Note: noise might or might not trigger speech detection

        finally:
            await provider.disconnect()

    @pytest.mark.asyncio
    async def test_real_vad_streaming(self):
        """Test real VAD with streaming audio."""
        pytest.importorskip("webrtcvad")

        provider = WebRTCVADProvider(
            mode=2,
            frame_duration_ms=30,
        )

        try:
            await provider.connect()

            async def audio_gen():
                for _ in range(5):
                    yield bytes(960)  # Silence

            events = []
            async for event in provider.process_stream(audio_gen(), 16000):
                events.append(event)

            assert len(events) == 5
            assert all(isinstance(e, VADEvent) for e in events)

        finally:
            await provider.disconnect()
