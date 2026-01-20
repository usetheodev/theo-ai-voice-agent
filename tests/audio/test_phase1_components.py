"""
Unit Tests for Phase 1 Audio Quality Components

Tests:
- RNNoise Filter (noise reduction)
- Silero VAD (ML-based voice detection)
- SOXR Resampler (high-quality resampling)

Run:
    pytest tests/audio/test_phase1_components.py -v
"""

import pytest
import numpy as np
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


# ============================================
# RNNoise Filter Tests
# ============================================

@pytest.mark.asyncio
async def test_rnnoise_filter_initialization():
    """Test RNNoise filter initialization"""
    try:
        from audio.filters import RNNoiseFilter

        filter = RNNoiseFilter(resampler_quality="QQ")
        await filter.start(sample_rate=8000)

        assert filter._sample_rate == 8000
        assert filter._filtering is True

        await filter.stop()

    except ImportError as e:
        pytest.skip(f"RNNoise not available: {e}")


@pytest.mark.asyncio
async def test_rnnoise_filter_bypass_when_disabled():
    """Test RNNoise filter bypasses audio when disabled"""
    try:
        from audio.filters import RNNoiseFilter

        filter = RNNoiseFilter()
        filter.set_enabled(False)

        # Generate test audio
        audio_in = np.random.randint(-1000, 1000, 1600, dtype=np.int16).tobytes()

        # Filter should bypass (return same audio)
        audio_out = await filter.filter(audio_in)

        assert audio_out == audio_in

    except ImportError:
        pytest.skip("RNNoise not available")


@pytest.mark.asyncio
async def test_rnnoise_filter_stats():
    """Test RNNoise filter statistics"""
    try:
        from audio.filters import RNNoiseFilter

        filter = RNNoiseFilter()
        await filter.start(sample_rate=8000)

        stats = filter.get_stats()

        assert 'enabled' in stats
        assert 'ready' in stats
        assert 'total_frames' in stats
        assert stats['sample_rate'] == 8000

        await filter.stop()

    except ImportError:
        pytest.skip("RNNoise not available")


# ============================================
# Silero VAD Tests
# ============================================

def test_silero_vad_initialization():
    """Test Silero VAD initialization"""
    try:
        from audio.vad_silero import SileroVAD

        vad = SileroVAD(
            sample_rate=8000,
            confidence_threshold=0.5
        )

        assert vad.sample_rate == 8000
        assert vad.confidence_threshold == 0.5
        assert vad.frame_size == 256  # 256 samples @ 8kHz
        assert vad.state.value == "silence"

    except ImportError as e:
        pytest.skip(f"Silero VAD not available: {e}")


def test_silero_vad_invalid_sample_rate():
    """Test Silero VAD rejects invalid sample rate"""
    try:
        from audio.vad_silero import SileroVAD

        with pytest.raises(ValueError, match="Sample rate must be 8000 or 16000"):
            SileroVAD(sample_rate=48000)

    except ImportError:
        pytest.skip("Silero VAD not available")


def test_silero_vad_process_silence():
    """Test Silero VAD processes silence correctly"""
    try:
        from audio.vad_silero import SileroVAD

        vad = SileroVAD(sample_rate=8000)

        if vad.model is None:
            pytest.skip("Silero model not loaded")

        # Generate silence (256 samples = 32ms @ 8kHz)
        silence = np.zeros(256, dtype=np.int16).tobytes()

        # Process multiple frames
        for i in range(10):
            is_speech = vad.process_frame(silence)

        assert vad.is_speech() is False
        assert vad.state.value == "silence"

    except ImportError:
        pytest.skip("Silero VAD not available")


def test_silero_vad_process_speech():
    """Test Silero VAD processes speech correctly"""
    try:
        from audio.vad_silero import SileroVAD

        vad = SileroVAD(
            sample_rate=8000,
            confidence_threshold=0.5,
            start_frames=2  # Quick start for testing
        )

        if vad.model is None:
            pytest.skip("Silero model not loaded")

        # Generate speech-like signal (440 Hz tone)
        frame_size = 256
        t = np.linspace(0, 0.032, frame_size)  # 32ms
        speech = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16).tobytes()

        # Process multiple speech frames
        for i in range(5):
            is_speech = vad.process_frame(speech)

        # After 5 frames, should be in speech state
        assert vad.is_speech() is True

    except ImportError:
        pytest.skip("Silero VAD not available")


def test_silero_vad_stats():
    """Test Silero VAD statistics"""
    try:
        from audio.vad_silero import SileroVAD

        vad = SileroVAD(sample_rate=8000)

        stats = vad.get_stats()

        assert stats['model'] == 'silero-onnx'
        assert stats['sample_rate'] == 8000
        assert stats['threshold'] == 0.5
        assert 'total_frames' in stats
        assert 'speech_segments' in stats

    except ImportError:
        pytest.skip("Silero VAD not available")


def test_silero_vad_reset():
    """Test Silero VAD reset functionality"""
    try:
        from audio.vad_silero import SileroVAD

        vad = SileroVAD(sample_rate=8000)

        if vad.model is None:
            pytest.skip("Silero model not loaded")

        # Process some audio
        audio = np.random.randint(-1000, 1000, 256, dtype=np.int16).tobytes()
        vad.process_frame(audio)

        # Reset
        vad.reset()

        assert vad.state.value == "silence"
        assert vad.starting_count == 0
        assert vad.stopping_count == 0
        assert len(vad.buffer) == 0

    except ImportError:
        pytest.skip("Silero VAD not available")


# ============================================
# SOXR Resampler Tests
# ============================================

@pytest.mark.asyncio
async def test_soxr_resampler_initialization():
    """Test SOXR resampler initialization"""
    try:
        from audio.resamplers import SOXRStreamResampler

        resampler = SOXRStreamResampler(quality="VHQ")

        assert resampler.quality == "VHQ"
        assert resampler._soxr_stream is None  # Not initialized until first use

    except ImportError as e:
        pytest.skip(f"SOXR not available: {e}")


@pytest.mark.asyncio
async def test_soxr_resampler_no_op():
    """Test SOXR resampler returns same audio when rates match"""
    try:
        from audio.resamplers import SOXRStreamResampler

        resampler = SOXRStreamResampler()

        audio_in = np.random.randint(-1000, 1000, 1600, dtype=np.int16).tobytes()

        # Same sample rate → no-op
        audio_out = await resampler.resample(audio_in, in_rate=8000, out_rate=8000)

        assert audio_out == audio_in

    except ImportError:
        pytest.skip("SOXR not available")


@pytest.mark.asyncio
async def test_soxr_resampler_8k_to_16k():
    """Test SOXR resampler 8kHz → 16kHz"""
    try:
        from audio.resamplers import SOXRStreamResampler

        resampler = SOXRStreamResampler(quality="VHQ")

        # Generate 1 second @ 8kHz
        num_samples_in = 8000
        audio_in = np.random.randint(-1000, 1000, num_samples_in, dtype=np.int16).tobytes()

        # Resample to 16kHz
        audio_out = await resampler.resample(audio_in, in_rate=8000, out_rate=16000)

        audio_out_array = np.frombuffer(audio_out, dtype=np.int16)

        # Expected: 16000 samples ± small tolerance (filter delay)
        expected_samples = 16000
        tolerance = 100

        assert abs(len(audio_out_array) - expected_samples) <= tolerance

    except ImportError:
        pytest.skip("SOXR not available")


@pytest.mark.asyncio
async def test_soxr_resampler_16k_to_8k():
    """Test SOXR resampler 16kHz → 8kHz (downsampling)"""
    try:
        from audio.resamplers import SOXRStreamResampler

        resampler = SOXRStreamResampler(quality="VHQ")

        # Generate 1 second @ 16kHz
        num_samples_in = 16000
        audio_in = np.random.randint(-1000, 1000, num_samples_in, dtype=np.int16).tobytes()

        # Resample to 8kHz
        audio_out = await resampler.resample(audio_in, in_rate=16000, out_rate=8000)

        audio_out_array = np.frombuffer(audio_out, dtype=np.int16)

        # Expected: 8000 samples ± small tolerance
        expected_samples = 8000
        tolerance = 100

        assert abs(len(audio_out_array) - expected_samples) <= tolerance

    except ImportError:
        pytest.skip("SOXR not available")


@pytest.mark.asyncio
async def test_soxr_resampler_empty_audio():
    """Test SOXR resampler handles empty audio"""
    try:
        from audio.resamplers import SOXRStreamResampler

        resampler = SOXRStreamResampler()

        audio_out = await resampler.resample(b"", in_rate=8000, out_rate=16000)

        assert audio_out == b""

    except ImportError:
        pytest.skip("SOXR not available")


@pytest.mark.asyncio
async def test_soxr_resampler_stats():
    """Test SOXR resampler statistics"""
    try:
        from audio.resamplers import SOXRStreamResampler

        resampler = SOXRStreamResampler(quality="HQ")

        stats = resampler.get_stats()

        assert stats['quality'] == "HQ"
        assert 'available' in stats
        assert 'initialized' in stats

    except ImportError:
        pytest.skip("SOXR not available")


@pytest.mark.asyncio
async def test_soxr_resampler_reset():
    """Test SOXR resampler reset functionality"""
    try:
        from audio.resamplers import SOXRStreamResampler

        resampler = SOXRStreamResampler()

        # Initialize by resampling
        audio = np.random.randint(-1000, 1000, 1600, dtype=np.int16).tobytes()
        await resampler.resample(audio, in_rate=8000, out_rate=16000)

        # Reset
        resampler.reset()

        # Should still work after reset
        audio_out = await resampler.resample(audio, in_rate=8000, out_rate=16000)
        assert len(audio_out) > 0

    except ImportError:
        pytest.skip("SOXR not available")


# ============================================
# Integration Test
# ============================================

@pytest.mark.asyncio
async def test_phase1_pipeline_integration():
    """Test all Phase 1 components working together"""
    try:
        from audio.filters import RNNoiseFilter
        from audio.vad_silero import SileroVAD
        from audio.resamplers import SOXRStreamResampler

        # Initialize all components
        noise_filter = RNNoiseFilter(resampler_quality="QQ")
        await noise_filter.start(sample_rate=8000)

        silero_vad = SileroVAD(sample_rate=8000)

        soxr_resampler = SOXRStreamResampler(quality="VHQ")

        # Generate test audio (440 Hz tone @ 8kHz, 1 second)
        sample_rate = 8000
        duration = 1.0
        num_samples = int(sample_rate * duration)
        t = np.linspace(0, duration, num_samples)
        audio_8khz = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16).tobytes()

        # Step 1: Noise reduction
        audio_filtered = await noise_filter.filter(audio_8khz)

        if len(audio_filtered) == 0:
            # Still buffering
            audio_filtered = audio_8khz

        # Step 2: VAD detection
        # Process in chunks (256 samples = 32ms @ 8kHz)
        frame_size = 256
        for i in range(0, len(audio_filtered), frame_size * 2):
            frame = audio_filtered[i:i + frame_size * 2]
            if len(frame) == frame_size * 2:
                silero_vad.process_frame(frame)

        # Step 3: Resample to 16kHz
        audio_16khz = await soxr_resampler.resample(
            audio_filtered,
            in_rate=8000,
            out_rate=16000
        )

        # Verify output
        assert len(audio_16khz) > 0
        audio_16khz_array = np.frombuffer(audio_16khz, dtype=np.int16)

        # Should be approximately 2x samples (8kHz → 16kHz)
        expected_ratio = 2.0
        actual_ratio = len(audio_16khz_array) / (len(audio_filtered) / 2)

        assert abs(actual_ratio - expected_ratio) < 0.1  # 10% tolerance

        # Cleanup
        await noise_filter.stop()

        print("\n✅ Phase 1 integration test passed!")
        print(f"   - Input: {len(audio_8khz)} bytes @ 8kHz")
        print(f"   - Filtered: {len(audio_filtered)} bytes")
        print(f"   - Output: {len(audio_16khz)} bytes @ 16kHz")
        print(f"   - VAD detected {silero_vad.total_frames} frames")

    except ImportError as e:
        pytest.skip(f"Phase 1 components not available: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
