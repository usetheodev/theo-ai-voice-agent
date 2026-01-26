"""Comprehensive tests for the resampling anti-aliasing fix.

Tests verify that both ``resample_audio`` (utils.audio) and
``resample_audio_np`` (streaming.optimized_buffer) correctly apply
anti-aliasing filters during downsampling, preserve passband signals,
fall back gracefully when scipy is absent, and maintain consistent
API signatures and output proportions.
"""

from __future__ import annotations

import struct
import sys
from math import gcd
from typing import Callable
from unittest.mock import patch

import numpy as np
import pytest

from voice_pipeline.utils.audio import resample_audio
from voice_pipeline.streaming.optimized_buffer import resample_audio_np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_sine_pcm16(
    freq_hz: float,
    sample_rate: int,
    duration_s: float,
    amplitude: float = 0.9,
) -> bytes:
    """Generate a pure sine-wave tone as PCM16 little-endian bytes.

    Args:
        freq_hz: Frequency of the sine wave in Hz.
        sample_rate: Sample rate in Hz.
        duration_s: Duration in seconds.
        amplitude: Peak amplitude in [0.0, 1.0] (default 0.9 to avoid clipping).

    Returns:
        PCM16 audio bytes (little-endian, mono).
    """
    n_samples = int(sample_rate * duration_s)
    t = np.arange(n_samples, dtype=np.float64) / sample_rate
    signal = amplitude * np.sin(2 * np.pi * freq_hz * t)
    pcm16 = (signal * 32767).astype(np.int16)
    return pcm16.tobytes()


def _pcm16_bytes_to_float(audio_bytes: bytes) -> np.ndarray:
    """Convert PCM16 bytes to float64 numpy array in [-1, 1]."""
    samples = np.frombuffer(audio_bytes, dtype=np.int16)
    return samples.astype(np.float64) / 32768.0


def _measure_band_energy_db_relative(
    audio_bytes: bytes,
    sample_rate: int,
    low_hz: float,
    high_hz: float,
) -> float:
    """Measure energy in a frequency band relative to total signal energy.

    Returns:
        Energy in dB (relative to total signal energy).
    """
    samples = _pcm16_bytes_to_float(audio_bytes)
    if len(samples) == 0:
        return float("-inf")

    window = np.hanning(len(samples))
    spectrum = np.fft.rfft(samples * window)
    magnitudes = np.abs(spectrum) ** 2
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)

    total_energy = np.sum(magnitudes)
    if total_energy == 0:
        return float("-inf")

    band_mask = (freqs >= low_hz) & (freqs <= high_hz)
    band_energy = np.sum(magnitudes[band_mask])
    if band_energy == 0:
        return float("-inf")

    return float(10 * np.log10(band_energy / total_energy))


def _measure_absolute_rms_in_band(
    audio_bytes: bytes,
    sample_rate: int,
    low_hz: float,
    high_hz: float,
) -> float:
    """Measure absolute RMS energy in a frequency band.

    Uses bandpass filtering via FFT to isolate the band,
    then computes the RMS of the time-domain signal.

    Returns:
        RMS value (linear, not dB).
    """
    samples = _pcm16_bytes_to_float(audio_bytes)
    if len(samples) == 0:
        return 0.0

    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)

    # Zero out everything outside the band
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    filtered_spectrum = np.zeros_like(spectrum)
    filtered_spectrum[mask] = spectrum[mask]

    # Inverse FFT to get time-domain signal in the band
    filtered_signal = np.fft.irfft(filtered_spectrum, n=len(samples))
    return float(np.sqrt(np.mean(filtered_signal ** 2)))


def _rms(audio_bytes: bytes) -> float:
    """Compute RMS of PCM16 audio."""
    samples = _pcm16_bytes_to_float(audio_bytes)
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def _amplitude_to_db(value: float, reference: float = 1.0) -> float:
    """Convert linear amplitude to dB."""
    if value <= 0:
        return float("-inf")
    return 20 * np.log10(value / reference)


# ---------------------------------------------------------------------------
# Parametrize over both implementations
# ---------------------------------------------------------------------------


RESAMPLE_FUNCTIONS: list[tuple[str, Callable[[bytes, int, int], bytes]]] = [
    ("resample_audio", resample_audio),
    ("resample_audio_np", resample_audio_np),
]


@pytest.fixture(params=RESAMPLE_FUNCTIONS, ids=[name for name, _ in RESAMPLE_FUNCTIONS])
def resample_fn(request) -> Callable[[bytes, int, int], bytes]:
    """Parametrized fixture yielding each resample function in turn."""
    return request.param[1]


# ===========================================================================
# 1. Anti-aliasing: 10 kHz signal resampled 24 kHz -> 16 kHz
# ===========================================================================


class TestAntiAliasing:
    """A 10 kHz tone resampled from 24 kHz to 16 kHz must not alias.

    The Nyquist frequency at 16 kHz is 8 kHz, so a 10 kHz component
    must be attenuated by the anti-aliasing filter.  Without the filter
    the tone would fold back to 6 kHz (16 kHz - 10 kHz) and appear as
    audible distortion.

    Acceptance criterion: energy above 8 kHz in the output signal
    must be below -40 dB relative to the INPUT signal energy.
    This measures absolute attenuation, not relative energy distribution.
    """

    SOURCE_RATE = 24_000
    TARGET_RATE = 16_000
    FREQ_HZ = 10_000.0
    DURATION_S = 0.5  # long enough for good spectral resolution

    def test_no_aliasing_energy_above_8khz_suppressed(self, resample_fn):
        """Energy above 7.5 kHz in resampled output must be < -40 dB
        relative to the original input signal energy.
        """
        pcm_in = _generate_sine_pcm16(
            self.FREQ_HZ, self.SOURCE_RATE, self.DURATION_S,
        )
        pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        rms_in = _rms(pcm_in)
        rms_near_nyquist = _measure_absolute_rms_in_band(
            pcm_out, self.TARGET_RATE, 7500, 8000,
        )

        attenuation_db = _amplitude_to_db(rms_near_nyquist, rms_in)
        assert attenuation_db < -40, (
            f"Energy near Nyquist is {attenuation_db:.1f} dB relative to input, "
            f"expected < -40 dB"
        )

    def test_alias_fold_frequency_suppressed(self, resample_fn):
        """The alias fold frequency (~6 kHz) must be suppressed
        relative to the original 10 kHz signal energy.

        Without an anti-alias filter, a 10 kHz tone sampled at 16 kHz
        would alias to 16 kHz - 10 kHz = 6 kHz with comparable energy.
        With proper filtering, the alias at 6 kHz must be > 40 dB below
        the original signal level.
        """
        pcm_in = _generate_sine_pcm16(
            self.FREQ_HZ, self.SOURCE_RATE, self.DURATION_S,
        )
        pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        rms_in = _rms(pcm_in)
        rms_alias = _measure_absolute_rms_in_band(
            pcm_out, self.TARGET_RATE, 5500, 6500,
        )

        attenuation_db = _amplitude_to_db(rms_alias, rms_in)
        assert attenuation_db < -40, (
            f"Alias fold energy around 6 kHz is {attenuation_db:.1f} dB "
            f"relative to input, expected < -40 dB"
        )

    def test_overall_output_is_mostly_silent(self, resample_fn):
        """Since 10 kHz is above target Nyquist, output must be near-silent."""
        pcm_in = _generate_sine_pcm16(
            self.FREQ_HZ, self.SOURCE_RATE, self.DURATION_S,
        )
        pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        rms_out = _rms(pcm_out)
        rms_in = _rms(pcm_in)

        # Output RMS should be at least 40 dB below input
        attenuation_db = _amplitude_to_db(rms_out, rms_in)
        assert attenuation_db < -40, (
            f"Output RMS is {attenuation_db:.1f} dB relative to input, "
            f"expected < -40 dB for a fully-filtered signal"
        )


# ===========================================================================
# 2. Passband preservation: 3 kHz signal survives resampling
# ===========================================================================


class TestPassbandPreservation:
    """A 3 kHz tone must survive resampling from 24 kHz to 16 kHz.

    3 kHz is well within the passband of both rates, so the
    anti-aliasing filter must not attenuate it significantly.
    """

    SOURCE_RATE = 24_000
    TARGET_RATE = 16_000
    FREQ_HZ = 3_000.0
    DURATION_S = 0.5

    def test_3khz_preserved_after_downsample(self, resample_fn):
        """3 kHz peak must be clearly present in the output spectrum."""
        pcm_in = _generate_sine_pcm16(
            self.FREQ_HZ, self.SOURCE_RATE, self.DURATION_S,
        )
        pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        # Energy around 3 kHz should dominate (relative to total)
        energy_3k = _measure_band_energy_db_relative(
            pcm_out, self.TARGET_RATE, 2800, 3200,
        )
        # Should be close to 0 dB (dominant component)
        assert energy_3k > -3.0, (
            f"3 kHz band energy is {energy_3k:.1f} dB, expected > -3.0 dB"
        )

    def test_3khz_amplitude_preserved(self, resample_fn):
        """RMS of the passband signal should be close to the original."""
        pcm_in = _generate_sine_pcm16(
            self.FREQ_HZ, self.SOURCE_RATE, self.DURATION_S,
        )
        pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        rms_in = _rms(pcm_in)
        rms_out = _rms(pcm_out)

        # Allow up to 20% amplitude loss (quantization + filter ripple)
        assert rms_out > rms_in * 0.80, (
            f"RMS dropped from {rms_in:.4f} to {rms_out:.4f} "
            f"({rms_out / rms_in * 100:.1f}%), expected > 80%"
        )

    def test_3khz_preserved_upsample(self, resample_fn):
        """3 kHz signal preserved when upsampling 16 kHz -> 24 kHz."""
        source_rate = 16_000
        target_rate = 24_000
        pcm_in = _generate_sine_pcm16(
            self.FREQ_HZ, source_rate, self.DURATION_S,
        )
        pcm_out = resample_fn(pcm_in, source_rate, target_rate)

        energy_3k = _measure_band_energy_db_relative(
            pcm_out, target_rate, 2800, 3200,
        )
        assert energy_3k > -3.0, (
            f"3 kHz band energy after upsample is {energy_3k:.1f} dB, "
            f"expected > -3.0 dB"
        )

    def test_1khz_signal_roundtrip(self, resample_fn):
        """A 1 kHz signal survives a downsample+upsample round-trip."""
        freq = 1_000.0
        pcm_original = _generate_sine_pcm16(freq, 24_000, self.DURATION_S)

        # Downsample 24k -> 16k -> upsample back to 24k
        pcm_down = resample_fn(pcm_original, 24_000, 16_000)
        pcm_roundtrip = resample_fn(pcm_down, 16_000, 24_000)

        rms_orig = _rms(pcm_original)
        rms_rt = _rms(pcm_roundtrip)

        # Should preserve at least 75% of energy through roundtrip
        assert rms_rt > rms_orig * 0.75, (
            f"Round-trip RMS dropped to {rms_rt / rms_orig * 100:.1f}% "
            f"of original, expected > 75%"
        )


# ===========================================================================
# 3. Fallback: numpy-only path when scipy is absent
# ===========================================================================


class TestScipyFallback:
    """Both functions must work when scipy cannot be imported.

    We mock ``scipy`` away and verify that the numpy-only fallback
    still applies anti-aliasing and preserves passband.
    """

    SOURCE_RATE = 24_000
    TARGET_RATE = 16_000
    DURATION_S = 0.5

    @staticmethod
    def _hide_scipy():
        """Context manager that hides scipy from imports."""
        import unittest.mock

        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _mock_import(name, *args, **kwargs):
            if name == "scipy" or name.startswith("scipy."):
                raise ImportError(f"Mocked: No module named '{name}'")
            return original_import(name, *args, **kwargs)

        return unittest.mock.patch("builtins.__import__", side_effect=_mock_import)

    def test_fallback_anti_aliasing_suppresses_alias(self, resample_fn):
        """Numpy fallback attenuates above-Nyquist signals relative to input."""
        pcm_in = _generate_sine_pcm16(10_000.0, self.SOURCE_RATE, self.DURATION_S)
        rms_in = _rms(pcm_in)

        with self._hide_scipy():
            pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        rms_out = _rms(pcm_out)
        attenuation_db = _amplitude_to_db(rms_out, rms_in)

        # The numpy fallback uses a 63-tap FIR which provides less
        # attenuation than scipy, so we use a more relaxed threshold of -20 dB
        assert attenuation_db < -20, (
            f"Fallback output is {attenuation_db:.1f} dB relative to input, "
            f"expected < -20 dB"
        )

    def test_fallback_passband_preserved(self, resample_fn):
        """Numpy fallback preserves 3 kHz passband signal."""
        pcm_in = _generate_sine_pcm16(3_000.0, self.SOURCE_RATE, self.DURATION_S)

        with self._hide_scipy():
            pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        energy_3k = _measure_band_energy_db_relative(
            pcm_out, self.TARGET_RATE, 2800, 3200,
        )
        assert energy_3k > -3.0, (
            f"Fallback 3 kHz energy is {energy_3k:.1f} dB, expected > -3.0 dB"
        )

    def test_fallback_passband_amplitude(self, resample_fn):
        """Numpy fallback preserves 3 kHz signal amplitude."""
        pcm_in = _generate_sine_pcm16(3_000.0, self.SOURCE_RATE, self.DURATION_S)

        with self._hide_scipy():
            pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        rms_in = _rms(pcm_in)
        rms_out = _rms(pcm_out)

        # More relaxed for numpy fallback (allow up to 30% loss)
        assert rms_out > rms_in * 0.70, (
            f"Fallback RMS dropped from {rms_in:.4f} to {rms_out:.4f} "
            f"({rms_out / rms_in * 100:.1f}%), expected > 70%"
        )

    def test_fallback_produces_correct_length(self, resample_fn):
        """Numpy fallback produces proportionally correct output length."""
        pcm_in = _generate_sine_pcm16(1_000.0, self.SOURCE_RATE, self.DURATION_S)

        with self._hide_scipy():
            pcm_out = resample_fn(pcm_in, self.SOURCE_RATE, self.TARGET_RATE)

        n_in = len(pcm_in) // 2
        n_out = len(pcm_out) // 2
        expected = int(n_in * self.TARGET_RATE / self.SOURCE_RATE)

        # Allow 2-sample tolerance for rounding
        assert abs(n_out - expected) <= 2, (
            f"Fallback output length {n_out} differs from expected {expected}"
        )


# ===========================================================================
# 4. Signature compatibility and proportional output lengths
# ===========================================================================


class TestSignatureAndLengths:
    """Both resample functions must share the same call convention
    (PCM16 bytes in, PCM16 bytes out) and produce proportionally
    correct output lengths.
    """

    def test_same_rate_returns_input_unchanged(self, resample_fn):
        """Resampling at same rate returns the original bytes."""
        pcm = _generate_sine_pcm16(440.0, 16_000, 0.1)
        result = resample_fn(pcm, 16_000, 16_000)
        assert result == pcm

    def test_empty_input_returns_empty(self, resample_fn):
        """Empty input produces empty output."""
        result = resample_fn(b"", 24_000, 16_000)
        assert result == b""

    def test_output_is_bytes(self, resample_fn):
        """Output type must be bytes."""
        pcm = _generate_sine_pcm16(440.0, 24_000, 0.1)
        result = resample_fn(pcm, 24_000, 16_000)
        assert isinstance(result, (bytes, bytearray))

    def test_output_length_even(self, resample_fn):
        """Output byte length must be even (valid PCM16)."""
        pcm = _generate_sine_pcm16(440.0, 24_000, 0.1)
        result = resample_fn(pcm, 24_000, 16_000)
        assert len(result) % 2 == 0, "Output byte length is odd -- invalid PCM16"

    @pytest.mark.parametrize(
        "source_rate, target_rate",
        [
            (24_000, 16_000),
            (16_000, 24_000),
            (48_000, 16_000),
            (44_100, 16_000),
            (22_050, 16_000),
            (16_000, 8_000),
            (8_000, 16_000),
        ],
        ids=[
            "24k->16k",
            "16k->24k",
            "48k->16k",
            "44.1k->16k",
            "22.05k->16k",
            "16k->8k",
            "8k->16k",
        ],
    )
    def test_proportional_output_length(
        self, resample_fn, source_rate: int, target_rate: int,
    ):
        """Output sample count must be proportional to rate ratio."""
        duration_s = 0.25
        pcm_in = _generate_sine_pcm16(440.0, source_rate, duration_s)
        pcm_out = resample_fn(pcm_in, source_rate, target_rate)

        n_in = len(pcm_in) // 2
        n_out = len(pcm_out) // 2
        expected = int(n_in * target_rate / source_rate)

        # Allow tolerance for rounding differences between implementations
        tolerance = max(2, int(n_in * 0.01))  # 1% or 2 samples, whichever is larger
        assert abs(n_out - expected) <= tolerance, (
            f"{source_rate}->{target_rate}: got {n_out} samples, "
            f"expected ~{expected} (tolerance {tolerance})"
        )

    def test_both_functions_agree_on_length(self):
        """resample_audio and resample_audio_np produce same output length."""
        pcm = _generate_sine_pcm16(1_000.0, 24_000, 0.5)

        out_a = resample_audio(pcm, 24_000, 16_000)
        out_b = resample_audio_np(pcm, 24_000, 16_000)

        n_a = len(out_a) // 2
        n_b = len(out_b) // 2

        # They may use slightly different rounding, allow 2-sample diff
        assert abs(n_a - n_b) <= 2, (
            f"resample_audio produced {n_a} samples, "
            f"resample_audio_np produced {n_b} samples"
        )

    def test_both_functions_agree_on_spectrum(self):
        """Both functions should produce spectrally similar output."""
        pcm = _generate_sine_pcm16(3_000.0, 24_000, 0.5)

        out_a = resample_audio(pcm, 24_000, 16_000)
        out_b = resample_audio_np(pcm, 24_000, 16_000)

        # Both should have strong 3 kHz component
        e_a = _measure_band_energy_db_relative(out_a, 16_000, 2800, 3200)
        e_b = _measure_band_energy_db_relative(out_b, 16_000, 2800, 3200)

        assert e_a > -3.0, f"resample_audio 3 kHz energy = {e_a:.1f} dB"
        assert e_b > -3.0, f"resample_audio_np 3 kHz energy = {e_b:.1f} dB"

    def test_both_functions_accept_same_signature(self):
        """Both functions accept (bytes, int, int) and return bytes."""
        pcm = _generate_sine_pcm16(440.0, 24_000, 0.05)

        # Verify both accept the same positional args
        result_a = resample_audio(pcm, 24_000, 16_000)
        result_b = resample_audio_np(pcm, 24_000, 16_000)

        assert isinstance(result_a, (bytes, bytearray))
        assert isinstance(result_b, (bytes, bytearray))
        assert len(result_a) > 0
        assert len(result_b) > 0
