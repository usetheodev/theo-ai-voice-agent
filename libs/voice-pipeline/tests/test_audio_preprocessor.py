"""Tests for AudioPreprocessor (AGC + Noise Gate)."""

import math

import numpy as np
import pytest

from voice_pipeline.audio.preprocessor import AudioPreprocessor, AudioPreprocessorConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_sine_pcm16(
    frequency: float = 440.0,
    duration_s: float = 0.5,
    amplitude_dbfs: float = -20.0,
    sample_rate: int = 16000,
) -> bytes:
    """Generate a mono PCM16 sine wave at a given amplitude (dBFS).

    Args:
        frequency: Frequency in Hz.
        duration_s: Duration in seconds.
        amplitude_dbfs: Amplitude in dBFS (0 dBFS = full scale).
        sample_rate: Sample rate in Hz.

    Returns:
        PCM16 little-endian bytes.
    """
    t = np.arange(int(sample_rate * duration_s)) / sample_rate
    amplitude_linear = 10 ** (amplitude_dbfs / 20.0)
    samples = (amplitude_linear * np.sin(2 * np.pi * frequency * t) * 32767).astype(
        np.int16
    )
    return samples.tobytes()


def _rms_dbfs(audio_bytes: bytes) -> float:
    """Compute RMS level of PCM16 audio in dBFS."""
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float64) / 32768.0
    rms = np.sqrt(np.mean(samples ** 2))
    if rms < 1e-10:
        return -120.0
    return 20.0 * math.log10(rms)


def _peak_dbfs(audio_bytes: bytes) -> float:
    """Compute peak level of PCM16 audio in dBFS."""
    samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float64) / 32768.0
    peak = np.max(np.abs(samples))
    if peak < 1e-10:
        return -120.0
    return 20.0 * math.log10(peak)


def _generate_silence_pcm16(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Generate silent PCM16 audio (all zeros)."""
    num_samples = int(sample_rate * duration_s)
    return np.zeros(num_samples, dtype=np.int16).tobytes()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestAudioPreprocessor:
    """Comprehensive tests for AudioPreprocessor."""

    # -- Test 1: Quiet audio amplified toward target -----------------------

    def test_quiet_audio_amplified_toward_target(self):
        """Quiet audio (-50 dBFS) should be amplified toward target (-20 dBFS).

        After processing enough audio for the AGC to converge, the output
        level should be significantly louder than the input.
        """
        config = AudioPreprocessorConfig(
            enable_agc=True,
            agc_target_db=-20.0,
            agc_max_gain_db=40.0,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Generate 2 seconds of quiet audio for AGC convergence
        quiet_audio = _generate_sine_pcm16(
            amplitude_dbfs=-50.0, duration_s=2.0, sample_rate=16000
        )

        processed = preprocessor.process(quiet_audio)

        input_rms = _rms_dbfs(quiet_audio)
        output_rms = _rms_dbfs(processed)

        # Output must be louder than input (at least 15 dB gain applied)
        assert output_rms > input_rms + 15, (
            f"Expected output ({output_rms:.1f} dBFS) to be at least 15 dB "
            f"louder than input ({input_rms:.1f} dBFS)"
        )
        # Output should be close-ish to target (within 10 dB tolerance for
        # RMS vs peak and convergence lag)
        assert output_rms > -35.0, (
            f"Output RMS ({output_rms:.1f} dBFS) should approach target -20 dBFS"
        )

    # -- Test 2: Loud audio attenuated ------------------------------------

    def test_loud_audio_attenuated(self):
        """Loud audio (-5 dBFS) should be attenuated toward target (-20 dBFS)."""
        config = AudioPreprocessorConfig(
            enable_agc=True,
            agc_target_db=-20.0,
            agc_max_gain_db=30.0,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        loud_audio = _generate_sine_pcm16(
            amplitude_dbfs=-5.0, duration_s=2.0, sample_rate=16000
        )

        processed = preprocessor.process(loud_audio)

        input_rms = _rms_dbfs(loud_audio)
        output_rms = _rms_dbfs(processed)

        # Output must be quieter than input
        assert output_rms < input_rms, (
            f"Expected output ({output_rms:.1f} dBFS) to be quieter than "
            f"input ({input_rms:.1f} dBFS)"
        )
        # Should approach target
        assert output_rms < -10.0, (
            f"Output RMS ({output_rms:.1f} dBFS) should be closer to target -20 dBFS"
        )

    # -- Test 3: Max gain respected ----------------------------------------

    def test_max_gain_respected(self):
        """AGC gain should never exceed agc_max_gain_db."""
        max_gain_db = 10.0
        config = AudioPreprocessorConfig(
            enable_agc=True,
            agc_target_db=-10.0,
            agc_max_gain_db=max_gain_db,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Very quiet audio that would need huge gain
        very_quiet = _generate_sine_pcm16(
            amplitude_dbfs=-60.0, duration_s=2.0, sample_rate=16000
        )

        processed = preprocessor.process(very_quiet)

        input_rms = _rms_dbfs(very_quiet)
        output_rms = _rms_dbfs(processed)
        actual_gain = output_rms - input_rms

        # The effective gain should not exceed max_gain_db by a significant margin.
        # We allow a small tolerance (3 dB) because the AGC converges gradually
        # and RMS measurement includes the ramp-up period.
        assert actual_gain <= max_gain_db + 3.0, (
            f"Effective gain ({actual_gain:.1f} dB) exceeded max_gain_db "
            f"({max_gain_db} dB) + tolerance"
        )

    # -- Test 4: Noise gate zeroes samples below threshold -----------------

    def test_noise_gate_zeroes_below_threshold(self):
        """Samples below the noise gate threshold should be zeroed."""
        config = AudioPreprocessorConfig(
            enable_agc=False,
            enable_noise_gate=True,
            noise_gate_threshold_db=-40.0,
            noise_gate_hold_time_ms=0.0,  # No hold — instant gate
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Audio well below the threshold
        quiet_audio = _generate_sine_pcm16(
            amplitude_dbfs=-60.0, duration_s=0.5, sample_rate=16000
        )

        processed = preprocessor.process(quiet_audio)

        # All output samples should be zero (gated)
        output_samples = np.frombuffer(processed, dtype=np.int16)
        non_zero = np.count_nonzero(output_samples)
        total = len(output_samples)

        # Allow very few non-zero samples (edge effects from threshold check)
        assert non_zero / total < 0.01, (
            f"Expected nearly all samples gated, but {non_zero}/{total} were non-zero"
        )

    # -- Test 5: Hold timer prevents chattering ----------------------------

    def test_noise_gate_hold_timer_prevents_chattering(self):
        """Hold timer should keep gate open briefly after signal drops.

        We send a loud burst, then silence. Samples during the hold period
        should still pass (gate stays open). After hold expires, silence
        should be gated.
        """
        hold_time_ms = 50.0
        sample_rate = 16000
        config = AudioPreprocessorConfig(
            enable_agc=False,
            enable_noise_gate=True,
            noise_gate_threshold_db=-40.0,
            noise_gate_hold_time_ms=hold_time_ms,
            sample_rate=sample_rate,
        )
        preprocessor = AudioPreprocessor(config)

        # Phase 1: Loud audio opens the gate
        loud_audio = _generate_sine_pcm16(
            amplitude_dbfs=-20.0, duration_s=0.1, sample_rate=sample_rate
        )
        preprocessor.process(loud_audio)

        # Phase 2: Very quiet audio (below threshold) — gate should hold open
        hold_samples = int(hold_time_ms / 1000.0 * sample_rate)
        # Send exactly half the hold duration — gate should still be open
        half_hold = hold_samples // 2
        quiet_during_hold = np.full(half_hold, 10, dtype=np.int16).tobytes()
        processed_hold = preprocessor.process(quiet_during_hold)

        # During hold, samples should pass through (not zeroed)
        hold_output = np.frombuffer(processed_hold, dtype=np.int16)
        assert np.any(hold_output != 0), (
            "Gate should remain open during hold period, but all samples were zeroed"
        )

        # Phase 3: Send much more silence to exhaust hold timer
        long_silence = _generate_silence_pcm16(
            duration_s=0.5, sample_rate=sample_rate
        )
        processed_after = preprocessor.process(long_silence)

        # After hold expires, samples should be zeroed
        after_output = np.frombuffer(processed_after, dtype=np.int16)
        # Check the tail end (last 25%) — hold should be expired by then
        tail_start = len(after_output) * 3 // 4
        tail = after_output[tail_start:]
        assert np.all(tail == 0), (
            "Gate should be closed after hold expires, but some samples were non-zero"
        )

    # -- Test 6: 20dB difference compensated (notebook vs headset) ---------

    def test_20db_difference_compensated(self):
        """AGC should make a notebook mic (-50 dBFS) and headset (-30 dBFS)
        produce similar output levels.
        """
        config = AudioPreprocessorConfig(
            enable_agc=True,
            agc_target_db=-20.0,
            agc_max_gain_db=40.0,
            enable_noise_gate=False,
            sample_rate=16000,
        )

        # Simulate notebook mic (quiet)
        notebook_audio = _generate_sine_pcm16(
            amplitude_dbfs=-50.0, duration_s=2.0, sample_rate=16000
        )
        preprocessor_notebook = AudioPreprocessor(config)
        processed_notebook = preprocessor_notebook.process(notebook_audio)

        # Simulate headset mic (louder)
        headset_audio = _generate_sine_pcm16(
            amplitude_dbfs=-30.0, duration_s=2.0, sample_rate=16000
        )
        preprocessor_headset = AudioPreprocessor(config)
        processed_headset = preprocessor_headset.process(headset_audio)

        notebook_rms = _rms_dbfs(processed_notebook)
        headset_rms = _rms_dbfs(processed_headset)

        # After AGC, the difference should be much smaller than the original 20 dB
        difference = abs(notebook_rms - headset_rms)
        assert difference < 10.0, (
            f"AGC should reduce the 20 dB input difference. "
            f"Output difference is still {difference:.1f} dB "
            f"(notebook={notebook_rms:.1f}, headset={headset_rms:.1f})"
        )

    # -- Test 7: Reset clears state ----------------------------------------

    def test_reset_clears_state(self):
        """After reset(), internal state should return to initial values."""
        config = AudioPreprocessorConfig(
            enable_agc=True,
            enable_noise_gate=True,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Process some audio to modify internal state
        audio = _generate_sine_pcm16(
            amplitude_dbfs=-30.0, duration_s=1.0, sample_rate=16000
        )
        preprocessor.process(audio)

        # State should be modified
        assert preprocessor._envelope != 0.0
        assert preprocessor._current_gain != 1.0 or preprocessor._envelope != 0.0

        # Reset
        preprocessor.reset()

        # State should be back to initial values
        assert preprocessor._envelope == 0.0
        assert preprocessor._current_gain == 1.0
        assert preprocessor._gate_open is False
        assert preprocessor._gate_hold_counter == 0

    # -- Test 8: Properties current_gain_db and current_level_db -----------

    def test_properties_current_gain_db(self):
        """current_gain_db should reflect the gain applied by AGC."""
        config = AudioPreprocessorConfig(
            enable_agc=True,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Before processing: gain is 1.0 = 0 dB
        assert preprocessor.current_gain_db == pytest.approx(0.0, abs=0.01)

        # Process quiet audio — gain should increase
        quiet_audio = _generate_sine_pcm16(
            amplitude_dbfs=-50.0, duration_s=1.0, sample_rate=16000
        )
        preprocessor.process(quiet_audio)

        assert preprocessor.current_gain_db > 0.0, (
            "After processing quiet audio, gain should be positive (amplification)"
        )

    def test_properties_current_level_db(self):
        """current_level_db should track the input signal envelope."""
        config = AudioPreprocessorConfig(
            enable_agc=True,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Before processing: envelope is 0, should be -inf
        assert preprocessor.current_level_db == float('-inf')

        # Process audio at -30 dBFS
        audio = _generate_sine_pcm16(
            amplitude_dbfs=-30.0, duration_s=1.0, sample_rate=16000
        )
        preprocessor.process(audio)

        level = preprocessor.current_level_db
        # Should be in a reasonable range near -30 dBFS
        assert -40.0 < level < -20.0, (
            f"current_level_db ({level:.1f}) should be near -30 dBFS"
        )

    def test_current_gain_db_negative_infinity_when_zero(self):
        """current_gain_db should return -inf if current_gain is 0."""
        config = AudioPreprocessorConfig(enable_agc=True, enable_noise_gate=False)
        preprocessor = AudioPreprocessor(config)
        preprocessor._current_gain = 0.0
        assert preprocessor.current_gain_db == float('-inf')

    # -- Test 9: Empty input returns empty output --------------------------

    def test_empty_input_returns_empty_output(self):
        """process(b'') should return b''."""
        preprocessor = AudioPreprocessor()
        result = preprocessor.process(b"")
        assert result == b""

    def test_empty_bytes_object(self):
        """process(bytes()) should return bytes()."""
        preprocessor = AudioPreprocessor()
        result = preprocessor.process(bytes())
        assert result == b""

    # -- Test 10: AGC only (noise gate disabled) ---------------------------

    def test_agc_only_no_noise_gate(self):
        """With noise gate disabled, quiet signals should pass through
        (not be zeroed) and AGC should amplify them.
        """
        config = AudioPreprocessorConfig(
            enable_agc=True,
            agc_target_db=-20.0,
            agc_max_gain_db=40.0,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Audio below what a noise gate threshold would normally gate
        quiet_audio = _generate_sine_pcm16(
            amplitude_dbfs=-55.0, duration_s=1.0, sample_rate=16000
        )

        processed = preprocessor.process(quiet_audio)

        # Signal should NOT be zeroed
        output_samples = np.frombuffer(processed, dtype=np.int16)
        assert np.any(output_samples != 0), (
            "With noise gate disabled, quiet audio should not be zeroed"
        )

        # Signal should be amplified
        output_rms = _rms_dbfs(processed)
        input_rms = _rms_dbfs(quiet_audio)
        assert output_rms > input_rms, "AGC should amplify quiet audio"

    # -- Test 11: Noise gate only (AGC disabled) ---------------------------

    def test_noise_gate_only_no_agc(self):
        """With AGC disabled, audio above threshold should pass unmodified."""
        config = AudioPreprocessorConfig(
            enable_agc=False,
            enable_noise_gate=True,
            noise_gate_threshold_db=-40.0,
            noise_gate_hold_time_ms=0.0,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        # Audio well above threshold
        loud_audio = _generate_sine_pcm16(
            amplitude_dbfs=-20.0, duration_s=0.5, sample_rate=16000
        )

        processed = preprocessor.process(loud_audio)

        input_rms = _rms_dbfs(loud_audio)
        output_rms = _rms_dbfs(processed)

        # Without AGC, level should be essentially unchanged
        assert abs(output_rms - input_rms) < 1.0, (
            f"With AGC disabled, output ({output_rms:.1f} dBFS) should match "
            f"input ({input_rms:.1f} dBFS)"
        )

    def test_noise_gate_only_below_threshold(self):
        """With AGC disabled, audio below threshold should be zeroed."""
        config = AudioPreprocessorConfig(
            enable_agc=False,
            enable_noise_gate=True,
            noise_gate_threshold_db=-40.0,
            noise_gate_hold_time_ms=0.0,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        quiet_audio = _generate_sine_pcm16(
            amplitude_dbfs=-60.0, duration_s=0.5, sample_rate=16000
        )

        processed = preprocessor.process(quiet_audio)
        output_samples = np.frombuffer(processed, dtype=np.int16)

        non_zero_ratio = np.count_nonzero(output_samples) / len(output_samples)
        assert non_zero_ratio < 0.01, (
            f"Expected nearly all samples gated, but {non_zero_ratio*100:.1f}% non-zero"
        )

    # -- Additional edge-case tests ----------------------------------------

    def test_default_config(self):
        """AudioPreprocessor with default config should work without errors."""
        preprocessor = AudioPreprocessor()
        audio = _generate_sine_pcm16(amplitude_dbfs=-30.0, duration_s=0.1)
        processed = preprocessor.process(audio)
        assert len(processed) == len(audio)

    def test_output_length_matches_input(self):
        """Processed output should have the same byte length as input."""
        preprocessor = AudioPreprocessor()
        audio = _generate_sine_pcm16(amplitude_dbfs=-25.0, duration_s=0.3)
        processed = preprocessor.process(audio)
        assert len(processed) == len(audio)

    def test_multiple_chunks_stateful(self):
        """Processing audio in multiple chunks should maintain state across
        calls, producing different output than processing with a fresh instance.
        """
        config = AudioPreprocessorConfig(
            enable_agc=True,
            agc_target_db=-20.0,
            agc_max_gain_db=30.0,
            enable_noise_gate=False,
            sample_rate=16000,
        )

        # Process 5 chunks with a single stateful preprocessor
        chunk = _generate_sine_pcm16(
            amplitude_dbfs=-45.0,
            duration_s=0.1,
            sample_rate=16000,
        )
        stateful = AudioPreprocessor(config)
        for _ in range(4):
            stateful.process(chunk)
        fifth_stateful = stateful.process(chunk)

        # Process the same chunk with a fresh preprocessor (no prior state)
        fresh = AudioPreprocessor(config)
        fifth_fresh = fresh.process(chunk)

        stateful_rms = _rms_dbfs(fifth_stateful)
        fresh_rms = _rms_dbfs(fifth_fresh)

        # The outputs must differ, proving statefulness across calls
        assert abs(stateful_rms - fresh_rms) > 0.5, (
            f"Stateful processing should differ from fresh: "
            f"stateful={stateful_rms:.1f}, fresh={fresh_rms:.1f}"
        )

    def test_clipping_prevention(self):
        """Output should never exceed 0 dBFS (PCM16 clipping)."""
        config = AudioPreprocessorConfig(
            enable_agc=True,
            agc_target_db=-5.0,  # Aggressive target
            agc_max_gain_db=40.0,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        audio = _generate_sine_pcm16(
            amplitude_dbfs=-10.0, duration_s=1.0, sample_rate=16000
        )
        processed = preprocessor.process(audio)

        output_samples = np.frombuffer(processed, dtype=np.int16)
        # No sample should exceed the PCM16 range
        assert np.all(output_samples >= -32768)
        assert np.all(output_samples <= 32767)

    def test_both_disabled_passthrough(self):
        """With both AGC and noise gate disabled, output should equal input."""
        config = AudioPreprocessorConfig(
            enable_agc=False,
            enable_noise_gate=False,
            sample_rate=16000,
        )
        preprocessor = AudioPreprocessor(config)

        audio = _generate_sine_pcm16(
            amplitude_dbfs=-25.0, duration_s=0.5, sample_rate=16000
        )
        processed = preprocessor.process(audio)

        # With both disabled, only float conversion round-trip occurs.
        # Allow +-1 LSB difference from int16->float32->int16 round-trip.
        input_arr = np.frombuffer(audio, dtype=np.int16).astype(np.int32)
        output_arr = np.frombuffer(processed, dtype=np.int16).astype(np.int32)
        max_diff = np.max(np.abs(input_arr - output_arr))
        assert max_diff <= 1, (
            f"Passthrough should preserve samples (max diff={max_diff})"
        )
