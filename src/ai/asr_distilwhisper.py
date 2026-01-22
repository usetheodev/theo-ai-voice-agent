"""
Distil-Whisper ASR Implementation via faster-whisper

Distil-Whisper is 6x faster than Whisper Large V3 with only 1% WER penalty.
Uses faster-whisper backend (CTranslate2) for optimized CPU/GPU inference.

References:
- Distil-Whisper: https://huggingface.co/distil-whisper/distil-large-v3
- PT-BR Model: https://huggingface.co/freds0/distil-whisper-large-v3-ptbr
- faster-whisper: https://github.com/SYSTRAN/faster-whisper

Performance:
- Latency: ~100ms for streaming
- WER PT-BR: 8.22% (freds0 model on Common Voice 16)
- CPU: ~6x faster than Whisper Large V3
- Memory: ~3GB RAM (int8 quantization)
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Optional, List
import numpy as np

logger = logging.getLogger(__name__)

# Try to import faster-whisper
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    logger.warning(
        "faster-whisper not available. Install with: pip install faster-whisper"
    )


@dataclass
class ASRResult:
    """ASR transcription result with metadata."""
    text: str
    is_partial: bool
    confidence: float
    language: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None


def is_distilwhisper_available() -> bool:
    """Check if Distil-Whisper (faster-whisper) is available."""
    return FASTER_WHISPER_AVAILABLE


class DistilWhisperASR:
    """
    Distil-Whisper ASR using faster-whisper backend.

    Supports:
    - CPU inference (int8 quantization)
    - GPU inference (float16)
    - Multiple languages (99+)
    - PT-BR specific model (freds0/distil-whisper-large-v3-ptbr)
    - Streaming via chunked processing

    Example:
        >>> asr = DistilWhisperASR(model="distil-large-v3", language="pt")
        >>> text = asr.transcribe_array(audio_data)
        >>> print(text)
        'olá mundo'
    """

    def __init__(
        self,
        model: str = "distil-large-v3",
        language: str = "pt",
        device: str = "cpu",
        compute_type: str = "int8",
        num_workers: int = 1,
        beam_size: int = 5,
    ):
        """
        Initialize Distil-Whisper ASR.

        Args:
            model: Model identifier. Options:
                - "distil-large-v3" (English-optimized, multilingual)
                - "freds0/distil-whisper-large-v3-ptbr" (PT-BR specific)
                - "distil-large-v2" (older version)
            language: Language code (pt, en, es, etc). Use "auto" for detection.
            device: "cpu" or "cuda"
            compute_type: Quantization type:
                - "int8" (CPU, fast, low memory)
                - "float16" (GPU, balanced)
                - "float32" (GPU, highest quality)
            num_workers: Number of workers for parallel processing
            beam_size: Beam search size (1-10, higher = better quality, slower)
        """
        if not FASTER_WHISPER_AVAILABLE:
            raise RuntimeError(
                "faster-whisper not installed. "
                "Install with: pip install faster-whisper"
            )

        self.model_name = model
        self.language = language
        self.device = device
        self.compute_type = compute_type

        # Use PT-BR model if Portuguese
        if language == "pt" and model == "distil-large-v3":
            logger.info("Using PT-BR specific model: freds0/distil-whisper-large-v3-ptbr")
            self.model_name = "freds0/distil-whisper-large-v3-ptbr"

        logger.info(
            f"Initializing Distil-Whisper ASR: model={self.model_name}, "
            f"device={device}, compute_type={compute_type}"
        )

        try:
            self.model = WhisperModel(
                self.model_name,
                device=device,
                compute_type=compute_type,
                num_workers=num_workers,
            )
            self.beam_size = beam_size
            self.transcriptions_count = 0
            logger.info("Distil-Whisper ASR initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Distil-Whisper: {e}")
            raise

    def transcribe_array(
        self,
        audio_data: np.ndarray,
        sample_rate: int = 16000,
    ) -> Optional[str]:
        """
        Transcribe audio array to text.

        Args:
            audio_data: Audio samples as numpy array (float32, normalized -1 to 1)
            sample_rate: Sample rate in Hz (default 16000)

        Returns:
            Transcribed text or None if no speech detected
        """
        if audio_data is None or len(audio_data) == 0:
            logger.warning("Empty audio data received")
            return None

        try:
            start_time = time.time()

            # faster-whisper expects float32 normalized audio
            if audio_data.dtype != np.float32:
                audio_data = audio_data.astype(np.float32)

            # Normalize if needed
            if audio_data.max() > 1.0 or audio_data.min() < -1.0:
                audio_data = audio_data / 32768.0

            # Transcribe
            segments, info = self.model.transcribe(
                audio_data,
                language=self.language if self.language != "auto" else None,
                beam_size=self.beam_size,
                vad_filter=True,  # Use built-in VAD
                vad_parameters=dict(
                    threshold=0.5,
                    min_speech_duration_ms=250,
                    min_silence_duration_ms=300,
                ),
            )

            # Collect all segments
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text)

            result = " ".join(text_parts).strip()

            latency = (time.time() - start_time) * 1000
            self.transcriptions_count += 1

            if result:
                logger.debug(
                    f"Transcribed in {latency:.0f}ms: '{result[:50]}...' "
                    f"(language={info.language}, prob={info.language_probability:.2f})"
                )
                return result
            else:
                logger.debug("No speech detected in audio")
                return None

        except Exception as e:
            logger.error(f"Transcription failed: {e}", exc_info=True)
            return None

    async def transcribe_stream(
        self,
        audio_iterator: AsyncIterator[np.ndarray],
        chunk_duration_s: float = 5.0,
        sample_rate: int = 16000,
    ) -> AsyncIterator[ASRResult]:
        """
        Transcribe streaming audio with chunked processing.

        This is a simplified streaming implementation that buffers audio chunks
        and processes them in batches. For true low-latency streaming, consider
        using whisper-streaming wrapper with SimulStreaming policy.

        Args:
            audio_iterator: Async iterator of audio chunks
            chunk_duration_s: Duration of each processing chunk in seconds
            sample_rate: Sample rate in Hz

        Yields:
            ASRResult objects with partial and final transcriptions
        """
        buffer = []
        chunk_samples = int(chunk_duration_s * sample_rate)
        buffer_samples = 0

        try:
            async for audio_chunk in audio_iterator:
                if audio_chunk is None or len(audio_chunk) == 0:
                    continue

                buffer.append(audio_chunk)
                buffer_samples += len(audio_chunk)

                # Process when buffer reaches chunk size
                if buffer_samples >= chunk_samples:
                    # Concatenate buffer
                    audio_data = np.concatenate(buffer)

                    # Transcribe in background thread (faster-whisper blocks)
                    text = await asyncio.to_thread(
                        self.transcribe_array,
                        audio_data,
                        sample_rate,
                    )

                    if text:
                        yield ASRResult(
                            text=text,
                            is_partial=True,
                            confidence=0.0,  # faster-whisper doesn't expose per-word confidence
                            language=self.language,
                        )

                    # Clear buffer
                    buffer = []
                    buffer_samples = 0

            # Process remaining buffer
            if buffer_samples > 0:
                audio_data = np.concatenate(buffer)
                text = await asyncio.to_thread(
                    self.transcribe_array,
                    audio_data,
                    sample_rate,
                )

                if text:
                    yield ASRResult(
                        text=text,
                        is_partial=False,
                        confidence=0.0,
                        language=self.language,
                    )

        except Exception as e:
            logger.error(f"Stream transcription failed: {e}", exc_info=True)
            raise

    def get_stats(self) -> dict:
        """Get ASR statistics."""
        return {
            "model": self.model_name,
            "language": self.language,
            "device": self.device,
            "compute_type": self.compute_type,
            "transcriptions_count": self.transcriptions_count,
        }


# Example usage
if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not FASTER_WHISPER_AVAILABLE:
        logger.error("faster-whisper not installed")
        sys.exit(1)

    # Test with sample audio (1 second of silence)
    logger.info("Testing Distil-Whisper ASR...")
    asr = DistilWhisperASR(model="distil-large-v3", language="pt")

    # Generate test audio (1 second sine wave @ 440Hz)
    sample_rate = 16000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32) * 0.3

    result = asr.transcribe_array(audio, sample_rate)
    logger.info(f"Result: {result}")
    logger.info(f"Stats: {asr.get_stats()}")
