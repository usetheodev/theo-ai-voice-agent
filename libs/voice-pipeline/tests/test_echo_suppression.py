"""Comprehensive tests for echo suppression module.

Tests cover all three modes (NONE, DUCKING, ENERGY_BASED), the TTS
lifecycle notifications, energy tracking, and edge cases like empty audio.

Audio helpers generate PCM16 bytes via numpy for deterministic testing.
"""

import struct
import time
from unittest.mock import patch

import numpy as np
import pytest

from voice_pipeline.audio.echo_suppressor import (
    EchoSuppressionConfig,
    EchoSuppressionMode,
    EchoSuppressor,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pcm16(frequency_hz: float, duration_s: float, amplitude: float = 0.5,
                sample_rate: int = 16000) -> bytes:
    """Generate a sine-wave PCM16 audio buffer.

    Args:
        frequency_hz: Tone frequency.
        duration_s: Duration in seconds.
        amplitude: Peak amplitude in [0.0, 1.0].
        sample_rate: Samples per second.

    Returns:
        PCM16 (int16 little-endian) bytes.
    """
    n_samples = int(sample_rate * duration_s)
    t = np.arange(n_samples, dtype=np.float32) / sample_rate
    signal = amplitude * np.sin(2 * np.pi * frequency_hz * t)
    pcm = (signal * 32767).astype(np.int16)
    return pcm.tobytes()


def _make_silence(duration_s: float, sample_rate: int = 16000) -> bytes:
    """Generate silent PCM16 audio (all zeros)."""
    n_samples = int(sample_rate * duration_s)
    return np.zeros(n_samples, dtype=np.int16).tobytes()


def _rms_of_bytes(audio_bytes: bytes) -> float:
    """Compute RMS of PCM16 audio bytes."""
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(samples ** 2)))


# ---------------------------------------------------------------------------
# NONE mode tests
# ---------------------------------------------------------------------------


class TestNoneMode:
    """NONE mode must be a pure passthrough."""

    def _make_suppressor(self) -> EchoSuppressor:
        cfg = EchoSuppressionConfig(mode=EchoSuppressionMode.NONE)
        return EchoSuppressor(cfg)

    def test_process_input_passthrough(self):
        """Input audio must be returned unchanged."""
        suppressor = self._make_suppressor()
        audio = _make_pcm16(440, 0.1)
        result = suppressor.process_input(audio)
        assert result == audio

    def test_should_process_vad_always_true(self):
        """VAD gate must always be open in NONE mode."""
        suppressor = self._make_suppressor()
        suppressor.notify_tts_start()
        suppressor.feed_output(_make_pcm16(440, 0.1))
        assert suppressor.should_process_vad() is True

    def test_feed_output_is_noop(self):
        """feed_output must not alter internal energy state."""
        suppressor = self._make_suppressor()
        suppressor.feed_output(_make_pcm16(440, 0.1))
        # Internal RMS should stay at zero (feed_output returns early)
        assert suppressor._output_rms == 0.0

    def test_passthrough_during_tts(self):
        """Even during active TTS, NONE mode does not modify audio."""
        suppressor = self._make_suppressor()
        audio = _make_pcm16(440, 0.1)
        suppressor.notify_tts_start()
        suppressor.feed_output(_make_pcm16(440, 0.1))
        result = suppressor.process_input(audio)
        assert result == audio
        assert suppressor.should_process_vad() is True

    def test_empty_audio_passthrough(self):
        """Empty bytes must be returned as-is."""
        suppressor = self._make_suppressor()
        assert suppressor.process_input(b"") == b""


# ---------------------------------------------------------------------------
# DUCKING mode tests
# ---------------------------------------------------------------------------


class TestDuckingMode:
    """DUCKING mode attenuates mic input while TTS is active."""

    def _make_suppressor(self, attenuation_db: float = -30.0,
                         release_ms: float = 200.0) -> EchoSuppressor:
        cfg = EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING,
            ducking_attenuation_db=attenuation_db,
            ducking_release_ms=release_ms,
        )
        return EchoSuppressor(cfg)

    def test_no_attenuation_when_idle(self):
        """When TTS is not active, audio must pass through unchanged."""
        suppressor = self._make_suppressor()
        audio = _make_pcm16(440, 0.1)
        result = suppressor.process_input(audio)
        assert result == audio

    def test_attenuation_during_tts(self):
        """During TTS, output RMS must be significantly reduced."""
        suppressor = self._make_suppressor(attenuation_db=-30.0)
        audio = _make_pcm16(440, 0.1, amplitude=0.8)
        rms_original = _rms_of_bytes(audio)

        suppressor.notify_tts_start()
        result = suppressor.process_input(audio)
        rms_ducked = _rms_of_bytes(result)

        # -30 dB => factor ~0.0316 => ducked should be ~3% of original
        assert rms_ducked < rms_original * 0.1
        assert rms_ducked > 0  # not completely zeroed

    def test_should_process_vad_always_true(self):
        """In ducking mode, VAD always runs (it sees attenuated signal)."""
        suppressor = self._make_suppressor()
        suppressor.notify_tts_start()
        assert suppressor.should_process_vad() is True
        suppressor.notify_tts_stop()
        assert suppressor.should_process_vad() is True

    def test_attenuation_during_release_period(self):
        """Ducking continues for release_ms after TTS stops."""
        suppressor = self._make_suppressor(release_ms=500.0)
        audio = _make_pcm16(440, 0.1, amplitude=0.8)
        rms_original = _rms_of_bytes(audio)

        suppressor.notify_tts_start()
        suppressor.notify_tts_stop()

        # Immediately after stop, should still be ducking (within release)
        result = suppressor.process_input(audio)
        rms_ducked = _rms_of_bytes(result)
        assert rms_ducked < rms_original * 0.1

    def test_restoration_after_release_period(self):
        """After the release period, audio must pass through unmodified."""
        suppressor = self._make_suppressor(release_ms=50.0)
        audio = _make_pcm16(440, 0.1, amplitude=0.8)

        suppressor.notify_tts_start()
        suppressor.notify_tts_stop()

        # Wait beyond release period
        time.sleep(0.08)  # 80ms > 50ms release

        result = suppressor.process_input(audio)
        assert result == audio

    def test_restoration_after_release_with_mocked_time(self):
        """Use mocked time to verify release without real sleep."""
        suppressor = self._make_suppressor(release_ms=200.0)
        audio = _make_pcm16(440, 0.1, amplitude=0.8)

        suppressor.notify_tts_start()
        # Manually set stop time far in the past
        suppressor._tts_active = False
        suppressor._tts_stop_time = time.monotonic() - 1.0  # 1s ago

        result = suppressor.process_input(audio)
        assert result == audio  # release period (200ms) has long passed

    def test_ducking_gain_calculation(self):
        """Verify the internal gain matches the dB specification."""
        suppressor = self._make_suppressor(attenuation_db=-20.0)
        expected_gain = 10 ** (-20.0 / 20.0)  # 0.1
        assert abs(suppressor._ducking_gain - expected_gain) < 1e-6

    def test_clipping_prevention(self):
        """Attenuated samples must stay within int16 range."""
        # Use a very mild attenuation to amplify edge-case awareness
        suppressor = self._make_suppressor(attenuation_db=-6.0)
        # Full-scale audio
        audio = _make_pcm16(440, 0.1, amplitude=1.0)
        suppressor.notify_tts_start()
        result = suppressor.process_input(audio)
        samples = np.frombuffer(result, dtype=np.int16)
        assert samples.min() >= -32768
        assert samples.max() <= 32767

    def test_empty_audio_during_ducking(self):
        """Empty bytes during active ducking must be returned as-is."""
        suppressor = self._make_suppressor()
        suppressor.notify_tts_start()
        assert suppressor.process_input(b"") == b""


# ---------------------------------------------------------------------------
# ENERGY_BASED mode tests
# ---------------------------------------------------------------------------


class TestEnergyBasedMode:
    """ENERGY_BASED mode gates VAD based on input vs output energy."""

    def _make_suppressor(self, barge_in_db: float = 6.0) -> EchoSuppressor:
        cfg = EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED,
            barge_in_energy_threshold_db=barge_in_db,
        )
        return EchoSuppressor(cfg)

    def test_suppresses_echo_when_input_quiet(self):
        """When mic input is quieter than echo, VAD should be gated."""
        suppressor = self._make_suppressor(barge_in_db=6.0)
        suppressor.notify_tts_start()

        # Feed loud TTS output
        loud_output = _make_pcm16(440, 0.1, amplitude=0.8)
        suppressor.feed_output(loud_output)

        # Process quiet mic input (echo-level, not user speech)
        quiet_input = _make_pcm16(440, 0.1, amplitude=0.05)
        suppressor.process_input(quiet_input)

        assert suppressor.should_process_vad() is False

    def test_allows_barge_in_when_input_loud(self):
        """When mic input significantly exceeds echo, VAD should open."""
        suppressor = self._make_suppressor(barge_in_db=6.0)
        suppressor.notify_tts_start()

        # Feed moderate TTS output
        output = _make_pcm16(440, 0.1, amplitude=0.1)
        suppressor.feed_output(output)

        # Process very loud mic input (user is speaking loudly)
        loud_input = _make_pcm16(440, 0.1, amplitude=0.9)
        suppressor.process_input(loud_input)

        assert suppressor.should_process_vad() is True

    def test_vad_open_when_tts_inactive(self):
        """When TTS is not active, VAD should always be open."""
        suppressor = self._make_suppressor()
        # Feed some output energy, then stop TTS
        suppressor.notify_tts_start()
        suppressor.feed_output(_make_pcm16(440, 0.1, amplitude=0.8))
        suppressor.notify_tts_stop()

        # Even with quiet input, VAD should be open (TTS is off)
        quiet_input = _make_pcm16(440, 0.1, amplitude=0.01)
        suppressor.process_input(quiet_input)
        assert suppressor.should_process_vad() is True

    def test_audio_passes_through_unmodified(self):
        """Energy mode does not modify audio, only gates VAD."""
        suppressor = self._make_suppressor()
        audio = _make_pcm16(440, 0.1)
        suppressor.notify_tts_start()
        suppressor.feed_output(_make_pcm16(440, 0.1, amplitude=0.5))
        result = suppressor.process_input(audio)
        assert result == audio

    def test_vad_open_when_no_output_energy(self):
        """When output RMS is near zero, VAD should be open."""
        suppressor = self._make_suppressor()
        suppressor.notify_tts_start()
        # Don't feed any output
        quiet_input = _make_pcm16(440, 0.1, amplitude=0.01)
        suppressor.process_input(quiet_input)
        assert suppressor.should_process_vad() is True

    def test_threshold_boundary(self):
        """Test behavior right at the barge-in threshold boundary."""
        suppressor = self._make_suppressor(barge_in_db=6.0)
        # 6 dB => linear ratio ~2.0
        threshold_linear = 10 ** (6.0 / 20.0)  # ~1.9953

        suppressor.notify_tts_start()

        # Feed output with known amplitude
        output_amplitude = 0.1
        output = _make_pcm16(440, 0.1, amplitude=output_amplitude)
        suppressor.feed_output(output)

        # Input just below threshold (should suppress)
        below_amplitude = output_amplitude * (threshold_linear * 0.5)
        below_input = _make_pcm16(440, 0.1, amplitude=below_amplitude)
        suppressor.process_input(below_input)
        assert suppressor.should_process_vad() is False

        # Input above threshold (should allow)
        above_amplitude = output_amplitude * (threshold_linear * 1.5)
        # Clamp to avoid overflow
        above_amplitude = min(above_amplitude, 0.99)
        above_input = _make_pcm16(440, 0.1, amplitude=above_amplitude)
        suppressor.process_input(above_input)
        assert suppressor.should_process_vad() is True

    def test_empty_audio_during_energy_mode(self):
        """Empty bytes during active energy mode must be handled."""
        suppressor = self._make_suppressor()
        suppressor.notify_tts_start()
        result = suppressor.process_input(b"")
        assert result == b""


# ---------------------------------------------------------------------------
# TTS lifecycle tests
# ---------------------------------------------------------------------------


class TestTTSLifecycle:
    """Tests for notify_tts_start/stop lifecycle management."""

    def test_start_sets_active(self):
        """notify_tts_start must set TTS active flag."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        assert suppressor._tts_active is False
        suppressor.notify_tts_start()
        assert suppressor._tts_active is True

    def test_stop_clears_active(self):
        """notify_tts_stop must clear TTS active flag."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        suppressor.notify_tts_start()
        suppressor.notify_tts_stop()
        assert suppressor._tts_active is False

    def test_stop_records_time(self):
        """notify_tts_stop must record the stop timestamp."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        suppressor.notify_tts_start()
        before = time.monotonic()
        suppressor.notify_tts_stop()
        after = time.monotonic()
        assert before <= suppressor._tts_stop_time <= after

    def test_start_resets_stop_time(self):
        """notify_tts_start must clear any previous stop time."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        suppressor.notify_tts_start()
        suppressor.notify_tts_stop()
        assert suppressor._tts_stop_time > 0

        suppressor.notify_tts_start()
        assert suppressor._tts_stop_time == 0.0

    def test_multiple_start_stop_cycles(self):
        """Multiple start/stop cycles must work correctly."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        audio = _make_pcm16(440, 0.05, amplitude=0.8)
        rms_original = _rms_of_bytes(audio)

        for _ in range(5):
            suppressor.notify_tts_start()
            result = suppressor.process_input(audio)
            rms_ducked = _rms_of_bytes(result)
            assert rms_ducked < rms_original * 0.1

            suppressor.notify_tts_stop()

        # After all cycles, with enough time passed, should be passthrough
        suppressor._tts_stop_time = time.monotonic() - 10.0
        result = suppressor.process_input(audio)
        assert result == audio

    def test_energy_mode_lifecycle(self):
        """TTS lifecycle in energy mode controls VAD gating."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED,
            barge_in_energy_threshold_db=6.0,
        ))

        loud_output = _make_pcm16(440, 0.1, amplitude=0.8)
        quiet_input = _make_pcm16(440, 0.1, amplitude=0.01)

        # Before TTS: VAD open
        suppressor.process_input(quiet_input)
        assert suppressor.should_process_vad() is True

        # During TTS with quiet input: VAD gated
        suppressor.notify_tts_start()
        suppressor.feed_output(loud_output)
        suppressor.process_input(quiet_input)
        assert suppressor.should_process_vad() is False

        # After TTS stops: VAD open again
        suppressor.notify_tts_stop()
        suppressor.process_input(quiet_input)
        assert suppressor.should_process_vad() is True


# ---------------------------------------------------------------------------
# Reset tests
# ---------------------------------------------------------------------------


class TestReset:
    """Tests for the reset() method."""

    def test_reset_clears_tts_active(self):
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        suppressor.notify_tts_start()
        suppressor.reset()
        assert suppressor._tts_active is False

    def test_reset_clears_stop_time(self):
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        suppressor.notify_tts_start()
        suppressor.notify_tts_stop()
        suppressor.reset()
        assert suppressor._tts_stop_time == 0.0

    def test_reset_clears_output_rms(self):
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED
        ))
        suppressor.feed_output(_make_pcm16(440, 0.1, amplitude=0.8))
        assert suppressor._output_rms > 0
        suppressor.reset()
        assert suppressor._output_rms == 0.0

    def test_reset_restores_vad_gate(self):
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED,
            barge_in_energy_threshold_db=6.0,
        ))
        suppressor.notify_tts_start()
        suppressor.feed_output(_make_pcm16(440, 0.1, amplitude=0.8))
        suppressor.process_input(_make_pcm16(440, 0.1, amplitude=0.01))
        assert suppressor.should_process_vad() is False

        suppressor.reset()
        assert suppressor.should_process_vad() is True

    def test_reset_allows_normal_operation_after(self):
        """After reset, suppressor should behave as freshly constructed."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        audio = _make_pcm16(440, 0.1)

        suppressor.notify_tts_start()
        suppressor.reset()

        # Should be passthrough (not ducking) after reset
        result = suppressor.process_input(audio)
        assert result == audio


# ---------------------------------------------------------------------------
# feed_output tests
# ---------------------------------------------------------------------------


class TestFeedOutput:
    """Tests for the feed_output() method."""

    def test_tracks_energy_in_energy_mode(self):
        """feed_output must update output RMS in energy-based mode."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED
        ))
        assert suppressor._output_rms == 0.0

        audio = _make_pcm16(440, 0.1, amplitude=0.5)
        suppressor.feed_output(audio)
        assert suppressor._output_rms > 0.0

    def test_energy_increases_with_louder_output(self):
        """Louder output should result in higher tracked energy."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED
        ))

        quiet = _make_pcm16(440, 0.1, amplitude=0.1)
        suppressor.feed_output(quiet)
        rms_quiet = suppressor._output_rms

        # Reset and feed loud
        suppressor.reset()
        loud = _make_pcm16(440, 0.1, amplitude=0.8)
        suppressor.feed_output(loud)
        rms_loud = suppressor._output_rms

        assert rms_loud > rms_quiet

    def test_energy_decays_over_multiple_feeds(self):
        """Output RMS should decay when fed silence after loud audio."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED
        ))

        loud = _make_pcm16(440, 0.1, amplitude=0.8)
        suppressor.feed_output(loud)
        rms_after_loud = suppressor._output_rms

        # Feed many silence chunks to trigger decay
        silence = _make_silence(0.1)
        for _ in range(20):
            suppressor.feed_output(silence)
        rms_after_decay = suppressor._output_rms

        assert rms_after_decay < rms_after_loud

    def test_noop_in_none_mode(self):
        """feed_output must not change state in NONE mode."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.NONE
        ))
        suppressor.feed_output(_make_pcm16(440, 0.1, amplitude=0.8))
        assert suppressor._output_rms == 0.0

    def test_empty_audio_is_noop(self):
        """Empty bytes must not change output RMS."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED
        ))
        suppressor.feed_output(b"")
        assert suppressor._output_rms == 0.0

    def test_feed_output_in_ducking_mode(self):
        """Ducking mode should accept feed_output without error."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        # Should not raise
        suppressor.feed_output(_make_pcm16(440, 0.1, amplitude=0.5))


# ---------------------------------------------------------------------------
# Empty/edge-case audio tests
# ---------------------------------------------------------------------------


class TestEmptyAudio:
    """Edge cases with empty or minimal audio."""

    @pytest.mark.parametrize("mode", list(EchoSuppressionMode))
    def test_empty_process_input(self, mode: EchoSuppressionMode):
        """Empty bytes must be handled gracefully in all modes."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(mode=mode))
        suppressor.notify_tts_start()
        result = suppressor.process_input(b"")
        assert result == b""

    @pytest.mark.parametrize("mode", list(EchoSuppressionMode))
    def test_empty_feed_output(self, mode: EchoSuppressionMode):
        """Empty bytes in feed_output must not raise."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(mode=mode))
        suppressor.feed_output(b"")  # Should not raise

    def test_single_sample_input(self):
        """A single int16 sample (2 bytes) must be processable."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.DUCKING
        ))
        single_sample = struct.pack("<h", 1000)
        suppressor.notify_tts_start()
        result = suppressor.process_input(single_sample)
        assert len(result) == 2
        value = struct.unpack("<h", result)[0]
        assert abs(value) < abs(1000)  # Should be attenuated

    def test_single_sample_energy_mode(self):
        """A single int16 sample must be processable in energy mode."""
        suppressor = EchoSuppressor(EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED
        ))
        single_sample = struct.pack("<h", 1000)
        suppressor.notify_tts_start()
        result = suppressor.process_input(single_sample)
        assert result == single_sample  # Energy mode passes through


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestEchoSuppressionConfig:
    """Tests for EchoSuppressionConfig defaults and customization."""

    def test_default_mode(self):
        cfg = EchoSuppressionConfig()
        assert cfg.mode == EchoSuppressionMode.DUCKING

    def test_default_values(self):
        cfg = EchoSuppressionConfig()
        assert cfg.ducking_attenuation_db == -30.0
        assert cfg.ducking_release_ms == 200.0
        assert cfg.barge_in_energy_threshold_db == 6.0
        assert cfg.sample_rate == 16000

    def test_custom_values(self):
        cfg = EchoSuppressionConfig(
            mode=EchoSuppressionMode.ENERGY_BASED,
            ducking_attenuation_db=-20.0,
            ducking_release_ms=300.0,
            barge_in_energy_threshold_db=10.0,
            sample_rate=48000,
        )
        assert cfg.mode == EchoSuppressionMode.ENERGY_BASED
        assert cfg.ducking_attenuation_db == -20.0
        assert cfg.ducking_release_ms == 300.0
        assert cfg.barge_in_energy_threshold_db == 10.0
        assert cfg.sample_rate == 48000

    def test_suppressor_default_config(self):
        """EchoSuppressor with None config should use defaults."""
        suppressor = EchoSuppressor(None)
        assert suppressor._config.mode == EchoSuppressionMode.DUCKING


# ---------------------------------------------------------------------------
# EchoSuppressionMode enum tests
# ---------------------------------------------------------------------------


class TestEchoSuppressionMode:
    """Tests for the mode enum."""

    def test_enum_values(self):
        assert EchoSuppressionMode.NONE.value == "none"
        assert EchoSuppressionMode.DUCKING.value == "ducking"
        assert EchoSuppressionMode.ENERGY_BASED.value == "energy_based"

    def test_all_modes_count(self):
        assert len(EchoSuppressionMode) == 3
