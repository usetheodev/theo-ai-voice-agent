"""Tests for NoiseAwareVAD wrapper with automatic noise floor calibration.

Tests cover:
- Quiet environment calibration (threshold stays close to base)
- Noisy environment calibration (threshold increases)
- Manual calibration via calibrate()
- Threshold clamping to max_threshold
- Threshold clamping to min_threshold
- Delegation of frame_size_ms to inner VAD
- reset() delegates to inner VAD without resetting calibration
- reset_calibration() resets calibration state
- Properties: noise_floor_rms, adjusted_threshold, is_calibrated
"""

import struct

import numpy as np
import pytest

from voice_pipeline.interfaces.vad import VADEvent, VADInterface, SpeechState
from voice_pipeline.providers.vad.noise_aware import NoiseAwareVAD, NoiseFloorConfig


# ==============================================================================
# Helper: Mock Inner VAD
# ==============================================================================


class MockInnerVAD(VADInterface):
    """Minimal mock VAD for testing the NoiseAwareVAD wrapper."""

    name = "MockInnerVAD"

    def __init__(self, frame_size_ms: int = 30):
        self._frame_size_ms = frame_size_ms
        self.process_call_count = 0
        self.reset_call_count = 0
        self._threshold: float | None = None

    async def process(self, audio_chunk: bytes, sample_rate: int) -> VADEvent:
        self.process_call_count += 1
        return VADEvent(is_speech=False, confidence=0.0, state=SpeechState.SILENCE)

    def reset(self) -> None:
        self.reset_call_count += 1

    def set_threshold(self, threshold: float) -> None:
        self._threshold = threshold

    @property
    def frame_size_ms(self) -> int:
        return self._frame_size_ms


# ==============================================================================
# Helper: PCM16 Audio Generation
# ==============================================================================


def generate_pcm16_noise(
    duration_s: float,
    sample_rate: int = 16000,
    rms_level: float = 0.01,
) -> bytes:
    """Generate PCM16 audio with gaussian noise at a given RMS level.

    Args:
        duration_s: Duration in seconds.
        sample_rate: Sample rate in Hz.
        rms_level: Target RMS level in the range [0.0, 1.0] relative to full scale.

    Returns:
        PCM16 audio bytes.
    """
    num_samples = int(sample_rate * duration_s)
    # Generate gaussian noise and scale to desired RMS
    samples = np.random.default_rng(42).normal(0, rms_level, num_samples).astype(np.float32)
    # Clip to [-1.0, 1.0] then convert to int16
    samples = np.clip(samples, -1.0, 1.0)
    pcm16 = (samples * 32767).astype(np.int16)
    return pcm16.tobytes()


def generate_pcm16_silence(
    duration_s: float,
    sample_rate: int = 16000,
) -> bytes:
    """Generate near-silent PCM16 audio (zeros)."""
    num_samples = int(sample_rate * duration_s)
    return b"\x00\x00" * num_samples


def split_audio_into_chunks(
    audio: bytes,
    chunk_duration_s: float = 0.03,
    sample_rate: int = 16000,
) -> list[bytes]:
    """Split PCM16 audio into fixed-size chunks."""
    chunk_size_bytes = int(sample_rate * chunk_duration_s) * 2  # 2 bytes per sample
    chunks = []
    for i in range(0, len(audio), chunk_size_bytes):
        chunk = audio[i : i + chunk_size_bytes]
        if len(chunk) >= 2:  # At least one sample
            chunks.append(chunk)
    return chunks


# ==============================================================================
# Tests: NoiseFloorConfig
# ==============================================================================


class TestNoiseFloorConfig:
    """Tests for NoiseFloorConfig defaults and customization."""

    def test_default_values(self):
        config = NoiseFloorConfig()

        assert config.calibration_duration_s == 2.5
        assert config.min_threshold == 0.3
        assert config.max_threshold == 0.85
        assert config.base_threshold == 0.5
        assert config.noise_multiplier == 3.0
        assert config.auto_calibrate is True

    def test_custom_values(self):
        config = NoiseFloorConfig(
            calibration_duration_s=1.0,
            min_threshold=0.2,
            max_threshold=0.9,
            base_threshold=0.4,
            noise_multiplier=2.0,
            auto_calibrate=False,
        )

        assert config.calibration_duration_s == 1.0
        assert config.min_threshold == 0.2
        assert config.max_threshold == 0.9
        assert config.base_threshold == 0.4
        assert config.noise_multiplier == 2.0
        assert config.auto_calibrate is False


# ==============================================================================
# Tests: NoiseAwareVAD
# ==============================================================================


class TestNoiseAwareVADInitialization:
    """Tests for NoiseAwareVAD initialization and default state."""

    def test_default_config(self):
        inner = MockInnerVAD()
        vad = NoiseAwareVAD(inner)

        assert vad.is_calibrated is False
        assert vad.noise_floor_rms == 0.0
        assert vad.adjusted_threshold == 0.5  # base_threshold default
        assert vad.name == "NoiseAwareVAD"

    def test_custom_config(self):
        inner = MockInnerVAD()
        config = NoiseFloorConfig(base_threshold=0.6)
        vad = NoiseAwareVAD(inner, config)

        assert vad.adjusted_threshold == 0.6
        assert vad.is_calibrated is False


class TestNoiseAwareVADQuietEnvironment:
    """Quiet environment: threshold stays close to base_threshold."""

    @pytest.mark.asyncio
    async def test_quiet_environment_threshold_stays_near_base(self):
        """In a very quiet environment the noise floor is low, so
        the adjusted threshold should stay close to base_threshold."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.5,
            base_threshold=0.5,
            noise_multiplier=3.0,
            min_threshold=0.3,
            max_threshold=0.85,
        )
        vad = NoiseAwareVAD(inner, config)

        # Feed near-silent audio (RMS ~ 0)
        audio = generate_pcm16_silence(duration_s=1.0, sample_rate=16000)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)

        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        # noise_floor_rms should be very close to 0
        assert vad.noise_floor_rms < 0.001
        # adjusted_threshold should be very close to base_threshold
        assert abs(vad.adjusted_threshold - config.base_threshold) < 0.01


class TestNoiseAwareVADNoisyEnvironment:
    """Noisy environment: threshold goes up."""

    @pytest.mark.asyncio
    async def test_noisy_environment_threshold_increases(self):
        """In a noisy environment the noise floor is higher, so
        adjusted_threshold should be significantly above base_threshold."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.5,
            base_threshold=0.5,
            noise_multiplier=3.0,
            min_threshold=0.3,
            max_threshold=0.85,
        )
        vad = NoiseAwareVAD(inner, config)

        # Feed noisy audio (RMS ~ 0.05)
        audio = generate_pcm16_noise(duration_s=1.0, sample_rate=16000, rms_level=0.05)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)

        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        # noise_floor_rms should be in the ballpark of the input RMS
        assert vad.noise_floor_rms > 0.01
        # threshold should be higher than base
        assert vad.adjusted_threshold > config.base_threshold


class TestNoiseAwareVADManualCalibration:
    """Manual calibration via calibrate() method."""

    @pytest.mark.asyncio
    async def test_manual_calibration_works(self):
        """calibrate() should compute noise floor and return the adjusted threshold."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            base_threshold=0.5,
            noise_multiplier=3.0,
            min_threshold=0.3,
            max_threshold=0.85,
            auto_calibrate=False,
        )
        vad = NoiseAwareVAD(inner, config)

        # Prepare calibration audio chunks
        audio = generate_pcm16_noise(duration_s=1.0, sample_rate=16000, rms_level=0.03)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.1, sample_rate=16000)

        threshold = await vad.calibrate(chunks, 16000)

        assert vad.is_calibrated is True
        assert threshold == vad.adjusted_threshold
        assert vad.noise_floor_rms > 0.0
        assert threshold > config.base_threshold

    @pytest.mark.asyncio
    async def test_manual_calibration_sets_inner_threshold(self):
        """calibrate() should call set_threshold on the inner VAD if supported."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            base_threshold=0.5,
            noise_multiplier=3.0,
            min_threshold=0.3,
            max_threshold=0.85,
        )
        vad = NoiseAwareVAD(inner, config)

        audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.04)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.1, sample_rate=16000)

        threshold = await vad.calibrate(chunks, 16000)

        # The inner VAD should have received the adjusted threshold
        assert inner._threshold == threshold

    @pytest.mark.asyncio
    async def test_manual_calibration_with_silence(self):
        """Manual calibration with silent audio keeps threshold near base."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(base_threshold=0.5)
        vad = NoiseAwareVAD(inner, config)

        audio = generate_pcm16_silence(duration_s=0.5, sample_rate=16000)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.1, sample_rate=16000)

        threshold = await vad.calibrate(chunks, 16000)

        assert vad.is_calibrated is True
        assert abs(threshold - config.base_threshold) < 0.01


class TestNoiseAwareVADThresholdClamping:
    """Threshold clamping to min_threshold and max_threshold."""

    @pytest.mark.asyncio
    async def test_threshold_clamped_to_max(self):
        """Very loud noise should clamp the threshold to max_threshold."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.3,
            base_threshold=0.5,
            noise_multiplier=5.0,
            max_threshold=0.85,
            min_threshold=0.3,
        )
        vad = NoiseAwareVAD(inner, config)

        # Very loud noise (RMS ~ 0.3) -> base + 0.3 * 5.0 = 2.0 -> clamped to 0.85
        audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.3)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)

        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        assert vad.adjusted_threshold == config.max_threshold

    @pytest.mark.asyncio
    async def test_threshold_clamped_to_min(self):
        """When base_threshold is set below min_threshold and noise is zero,
        the threshold should be clamped to min_threshold."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.3,
            base_threshold=0.1,  # Below min_threshold
            noise_multiplier=3.0,
            min_threshold=0.3,
            max_threshold=0.85,
        )
        vad = NoiseAwareVAD(inner, config)

        # Silent audio: threshold = base(0.1) + 0.0 * 3.0 = 0.1 -> clamped to 0.3
        audio = generate_pcm16_silence(duration_s=0.5, sample_rate=16000)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)

        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        assert vad.adjusted_threshold == config.min_threshold


class TestNoiseAwareVADDelegation:
    """Tests for delegation to the inner VAD."""

    def test_frame_size_ms_delegates_to_inner(self):
        """frame_size_ms should return the inner VAD's frame_size_ms."""
        inner = MockInnerVAD(frame_size_ms=20)
        vad = NoiseAwareVAD(inner)

        assert vad.frame_size_ms == 20

    def test_frame_size_ms_delegates_different_values(self):
        """Verify delegation for various frame sizes."""
        for ms in [10, 20, 30, 60]:
            inner = MockInnerVAD(frame_size_ms=ms)
            vad = NoiseAwareVAD(inner)
            assert vad.frame_size_ms == ms

    @pytest.mark.asyncio
    async def test_process_delegates_to_inner(self):
        """process() should delegate audio processing to the inner VAD."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(auto_calibrate=False)
        vad = NoiseAwareVAD(inner, config)

        audio = generate_pcm16_silence(duration_s=0.03, sample_rate=16000)
        event = await vad.process(audio, 16000)

        assert inner.process_call_count == 1
        assert isinstance(event, VADEvent)
        assert event.is_speech is False


class TestNoiseAwareVADReset:
    """Tests for reset() and reset_calibration()."""

    @pytest.mark.asyncio
    async def test_reset_delegates_to_inner_vad(self):
        """reset() should call reset on the inner VAD."""
        inner = MockInnerVAD()
        vad = NoiseAwareVAD(inner)

        vad.reset()

        assert inner.reset_call_count == 1

    @pytest.mark.asyncio
    async def test_reset_does_not_reset_calibration(self):
        """reset() should NOT reset the calibration state."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(calibration_duration_s=0.3)
        vad = NoiseAwareVAD(inner, config)

        # First, calibrate
        audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.05)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)
        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        saved_threshold = vad.adjusted_threshold
        saved_noise_floor = vad.noise_floor_rms

        # Now reset
        vad.reset()

        # Calibration should be preserved
        assert vad.is_calibrated is True
        assert vad.adjusted_threshold == saved_threshold
        assert vad.noise_floor_rms == saved_noise_floor

    @pytest.mark.asyncio
    async def test_reset_calibration_resets_state(self):
        """reset_calibration() should reset all calibration state."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.3,
            base_threshold=0.5,
        )
        vad = NoiseAwareVAD(inner, config)

        # Calibrate first
        audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.05)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)
        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        assert vad.noise_floor_rms > 0.0
        assert vad.adjusted_threshold != config.base_threshold

        # Reset calibration
        vad.reset_calibration()

        assert vad.is_calibrated is False
        assert vad.noise_floor_rms == 0.0
        assert vad.adjusted_threshold == config.base_threshold

    @pytest.mark.asyncio
    async def test_recalibration_after_reset(self):
        """After reset_calibration(), auto-calibration should run again."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.3,
            base_threshold=0.5,
            auto_calibrate=True,
        )
        vad = NoiseAwareVAD(inner, config)

        # First calibration with quiet audio
        quiet_audio = generate_pcm16_silence(duration_s=0.5, sample_rate=16000)
        for chunk in split_audio_into_chunks(quiet_audio, 0.03, 16000):
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        first_threshold = vad.adjusted_threshold

        # Reset and recalibrate with noisy audio
        vad.reset_calibration()

        noisy_audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.08)
        for chunk in split_audio_into_chunks(noisy_audio, 0.03, 16000):
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        second_threshold = vad.adjusted_threshold

        # Second calibration should produce a higher threshold
        assert second_threshold > first_threshold


class TestNoiseAwareVADProperties:
    """Tests for read-only properties."""

    def test_noise_floor_rms_initial(self):
        inner = MockInnerVAD()
        vad = NoiseAwareVAD(inner)
        assert vad.noise_floor_rms == 0.0

    def test_adjusted_threshold_initial(self):
        inner = MockInnerVAD()
        config = NoiseFloorConfig(base_threshold=0.6)
        vad = NoiseAwareVAD(inner, config)
        assert vad.adjusted_threshold == 0.6

    def test_is_calibrated_initial(self):
        inner = MockInnerVAD()
        vad = NoiseAwareVAD(inner)
        assert vad.is_calibrated is False

    @pytest.mark.asyncio
    async def test_noise_floor_rms_after_calibration(self):
        inner = MockInnerVAD()
        config = NoiseFloorConfig(calibration_duration_s=0.3)
        vad = NoiseAwareVAD(inner, config)

        audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.04)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)
        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        # noise_floor_rms = mean_rms + stddev, should be in the range of the input RMS
        assert 0.01 < vad.noise_floor_rms < 0.15

    @pytest.mark.asyncio
    async def test_adjusted_threshold_after_calibration(self):
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.3,
            base_threshold=0.5,
            noise_multiplier=3.0,
        )
        vad = NoiseAwareVAD(inner, config)

        audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.04)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)
        for chunk in chunks:
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        # adjusted_threshold = base + noise_floor_rms * multiplier
        expected_approx = config.base_threshold + vad.noise_floor_rms * config.noise_multiplier
        expected_clamped = max(config.min_threshold, min(config.max_threshold, expected_approx))
        assert abs(vad.adjusted_threshold - expected_clamped) < 1e-6


class TestNoiseAwareVADAutoCalibrationDisabled:
    """Tests for behavior when auto_calibrate is False."""

    @pytest.mark.asyncio
    async def test_no_auto_calibration_when_disabled(self):
        """When auto_calibrate is False, processing frames should not trigger calibration."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.3,
            auto_calibrate=False,
        )
        vad = NoiseAwareVAD(inner, config)

        audio = generate_pcm16_noise(duration_s=1.0, sample_rate=16000, rms_level=0.05)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.03, sample_rate=16000)

        for chunk in chunks:
            await vad.process(chunk, 16000)

        # Should NOT be calibrated automatically
        assert vad.is_calibrated is False
        assert vad.noise_floor_rms == 0.0
        assert vad.adjusted_threshold == config.base_threshold

    @pytest.mark.asyncio
    async def test_manual_calibration_still_works_when_auto_disabled(self):
        """Even with auto_calibrate=False, manual calibrate() should work."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            auto_calibrate=False,
            base_threshold=0.5,
        )
        vad = NoiseAwareVAD(inner, config)

        audio = generate_pcm16_noise(duration_s=0.5, sample_rate=16000, rms_level=0.04)
        chunks = split_audio_into_chunks(audio, chunk_duration_s=0.1, sample_rate=16000)

        threshold = await vad.calibrate(chunks, 16000)

        assert vad.is_calibrated is True
        assert threshold > config.base_threshold


class TestNoiseAwareVADEdgeCases:
    """Edge cases and robustness tests."""

    @pytest.mark.asyncio
    async def test_empty_audio_chunk(self):
        """Processing an empty chunk should not crash."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(auto_calibrate=False)
        vad = NoiseAwareVAD(inner, config)

        # Empty bytes (< 2 bytes) - should still delegate to inner VAD
        event = await vad.process(b"", 16000)
        assert isinstance(event, VADEvent)
        assert inner.process_call_count == 1

    @pytest.mark.asyncio
    async def test_single_sample_chunk(self):
        """Processing a chunk with exactly 1 sample (2 bytes) should work."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(calibration_duration_s=0.001)
        vad = NoiseAwareVAD(inner, config)

        # 1 sample = 2 bytes
        chunk = struct.pack("<h", 1000)
        event = await vad.process(chunk, 16000)

        assert isinstance(event, VADEvent)
        assert inner.process_call_count == 1

    @pytest.mark.asyncio
    async def test_calibrate_with_empty_list(self):
        """Calibrating with no chunks should complete without error."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(base_threshold=0.5)
        vad = NoiseAwareVAD(inner, config)

        threshold = await vad.calibrate([], 16000)

        # Should be calibrated (finalize is called) but noise floor stays 0
        assert vad.is_calibrated is True
        assert vad.noise_floor_rms == 0.0
        assert threshold == config.base_threshold

    @pytest.mark.asyncio
    async def test_multiple_calibrations_overwrite(self):
        """Calling calibrate() multiple times should use latest data."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(base_threshold=0.5, noise_multiplier=3.0)
        vad = NoiseAwareVAD(inner, config)

        # First calibration: quiet
        quiet_chunks = split_audio_into_chunks(
            generate_pcm16_silence(0.3, 16000), 0.1, 16000
        )
        t1 = await vad.calibrate(quiet_chunks, 16000)

        # Second calibration: noisy
        noisy_chunks = split_audio_into_chunks(
            generate_pcm16_noise(0.3, 16000, rms_level=0.1), 0.1, 16000
        )
        t2 = await vad.calibrate(noisy_chunks, 16000)

        # Second calibration should produce higher threshold
        assert t2 > t1

    @pytest.mark.asyncio
    async def test_auto_calibration_only_runs_once(self):
        """Auto-calibration should only happen during the calibration period.
        After calibration, additional frames should not change the threshold."""
        inner = MockInnerVAD()
        config = NoiseFloorConfig(
            calibration_duration_s=0.3,
            base_threshold=0.5,
        )
        vad = NoiseAwareVAD(inner, config)

        # Calibrate with quiet audio
        quiet_audio = generate_pcm16_silence(duration_s=0.5, sample_rate=16000)
        for chunk in split_audio_into_chunks(quiet_audio, 0.03, 16000):
            await vad.process(chunk, 16000)

        assert vad.is_calibrated is True
        threshold_after_cal = vad.adjusted_threshold

        # Now feed loud audio - should not change the threshold
        loud_audio = generate_pcm16_noise(duration_s=1.0, sample_rate=16000, rms_level=0.5)
        for chunk in split_audio_into_chunks(loud_audio, 0.03, 16000):
            await vad.process(chunk, 16000)

        assert vad.adjusted_threshold == threshold_after_cal
