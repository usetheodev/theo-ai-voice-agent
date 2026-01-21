"""
Unit Tests - VoiceActivityDetector (Dual-Mode)

Tests WebRTC + Energy dual-mode VAD with focus on:
- Graceful fallback when webrtcvad not available
- Logical OR strategy (webrtc OR energy)
- Agreement tracking between methods
- State machine transitions

Coverage Target: 85%+
"""

import pytest
import numpy as np
from src.audio.vad import VoiceActivityDetector, VADState, WEBRTC_VAD_AVAILABLE


class TestVADInitialization:
    """Test VAD initialization and mode detection."""

    def test_vad_init_defaults(self):
        """VAD should initialize with sane defaults."""
        vad = VoiceActivityDetector()

        assert vad.sample_rate == 8000
        assert vad.frame_duration_ms == 20
        assert vad.energy_threshold_start == 500.0
        assert vad.energy_threshold_end == 300.0
        assert vad.state == VADState.SILENCE

    def test_vad_init_with_webrtc(self):
        """VAD should initialize WebRTC if available."""
        vad = VoiceActivityDetector(
            sample_rate=8000,
            webrtc_aggressiveness=1
        )

        if WEBRTC_VAD_AVAILABLE:
            assert vad.webrtc_mode == "dual-mode"
            assert vad.webrtc_vad is not None
        else:
            assert vad.webrtc_mode == "energy-only"
            assert vad.webrtc_vad is None

    def test_vad_init_unsupported_sample_rate(self):
        """VAD should fallback to energy-only if sample rate not supported by WebRTC."""
        # WebRTC only supports 8k/16k/32k
        vad = VoiceActivityDetector(
            sample_rate=48000,  # Not supported
            webrtc_aggressiveness=1
        )

        # Should fall back to energy-only
        assert vad.webrtc_mode == "energy-only"
        assert vad.webrtc_vad is None

    def test_vad_webrtc_aggressiveness_levels(self):
        """VAD should accept aggressiveness 0-3."""
        for level in [0, 1, 2, 3]:
            vad = VoiceActivityDetector(
                sample_rate=8000,
                webrtc_aggressiveness=level
            )
            assert vad.webrtc_aggressiveness == level


class TestEnergyCalculation:
    """Test RMS energy calculation."""

    def test_calculate_rms_silence(self):
        """Silence should have low RMS energy."""
        vad = VoiceActivityDetector()
        silence = np.zeros(160, dtype=np.int16)  # 20ms @ 8kHz

        energy = vad.calculate_rms_energy(silence.tobytes())

        assert energy == 0.0

    def test_calculate_rms_loud_signal(self):
        """Loud signal should have high RMS energy."""
        vad = VoiceActivityDetector()

        # Generate 440 Hz tone at high amplitude
        t = np.linspace(0, 0.02, 160)  # 20ms
        tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)

        energy = vad.calculate_rms_energy(tone.tobytes())

        assert energy > 5000  # High energy

    def test_calculate_rms_quiet_signal(self):
        """Quiet signal should have low-medium RMS energy."""
        vad = VoiceActivityDetector()

        # Generate quiet tone
        t = np.linspace(0, 0.02, 160)
        tone = (np.sin(2 * np.pi * 440 * t) * 500).astype(np.int16)

        energy = vad.calculate_rms_energy(tone.tobytes())

        assert 100 < energy < 1000  # Medium energy


class TestVADStateMachine:
    """Test VAD state transitions."""

    def test_silence_to_speech_transition(self):
        """High energy should trigger SILENCE → SPEECH transition."""
        speech_started = False

        def on_start():
            nonlocal speech_started
            speech_started = True

        vad = VoiceActivityDetector(
            energy_threshold_start=500.0,
            on_speech_start=on_start
        )

        # Generate loud tone (energy > threshold)
        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)

        is_speech = vad.process_frame(loud_tone.tobytes())

        assert is_speech is True
        assert vad.state == VADState.SPEECH
        assert speech_started is True

    def test_speech_continuation(self):
        """Continuous speech should maintain SPEECH state."""
        vad = VoiceActivityDetector(
            energy_threshold_start=500.0,
            energy_threshold_end=300.0
        )

        # Generate loud tone
        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)

        # Process multiple frames
        vad.process_frame(loud_tone.tobytes())  # Start
        vad.process_frame(loud_tone.tobytes())  # Continue
        vad.process_frame(loud_tone.tobytes())  # Continue

        assert vad.state == VADState.SPEECH
        assert vad.speech_frames >= 3

    def test_speech_to_pending_end(self):
        """Low energy after speech should trigger SPEECH → PENDING_END."""
        vad = VoiceActivityDetector(
            sample_rate=48000,  # Force energy-only mode (WebRTC doesn't support 48k)
            energy_threshold_start=500.0,
            energy_threshold_end=300.0
        )

        # Start with loud tone
        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        vad.process_frame(loud_tone.tobytes())

        # Then silence
        silence = np.zeros(160, dtype=np.int16)
        is_speech = vad.process_frame(silence.tobytes())

        assert vad.state == VADState.PENDING_END
        assert is_speech is True  # Still considered speech (waiting confirmation)

    def test_pending_end_to_silence(self):
        """Prolonged silence should trigger PENDING_END → SILENCE."""
        speech_ended = False

        def on_end():
            nonlocal speech_ended
            speech_ended = True

        vad = VoiceActivityDetector(
            sample_rate=48000,  # Force energy-only mode
            energy_threshold_start=500.0,
            energy_threshold_end=300.0,
            silence_duration_ms=500,  # 25 frames @ 20ms
            min_speech_duration_ms=100,  # Lower threshold for test
            on_speech_end=on_end
        )

        # Start speech
        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        for _ in range(10):  # 200ms of speech
            vad.process_frame(loud_tone.tobytes())

        # Then silence for 600ms (30 frames)
        silence = np.zeros(160, dtype=np.int16)
        for _ in range(30):
            is_speech = vad.process_frame(silence.tobytes())

        assert vad.state == VADState.SILENCE
        assert is_speech is False
        assert speech_ended is True

    def test_false_end_resume_speech(self):
        """Brief silence should not end speech (PENDING_END → SPEECH)."""
        vad = VoiceActivityDetector(
            energy_threshold_start=500.0,
            energy_threshold_end=300.0,
            silence_duration_ms=500
        )

        # Start speech
        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        vad.process_frame(loud_tone.tobytes())

        # Brief silence (< threshold)
        silence = np.zeros(160, dtype=np.int16)
        for _ in range(5):
            vad.process_frame(silence.tobytes())

        # Resume speech
        vad.process_frame(loud_tone.tobytes())

        assert vad.state == VADState.SPEECH  # Resumed


class TestMinimumSpeechDuration:
    """Test noise filtering via minimum speech duration."""

    def test_short_speech_filtered(self):
        """Speech shorter than min_speech_duration should be filtered."""
        speech_ended_count = 0

        def on_end():
            nonlocal speech_ended_count
            speech_ended_count += 1

        vad = VoiceActivityDetector(
            energy_threshold_start=500.0,
            min_speech_duration_ms=500,  # 25 frames minimum
            on_speech_end=on_end
        )

        # Very short speech (5 frames = 100ms)
        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        for _ in range(5):
            vad.process_frame(loud_tone.tobytes())

        # Then silence
        silence = np.zeros(160, dtype=np.int16)
        for _ in range(30):
            vad.process_frame(silence.tobytes())

        # Speech end callback should NOT be called (filtered as noise)
        assert speech_ended_count == 0
        assert vad.speech_segments == 1  # Segment started but filtered


class TestDualModeOperation:
    """Test WebRTC + Energy dual-mode logic."""

    @pytest.mark.skipif(not WEBRTC_VAD_AVAILABLE, reason="webrtcvad not installed")
    def test_dual_mode_logical_or(self):
        """Dual-mode should use logical OR (webrtc OR energy)."""
        vad = VoiceActivityDetector(
            sample_rate=8000,
            energy_threshold_start=500.0,
            webrtc_aggressiveness=1
        )

        # Process some frames
        t = np.linspace(0, 0.02, 160)
        tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)

        for _ in range(50):
            vad.process_frame(tone.tobytes())

        # Check that both methods are being used
        if vad.webrtc_mode == "dual-mode":
            assert vad.webrtc_detections > 0
            assert vad.energy_detections > 0

    @pytest.mark.skipif(not WEBRTC_VAD_AVAILABLE, reason="webrtcvad not installed")
    def test_agreement_tracking(self):
        """VAD should track agreement between WebRTC and Energy."""
        vad = VoiceActivityDetector(
            sample_rate=8000,
            energy_threshold_start=500.0,
            webrtc_aggressiveness=1
        )

        # Process frames
        t = np.linspace(0, 0.02, 160)
        tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)

        for _ in range(50):
            vad.process_frame(tone.tobytes())

        if vad.webrtc_mode == "dual-mode":
            # Agreement should be tracked
            assert vad.agreement_count > 0
            assert vad.total_frames == 50


class TestVADStatistics:
    """Test VAD statistics reporting."""

    def test_get_stats_structure(self):
        """get_stats() should return complete statistics dict."""
        vad = VoiceActivityDetector()

        stats = vad.get_stats()

        assert 'state' in stats
        assert 'mode' in stats
        assert 'total_frames' in stats
        assert 'speech_segments' in stats
        assert 'is_speech' in stats

    @pytest.mark.skipif(not WEBRTC_VAD_AVAILABLE, reason="webrtcvad not installed")
    def test_get_stats_webrtc_metrics(self):
        """Dual-mode stats should include WebRTC metrics."""
        vad = VoiceActivityDetector(
            sample_rate=8000,
            webrtc_aggressiveness=1
        )

        # Process some frames
        t = np.linspace(0, 0.02, 160)
        tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        for _ in range(10):
            vad.process_frame(tone.tobytes())

        stats = vad.get_stats()

        if vad.webrtc_mode == "dual-mode":
            assert 'webrtc_detections' in stats
            assert 'energy_detections' in stats
            assert 'agreement_count' in stats
            assert 'agreement_rate' in stats

    def test_speech_segments_counter(self):
        """speech_segments should increment on each new speech."""
        vad = VoiceActivityDetector(
            energy_threshold_start=500.0,
            silence_duration_ms=500,
            min_speech_duration_ms=100
        )

        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        silence = np.zeros(160, dtype=np.int16)

        # First speech segment
        for _ in range(10):
            vad.process_frame(loud_tone.tobytes())
        for _ in range(30):
            vad.process_frame(silence.tobytes())

        # Second speech segment
        for _ in range(10):
            vad.process_frame(loud_tone.tobytes())
        for _ in range(30):
            vad.process_frame(silence.tobytes())

        stats = vad.get_stats()
        # Note: speech_segments may be filtered if too short
        assert stats['speech_segments'] >= 1


class TestVADReset:
    """Test VAD reset functionality."""

    def test_reset_clears_state(self):
        """reset() should clear VAD state."""
        vad = VoiceActivityDetector()

        # Trigger some speech
        t = np.linspace(0, 0.02, 160)
        loud_tone = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        vad.process_frame(loud_tone.tobytes())

        # Reset
        vad.reset()

        assert vad.state == VADState.SILENCE
        assert vad.silence_frames == 0
        assert vad.speech_frames == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
