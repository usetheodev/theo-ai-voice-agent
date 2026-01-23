"""
Piper TTS Integration

High-performance CPU-based Text-to-Speech using Piper.

Features:
- RTF < 0.2 (5x faster than Kokoro)
- CPU-only (no GPU required)
- Portuguese BR native support
- Low memory footprint (~500MB)

Performance:
- Latency: ~200-300ms for typical response
- RTF: 0.15-0.2 (process 3s audio in ~0.5s)
- Throughput: 10+ chars/s

References:
- Piper: https://github.com/OHF-Voice/piper1-gpl
- Models: https://huggingface.co/rhasspy/piper-voices
"""

import subprocess
import tempfile
import numpy as np
import logging
import time
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Check if piper is available
try:
    result = subprocess.run(
        ["python3", "-m", "piper", "--help"],
        capture_output=True,
        text=True,
        timeout=5
    )
    PIPER_AVAILABLE = result.returncode == 0
except (FileNotFoundError, subprocess.TimeoutExpired):
    PIPER_AVAILABLE = False
    logger.warning("Piper TTS not available. Install: pip install piper-tts")


class PiperTTS:
    """
    Piper TTS engine for ultra-fast speech synthesis.

    Uses Piper's VITS-based models optimized for CPU inference.

    Example:
        >>> tts = PiperTTS(model="pt_BR-faber-medium")
        >>> audio = tts.synthesize("Olá, como posso ajudar?")
        >>> print(f"Generated {len(audio)} samples")
    """

    def __init__(
        self,
        model: str = "pt_BR-faber-medium",
        sample_rate: int = 22050,
        quality: str = "medium",
    ):
        """
        Initialize Piper TTS.

        Args:
            model: Model name (e.g., "pt_BR-faber-medium", "pt_BR-edresson-medium")
            sample_rate: Output sample rate (default: 22050 Hz)
            quality: Model quality (low, medium, high)

        Raises:
            RuntimeError: If Piper is not available
        """
        if not PIPER_AVAILABLE:
            raise RuntimeError(
                "Piper TTS not available. Install with: pip install piper-tts"
            )

        self.model = model
        self.sample_rate = sample_rate
        self.quality = quality

        # Stats
        self.total_chars = 0
        self.total_synthesis_time = 0.0
        self.total_audio_duration = 0.0
        self.synthesis_count = 0

        logger.info(
            f"🔧 Initializing Piper TTS: model={model}, sample_rate={sample_rate}"
        )

        # Verify model is available (lazy download if needed)
        self._verify_model()

        logger.info(
            f"✅ Piper TTS initialized: model={model}, quality={quality}"
        )

    def _verify_model(self):
        """Verify that the model is available (download automatically if needed)."""
        try:
            # Test if model is already available
            result = subprocess.run(
                ["python3", "-m", "piper", "-m", self.model, "-f", "/dev/null", "--", "test"],
                capture_output=True,
                timeout=10,
            )

            if result.returncode == 0:
                logger.info(f"✅ Model {self.model} already downloaded")
                return

            # Check if error is about missing model
            error_msg = result.stderr.decode() if result.stderr else ""
            if "Unable to find voice" in error_msg:
                logger.info(f"📥 Downloading Piper model: {self.model} (first use, ~5MB)...")

                # Download model using piper.download_voices
                download_result = subprocess.run(
                    ["python3", "-m", "piper.download_voices", self.model],
                    capture_output=True,
                    timeout=120,  # 2 minutes for download
                )

                if download_result.returncode != 0:
                    download_error = download_result.stderr.decode() if download_result.stderr else "Unknown error"
                    raise RuntimeError(
                        f"Failed to download Piper model '{self.model}': {download_error}\n"
                        f"Available models: https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR"
                    )

                logger.info(f"✅ Model {self.model} downloaded successfully")
                return

            # Other error
            raise RuntimeError(
                f"Piper model verification failed: {error_msg}\n"
                f"Available models: https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR"
            )

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Piper model download/verification timeout. "
                f"Check network or model name: {self.model}"
            )

    def synthesize(
        self,
        text: str,
        speaker_id: Optional[int] = None,
        length_scale: float = 1.0,
        noise_scale: float = 0.667,
        noise_w: float = 0.8,
    ) -> np.ndarray:
        """
        Synthesize speech from text.

        Args:
            text: Text to synthesize (UTF-8)
            speaker_id: Speaker ID for multi-speaker models (default: None)
            length_scale: Speech speed (1.0 = normal, <1.0 = faster, >1.0 = slower)
            noise_scale: Variation in speaking (default: 0.667)
            noise_w: Variation in duration (default: 0.8)

        Returns:
            Audio samples (float32, mono, sample_rate)

        Note: Returns empty array if text is empty or synthesis fails.
        """
        if not text or not text.strip():
            logger.warning("Empty text provided to synthesize()")
            return np.array([], dtype=np.float32)

        start_time = time.time()

        # Create temporary file for output
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            output_path = tmp_file.name

        try:
            # Build piper command (using python3 -m piper)
            cmd = [
                "python3", "-m", "piper",
                "-m", self.model,
                "-f", output_path,
                "--length-scale", str(length_scale),
                "--noise-scale", str(noise_scale),
                "--noise-w", str(noise_w),
                "--"
            ]

            if speaker_id is not None:
                # Speaker ID must come before the "--" separator
                cmd.insert(-1, "--speaker")
                cmd.insert(-1, str(speaker_id))

            # Add text after "--" separator
            cmd.append(text)

            # Run piper
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,  # 10s timeout for synthesis
            )

            if result.returncode != 0:
                error_msg = result.stderr.decode() if result.stderr else "Unknown error"
                logger.error(f"Piper synthesis failed: {error_msg}")
                return np.array([], dtype=np.float32)

            # Load generated audio
            import wave
            with wave.open(output_path, 'rb') as wav:
                sample_rate = wav.getframerate()
                frames = wav.getnframes()
                audio_bytes = wav.readframes(frames)
                channels = wav.getsampwidth()

                # Convert to numpy array
                if channels == 2:  # 16-bit
                    audio = np.frombuffer(audio_bytes, dtype=np.int16)
                    audio = audio.astype(np.float32) / 32768.0
                else:
                    raise ValueError(f"Unsupported sample width: {channels}")

            synthesis_time = time.time() - start_time
            audio_duration = len(audio) / sample_rate
            rtf = synthesis_time / audio_duration if audio_duration > 0 else 0.0

            # Update stats
            self.total_chars += len(text)
            self.total_synthesis_time += synthesis_time
            self.total_audio_duration += audio_duration
            self.synthesis_count += 1

            logger.info(
                f"✅ Synthesis #{self.synthesis_count}: {len(text)} chars → "
                f"{len(audio)} samples ({audio_duration:.2f}s) | "
                f"RTF={rtf:.3f} | latency={synthesis_time:.3f}s"
            )

            return audio

        except subprocess.TimeoutExpired:
            logger.error(f"Piper synthesis timeout for text: {text[:50]}...")
            return np.array([], dtype=np.float32)

        except Exception as e:
            logger.error(f"Piper synthesis error: {e}", exc_info=True)
            return np.array([], dtype=np.float32)

        finally:
            # Cleanup temp file
            try:
                Path(output_path).unlink(missing_ok=True)
            except Exception:
                pass

    def get_stats(self) -> Dict[str, float]:
        """
        Get TTS performance statistics.

        Returns:
            Dictionary with:
            - avg_rtf: Average Real-time Factor
            - avg_chars_per_s: Average synthesis throughput
            - total_synthesis_time: Total CPU time
            - total_audio_duration: Total audio generated
            - synthesis_count: Number of syntheses
        """
        avg_rtf = (
            self.total_synthesis_time / self.total_audio_duration
            if self.total_audio_duration > 0
            else 0.0
        )

        avg_chars_per_s = (
            self.total_chars / self.total_synthesis_time
            if self.total_synthesis_time > 0
            else 0.0
        )

        return {
            "avg_rtf": avg_rtf,
            "avg_chars_per_s": avg_chars_per_s,
            "total_synthesis_time": self.total_synthesis_time,
            "total_audio_duration": self.total_audio_duration,
            "synthesis_count": self.synthesis_count,
            "total_chars": self.total_chars,
        }

    def reset_stats(self):
        """Reset performance statistics."""
        self.total_chars = 0
        self.total_synthesis_time = 0.0
        self.total_audio_duration = 0.0
        self.synthesis_count = 0


def is_piper_available() -> bool:
    """Check if Piper TTS is available."""
    return PIPER_AVAILABLE
