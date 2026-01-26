"""FasterWhisper ASR provider.

FasterWhisper is a reimplementation of OpenAI's Whisper using CTranslate2,
providing up to 4x faster transcription with lower memory usage.

Optimized for CPU with int8 quantization.

Features:
- 4x faster than original Whisper
- int8 quantization for CPU efficiency
- VAD filter for better accuracy
- Word-level timestamps
- Supports all Whisper model sizes

Reference: https://github.com/SYSTRAN/faster-whisper
"""

import asyncio
import io
import logging
import time
import wave
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, List, Optional, Union

from voice_pipeline.interfaces.asr import ASRInterface, TranscriptionResult
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
)
from voice_pipeline.providers.decorators import register_asr
from voice_pipeline.providers.types import ASRCapabilities

logger = logging.getLogger(__name__)


class FasterWhisperModel(Enum):
    """Available FasterWhisper model sizes.

    Tradeoff: Larger models = better accuracy but slower.

    For CPU, recommended: tiny, base, or small.
    """
    TINY = "tiny"           # 39M params, ~1s on CPU
    TINY_EN = "tiny.en"     # English-only tiny
    BASE = "base"           # 74M params, ~2s on CPU
    BASE_EN = "base.en"     # English-only base
    SMALL = "small"         # 244M params, ~4s on CPU
    SMALL_EN = "small.en"   # English-only small
    MEDIUM = "medium"       # 769M params, ~8s on CPU
    MEDIUM_EN = "medium.en" # English-only medium
    LARGE_V1 = "large-v1"   # 1550M params
    LARGE_V2 = "large-v2"   # 1550M params (improved)
    LARGE_V3 = "large-v3"   # 1550M params (latest)
    DISTIL_LARGE_V3 = "distil-large-v3"  # Distilled, faster
    DISTIL_MEDIUM_EN = "distil-medium.en"  # Distilled medium


class ComputeType(Enum):
    """Compute type for inference.

    For CPU: use INT8 (fastest) or FLOAT32 (most accurate).
    For GPU: use FLOAT16 or INT8_FLOAT16.
    """
    INT8 = "int8"                 # CPU optimized, fastest
    INT8_FLOAT16 = "int8_float16" # GPU optimized
    INT16 = "int16"
    FLOAT16 = "float16"           # GPU default
    FLOAT32 = "float32"           # Most accurate, slowest
    AUTO = "auto"                 # Let library decide


@dataclass
class FasterWhisperConfig(ProviderConfig):
    """Configuration for FasterWhisper ASR provider.

    Attributes:
        model: Whisper model size (tiny, base, small, medium, large-v3).
        device: Device to run on ('cpu' or 'cuda').
        compute_type: Quantization type ('int8' recommended for CPU).
        language: Language code (e.g., 'pt', 'en'). None for auto-detection.
        beam_size: Beam search width. Lower = faster, higher = more accurate.
        vad_filter: Use VAD to filter silent sections.
        word_timestamps: Compute word-level timestamps.
        sample_rate: Input audio sample rate in Hz.
        cpu_threads: Number of CPU threads (0 = auto).
        num_workers: Number of parallel workers.

    Example:
        >>> config = FasterWhisperConfig(
        ...     model="small",
        ...     language="en",
        ...     compute_type="int8",
        ... )
        >>> asr = FasterWhisperProvider(config=config)
    """

    model: str = "small"
    """Whisper model size. For CPU: tiny, base, or small recommended."""

    device: str = "cpu"
    """Device: 'cpu' or 'cuda'."""

    compute_type: str = "int8"
    """Compute type. 'int8' for CPU, 'float16' for GPU."""

    language: Optional[str] = None
    """Language code (ISO-639-1). None for auto-detection."""

    beam_size: int = 5
    """Beam search width. 1-5 recommended. Lower = faster."""

    vad_filter: bool = True
    """Enable Silero VAD to filter silent sections."""

    vad_parameters: Optional[dict] = None
    """Custom VAD parameters (threshold, min_silence_duration_ms, etc.)."""

    word_timestamps: bool = False
    """Compute word-level timestamps."""

    sample_rate: int = 16000
    """Input audio sample rate. Whisper expects 16kHz."""

    cpu_threads: int = 0
    """Number of CPU threads. 0 = auto (use all cores)."""

    num_workers: int = 1
    """Number of parallel transcription workers."""

    initial_prompt: Optional[str] = None
    """Optional prompt to guide transcription style."""

    temperature: float = 0.0
    """Sampling temperature. 0 = greedy decoding."""

    compression_ratio_threshold: float = 2.4
    """Threshold for gzip compression ratio (quality filter)."""

    log_prob_threshold: float = -1.0
    """Threshold for average log probability (quality filter)."""

    no_speech_threshold: float = 0.6
    """Threshold for no_speech probability."""

    condition_on_previous_text: bool = True
    """Condition on previous output for better continuity."""


@register_asr(
    name="faster-whisper",
    capabilities=ASRCapabilities(
        streaming=True,
        languages=["en", "pt", "es", "fr", "de", "it", "ja", "ko", "zh", "ru", "ar", "hi"],
        real_time=False,
        word_timestamps=True,
        speaker_diarization=False,
    ),
    description="FasterWhisper ASR using CTranslate2 for 4x faster CPU inference.",
    version="1.0.0",
    aliases=["faster_whisper", "fasterwhisper"],
    tags=["local", "offline", "cpu-optimized", "fast"],
    default_config={
        "model": "small",
        "compute_type": "int8",
        "beam_size": 5,
        "vad_filter": True,
    },
)
class FasterWhisperProvider(BaseProvider, ASRInterface):
    """FasterWhisper ASR provider.

    Uses CTranslate2 for up to 4x faster Whisper inference.
    Optimized for CPU with int8 quantization.

    Features:
    - 4x faster than openai/whisper
    - Lower memory usage
    - int8 quantization for CPU
    - VAD filter for noise handling
    - Word-level timestamps

    Example:
        >>> asr = FasterWhisperProvider(
        ...     model="small",
        ...     language="en",
        ...     device="cpu",
        ... )
        >>> await asr.connect()
        >>>
        >>> # Transcribe audio
        >>> result = await asr.transcribe(audio_bytes)
        >>> print(result.text)
        >>>
        >>> # With VAD filter
        >>> asr = FasterWhisperProvider(
        ...     model="base",
        ...     vad_filter=True,
        ... )

    Attributes:
        provider_name: "faster-whisper"
        name: "FasterWhisper"
    """

    provider_name: str = "faster-whisper"
    name: str = "FasterWhisper"

    def __init__(
        self,
        config: Optional[FasterWhisperConfig] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        beam_size: Optional[int] = None,
        vad_filter: Optional[bool] = None,
        vad_parameters: Optional[dict] = None,
        **kwargs,
    ):
        """Initialize FasterWhisper provider.

        Args:
            config: Full configuration object.
            model: Model size (shortcut): tiny, base, small, medium, large-v3.
            language: Language code (shortcut): pt, en, es, etc.
            device: Device (shortcut): cpu or cuda.
            compute_type: Compute type (shortcut): int8, float16, float32.
            beam_size: Beam search width (shortcut).
            vad_filter: Enable VAD filter (shortcut).
            vad_parameters: Custom VAD parameters (shortcut).
            **kwargs: Additional configuration options.
        """
        if config is None:
            config = FasterWhisperConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if language is not None:
            config.language = language
        if device is not None:
            config.device = device
        if compute_type is not None:
            config.compute_type = compute_type
        if beam_size is not None:
            config.beam_size = beam_size
        if vad_filter is not None:
            config.vad_filter = vad_filter
        if vad_parameters is not None:
            config.vad_parameters = vad_parameters

        super().__init__(config=config, **kwargs)

        self._asr_config: FasterWhisperConfig = config
        self._model = None

    @property
    def sample_rate(self) -> int:
        """Expected input sample rate (16000 Hz)."""
        return self._asr_config.sample_rate

    async def connect(self) -> None:
        """Load FasterWhisper model."""
        await super().connect()

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper is required. "
                "Install with: pip install faster-whisper"
            )

        logger.info(f"Loading FasterWhisper model: {self._asr_config.model}")
        logger.info(f"Device: {self._asr_config.device}, Compute: {self._asr_config.compute_type}")

        # Load model in thread pool (blocking operation)
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(
            None,
            self._load_model,
        )

        logger.info(f"FasterWhisper model loaded: {self._asr_config.model}")

    def _load_model(self):
        """Load model (blocking)."""
        from faster_whisper import WhisperModel

        model_kwargs = {
            "device": self._asr_config.device,
            "compute_type": self._asr_config.compute_type,
        }

        if self._asr_config.cpu_threads > 0:
            model_kwargs["cpu_threads"] = self._asr_config.cpu_threads

        if self._asr_config.num_workers > 1:
            model_kwargs["num_workers"] = self._asr_config.num_workers

        return WhisperModel(self._asr_config.model, **model_kwargs)

    async def disconnect(self) -> None:
        """Release model resources."""
        if self._model is not None:
            del self._model
            self._model = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if model is loaded and functional."""
        if self._model is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Model not loaded. Call connect() first.",
            )

        try:
            # Test with minimal audio (0.5s of silence)
            import numpy as np
            test_audio = np.zeros(int(0.5 * self.sample_rate), dtype=np.float32)

            # Quick transcription test
            loop = asyncio.get_event_loop()
            segments, _ = await loop.run_in_executor(
                None,
                lambda: self._model.transcribe(test_audio, beam_size=1),
            )
            # Consume generator
            list(segments)

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"FasterWhisper ready. Model: {self._asr_config.model}",
                details={
                    "model": self._asr_config.model,
                    "device": self._asr_config.device,
                    "compute_type": self._asr_config.compute_type,
                    "vad_filter": self._asr_config.vad_filter,
                },
            )
        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Health check failed: {e}",
            )

    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe complete audio data.

        Args:
            audio_data: Audio data (PCM16, 16kHz, mono).
            language: Language code (overrides default).

        Returns:
            Transcription result with text and metadata.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call connect() first.")

        import numpy as np

        start_time = time.perf_counter()

        try:
            # Convert PCM16 bytes to float32 numpy array
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            # Build transcription kwargs
            transcribe_kwargs = {
                "beam_size": self._asr_config.beam_size,
                "vad_filter": self._asr_config.vad_filter,
                "word_timestamps": self._asr_config.word_timestamps,
                "temperature": self._asr_config.temperature,
                "compression_ratio_threshold": self._asr_config.compression_ratio_threshold,
                "log_prob_threshold": self._asr_config.log_prob_threshold,
                "no_speech_threshold": self._asr_config.no_speech_threshold,
                "condition_on_previous_text": self._asr_config.condition_on_previous_text,
            }

            # Language
            effective_language = language or self._asr_config.language
            if effective_language:
                transcribe_kwargs["language"] = effective_language

            # Initial prompt
            if self._asr_config.initial_prompt:
                transcribe_kwargs["initial_prompt"] = self._asr_config.initial_prompt

            # VAD parameters
            if self._asr_config.vad_parameters:
                transcribe_kwargs["vad_parameters"] = self._asr_config.vad_parameters

            # Run transcription in thread pool
            loop = asyncio.get_event_loop()
            segments, info = await loop.run_in_executor(
                None,
                lambda: self._model.transcribe(audio_np, **transcribe_kwargs),
            )

            # Collect all segments
            all_segments = list(segments)

            # Combine text
            text = " ".join(seg.text.strip() for seg in all_segments)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Calculate audio duration
            audio_duration = len(audio_np) / self.sample_rate

            # Log performance
            rtf = (latency_ms / 1000) / audio_duration if audio_duration > 0 else 0
            logger.info(
                f"Transcribed {audio_duration:.2f}s audio in {latency_ms:.0f}ms "
                f"(RTF: {rtf:.2f})"
            )

            return TranscriptionResult(
                text=text,
                is_final=True,
                confidence=1.0 - (info.language_probability if hasattr(info, 'language_probability') else 0),
                language=info.language if hasattr(info, 'language') else effective_language,
                start_time=0.0,
                end_time=audio_duration,
            )

        except Exception as e:
            self._metrics.record_failure(str(e))
            logger.error(f"Transcription error: {e}")
            raise

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio stream.

        Note: FasterWhisper is batch-only, so this accumulates audio
        and transcribes periodically or at the end.

        For true streaming, consider using whisper_streaming library
        with FasterWhisper as backend.

        Args:
            audio_stream: Async iterator of audio chunks (PCM16, 16kHz, mono).
            language: Language code (overrides default).

        Yields:
            TranscriptionResult objects.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call connect() first.")

        import numpy as np

        # Accumulate audio chunks
        audio_chunks: List[bytes] = []
        chunk_duration_threshold = 3.0  # Transcribe every 3 seconds
        bytes_per_second = self.sample_rate * 2  # 16-bit = 2 bytes per sample

        async for chunk in audio_stream:
            audio_chunks.append(chunk)

            # Check if we have enough audio for intermediate transcription
            total_bytes = sum(len(c) for c in audio_chunks)
            total_duration = total_bytes / bytes_per_second

            if total_duration >= chunk_duration_threshold:
                # Transcribe accumulated audio
                audio_data = b"".join(audio_chunks)
                result = await self.transcribe(audio_data, language)

                if result.text.strip():
                    yield TranscriptionResult(
                        text=result.text,
                        is_final=False,
                        confidence=result.confidence,
                        language=result.language,
                    )

                # Keep last 0.5s for context overlap
                overlap_bytes = int(0.5 * bytes_per_second)
                if len(audio_data) > overlap_bytes:
                    audio_chunks = [audio_data[-overlap_bytes:]]
                else:
                    audio_chunks = []

        # Final transcription
        if audio_chunks:
            audio_data = b"".join(audio_chunks)
            result = await self.transcribe(audio_data, language)

            yield TranscriptionResult(
                text=result.text,
                is_final=True,
                confidence=result.confidence,
                language=result.language,
                start_time=result.start_time,
                end_time=result.end_time,
            )

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"FasterWhisperProvider("
            f"model={self._asr_config.model!r}, "
            f"language={self._asr_config.language!r}, "
            f"device={self._asr_config.device!r}, "
            f"compute_type={self._asr_config.compute_type!r}, "
            f"connected={self._connected})"
        )
