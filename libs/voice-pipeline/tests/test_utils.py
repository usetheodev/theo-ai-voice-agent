"""Tests for utility functions."""

import pytest
import math
from voice_pipeline.utils.audio import (
    pcm16_to_float,
    float_to_pcm16,
    calculate_rms,
    calculate_db,
    resample_audio,
)
from voice_pipeline.utils.timing import Timer, measure_latency


class TestAudioUtils:
    """Tests for audio utilities."""

    def test_pcm16_to_float(self):
        """Test PCM16 to float conversion."""
        # Max positive value
        audio = b"\xff\x7f"  # 32767 in little-endian
        result = pcm16_to_float(audio)
        assert len(result) == 1
        assert abs(result[0] - 1.0) < 0.001

        # Zero
        audio = b"\x00\x00"
        result = pcm16_to_float(audio)
        assert result[0] == 0.0

        # Max negative value
        audio = b"\x00\x80"  # -32768 in little-endian
        result = pcm16_to_float(audio)
        assert abs(result[0] - (-1.0)) < 0.001

    def test_float_to_pcm16(self):
        """Test float to PCM16 conversion."""
        # Max positive
        samples = [1.0]
        result = float_to_pcm16(samples)
        assert result == b"\xff\x7f"

        # Zero
        samples = [0.0]
        result = float_to_pcm16(samples)
        assert result == b"\x00\x00"

    def test_roundtrip_conversion(self):
        """Test PCM16 → float → PCM16 roundtrip."""
        original = b"\x00\x40\xff\x7f\x00\x80"  # Some values
        floats = pcm16_to_float(original)
        result = float_to_pcm16(floats)

        # Should be approximately the same (may have small differences)
        assert len(result) == len(original)

    def test_calculate_rms_silence(self):
        """Test RMS of silence."""
        silence = b"\x00\x00" * 100
        rms = calculate_rms(silence)
        assert rms == 0.0

    def test_calculate_rms_signal(self):
        """Test RMS of a signal."""
        # Full-scale sine would have RMS of ~0.707
        audio = float_to_pcm16([0.5] * 100)
        rms = calculate_rms(audio)
        assert 0.4 < rms < 0.6

    def test_calculate_db_silence(self):
        """Test dB of silence."""
        silence = b"\x00\x00" * 100
        db = calculate_db(silence)
        assert db == float('-inf')

    def test_calculate_db_signal(self):
        """Test dB of a signal."""
        # Half amplitude should be ~-6 dB
        audio = float_to_pcm16([0.5] * 100)
        db = calculate_db(audio)
        assert -10 < db < 0

    def test_resample_same_rate(self):
        """Test resampling with same rate returns same data."""
        audio = b"\x01\x02\x03\x04"
        result = resample_audio(audio, 16000, 16000)
        assert result == audio

    def test_resample_downsample(self):
        """Test downsampling."""
        # 4 samples at 16000 → 2 samples at 8000
        audio = float_to_pcm16([0.0, 0.5, 1.0, 0.5])
        result = resample_audio(audio, 16000, 8000)
        # Should have fewer samples
        assert len(result) < len(audio)

    def test_resample_upsample(self):
        """Test upsampling."""
        # 2 samples at 8000 → 4 samples at 16000
        audio = float_to_pcm16([0.0, 1.0])
        result = resample_audio(audio, 8000, 16000)
        # Should have more samples
        assert len(result) > len(audio)


class TestTimer:
    """Tests for Timer utility."""

    def test_basic_timing(self):
        """Test basic timer usage."""
        timer = Timer()
        timer.start()

        # Do something
        import time
        time.sleep(0.01)

        elapsed = timer.stop()
        assert elapsed >= 0.01
        assert timer.elapsed_ms >= 10

    def test_checkpoint(self):
        """Test checkpoint recording."""
        timer = Timer().start()

        import time
        time.sleep(0.01)
        timer.checkpoint("first")

        time.sleep(0.01)
        timer.checkpoint("second")

        first = timer.get_checkpoint("first")
        second = timer.get_checkpoint("second")

        assert first is not None
        assert second is not None
        assert second > first

    def test_checkpoint_ms(self):
        """Test checkpoint in milliseconds."""
        timer = Timer().start()

        import time
        time.sleep(0.01)
        timer.checkpoint("test")

        ms = timer.get_checkpoint_ms("test")
        assert ms is not None
        assert ms >= 10

    def test_elapsed_before_start(self):
        """Test elapsed before starting."""
        timer = Timer()
        assert timer.elapsed == 0.0

    def test_checkpoint_before_start(self):
        """Test checkpoint before starting raises error."""
        timer = Timer()
        with pytest.raises(RuntimeError):
            timer.checkpoint("test")


class TestMeasureLatency:
    """Tests for measure_latency context manager."""

    def test_measure_latency(self):
        """Test latency measurement."""
        recorded_ms = [0]

        def callback(ms):
            recorded_ms[0] = ms

        with measure_latency(callback):
            import time
            time.sleep(0.01)

        assert recorded_ms[0] >= 10

    def test_measure_latency_yields_timer(self):
        """Test that context manager yields timer."""
        with measure_latency() as timer:
            import time
            time.sleep(0.01)
            timer.checkpoint("middle")

        assert timer.elapsed_ms >= 10
        assert timer.get_checkpoint("middle") is not None
