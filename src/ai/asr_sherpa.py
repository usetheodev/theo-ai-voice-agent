"""
Sherpa-ONNX ASR Module

Optimized CPU-based ASR using Sherpa-ONNX with Whisper large-v3.

Features:
- ONNX Runtime (CPU-optimized)
- INT8 quantization (6x faster than full precision)
- Streaming support via chunking
- RTF (Real-time Factor) monitoring
- Portuguese language support

Performance:
- RTF Target: <0.3 on CPU (3s audio in <1s processing)
- Latency: ~100-300ms per chunk
- Memory: ~2GB model + ~512MB runtime

References:
- Sherpa-ONNX: https://github.com/k2-fsa/sherpa-onnx
- Whisper large-v3: OpenAI's latest multilingual ASR
"""

import numpy as np
import logging
import time
from typing import Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import sherpa_onnx
    SHERPA_ONNX_AVAILABLE = True
except ImportError:
    SHERPA_ONNX_AVAILABLE = False
    logger.warning("Sherpa-ONNX not available. Install: pip install sherpa-onnx")


class SherpaONNXASR:
    """
    Sherpa-ONNX ASR for CPU-optimized speech recognition.

    Uses Whisper large-v3 INT8 quantized model for 6x speedup.

    Example:
        >>> asr = SherpaONNXASR()
        >>> text, rtf = asr.transcribe(audio_chunk)
        >>> print(f"Transcription: {text} (RTF: {rtf:.3f})")
    """

    def __init__(
        self,
        model_dir: str = "models/sherpa-onnx/sherpa-onnx-whisper-large-v3",
        language: str = "pt",
        num_threads: int = 4,
    ):
        """
        Initialize Sherpa-ONNX ASR.

        Args:
            model_dir: Path to Sherpa-ONNX Whisper model directory
            language: Language code (pt, en, es, etc.)
            num_threads: Number of CPU threads for inference

        Raises:
            RuntimeError: If Sherpa-ONNX is not available or model not found
        """
        if not SHERPA_ONNX_AVAILABLE:
            raise RuntimeError(
                "Sherpa-ONNX not available. Install: pip install sherpa-onnx"
            )

        self.model_dir = Path(model_dir)
        self.language = language
        self.num_threads = num_threads

        # Auto-detect model files (supports tiny, base, small, medium, large-v3)
        encoder_int8 = list(self.model_dir.glob("*-encoder.int8.onnx"))
        decoder_int8 = list(self.model_dir.glob("*-decoder.int8.onnx"))
        tokens_file = list(self.model_dir.glob("*-tokens.txt"))

        if not encoder_int8:
            raise FileNotFoundError(
                f"Encoder not found in {self.model_dir}\n"
                f"Expected: *-encoder.int8.onnx\n"
                f"Download from: https://github.com/k2-fsa/sherpa-onnx/releases"
            )

        if not decoder_int8:
            raise FileNotFoundError(f"Decoder not found in {self.model_dir}")

        if not tokens_file:
            raise FileNotFoundError(f"Tokens not found in {self.model_dir}")

        encoder_path = encoder_int8[0]
        decoder_path = decoder_int8[0]
        tokens_path = tokens_file[0]

        # Detect model name from file prefix
        model_name = encoder_path.stem.replace("-encoder.int8", "")

        # Initialize recognizer
        logger.info(f"🔧 Loading Sherpa-ONNX Whisper {model_name} ({language})...")

        self.recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
            encoder=str(encoder_path),
            decoder=str(decoder_path),
            tokens=str(tokens_path),
            language=language,
            num_threads=num_threads,
        )

        # Stats
        self.total_audio_duration = 0.0
        self.total_processing_time = 0.0
        self.transcription_count = 0
        self.model_name = model_name

        logger.info(
            f"✅ Sherpa-ONNX ASR initialized: "
            f"model={model_name}, lang={language}, threads={num_threads}"
        )

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> tuple[str, float]:
        """
        Transcribe audio chunk.

        Args:
            audio: Audio samples (float32, mono, 16kHz)
            sample_rate: Sample rate (must be 16000 Hz)

        Returns:
            Tuple of (transcription, rtf)
            - transcription: Transcribed text
            - rtf: Real-time Factor (processing_time / audio_duration)

        Note: Sherpa-ONNX expects 16kHz mono audio. Resample if needed.
        """
        if sample_rate != 16000:
            raise ValueError(
                f"Sherpa-ONNX requires 16kHz audio, got {sample_rate}Hz. "
                "Please resample before calling transcribe()."
            )

        # Ensure float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Normalize to [-1, 1] if needed
        if audio.max() > 1.0 or audio.min() < -1.0:
            audio = audio / 32768.0  # Assuming int16 range

        # Measure processing time
        start_time = time.time()

        # Create stream and feed audio
        stream = self.recognizer.create_stream()
        stream.accept_waveform(sample_rate, audio)

        # Decode
        self.recognizer.decode_stream(stream)

        # Get result
        result = stream.result.text.strip()

        processing_time = time.time() - start_time

        # Calculate RTF (Real-time Factor)
        audio_duration = len(audio) / sample_rate
        rtf = processing_time / audio_duration if audio_duration > 0 else 0.0

        # Update stats
        self.total_audio_duration += audio_duration
        self.total_processing_time += processing_time
        self.transcription_count += 1

        logger.debug(
            f"ASR: '{result}' | "
            f"RTF={rtf:.3f} | "
            f"audio={audio_duration:.2f}s | "
            f"proc={processing_time:.3f}s"
        )

        return result, rtf

    def transcribe_array(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
    ) -> str:
        """
        Transcribe audio array (compatibility wrapper for main.py).

        This method provides API compatibility with other ASR implementations
        (DistilWhisperASR, WhisperASR) which use transcribe_array().

        Args:
            audio: Audio samples (float32, mono, 16kHz)
            sample_rate: Sample rate (must be 16000 Hz)

        Returns:
            Transcribed text (str)

        Note: This is a wrapper around transcribe() that discards RTF metric.
        """
        result, rtf = self.transcribe(audio, sample_rate)
        return result

    def transcribe_streaming(
        self,
        audio_chunks: list[np.ndarray],
        sample_rate: int = 16000,
        chunk_duration_s: float = 1.0,
    ) -> list[tuple[str, float]]:
        """
        Transcribe multiple audio chunks (simulated streaming).

        Args:
            audio_chunks: List of audio chunks
            sample_rate: Sample rate
            chunk_duration_s: Duration of each chunk in seconds

        Returns:
            List of (transcription, rtf) tuples for each chunk
        """
        results = []

        for i, chunk in enumerate(audio_chunks):
            text, rtf = self.transcribe(chunk, sample_rate)

            if text:  # Only add non-empty transcriptions
                results.append((text, rtf))

                logger.info(
                    f"📝 Chunk {i+1}/{len(audio_chunks)}: '{text}' (RTF: {rtf:.3f})"
                )

        return results

    def get_stats(self) -> Dict[str, float]:
        """
        Get ASR performance statistics.

        Returns:
            Dictionary with:
            - avg_rtf: Average Real-time Factor
            - total_audio_duration: Total audio processed (seconds)
            - total_processing_time: Total CPU time (seconds)
            - transcription_count: Number of transcriptions
        """
        avg_rtf = (
            self.total_processing_time / self.total_audio_duration
            if self.total_audio_duration > 0
            else 0.0
        )

        return {
            "avg_rtf": avg_rtf,
            "total_audio_duration": self.total_audio_duration,
            "total_processing_time": self.total_processing_time,
            "transcription_count": self.transcription_count,
        }

    def reset_stats(self):
        """Reset performance statistics."""
        self.total_audio_duration = 0.0
        self.total_processing_time = 0.0
        self.transcription_count = 0


def is_sherpa_onnx_available() -> bool:
    """Check if Sherpa-ONNX is available."""
    return SHERPA_ONNX_AVAILABLE
