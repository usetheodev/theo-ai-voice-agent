"""NVIDIA Parakeet ASR provider via ONNX.

NVIDIA Parakeet is a state-of-the-art ASR model that achieves
industry-leading accuracy with efficient inference via ONNX.

Features:
- 6% WER on English benchmarks
- 25 European languages including Portuguese
- Fast CPU inference via ONNX Runtime
- INT8 quantization for efficiency
- Small footprint (~600MB)

Reference: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, List, Optional

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


@dataclass
class ParakeetConfig(ProviderConfig):
    """Configuration for NVIDIA Parakeet ASR provider.

    Attributes:
        model: Parakeet model variant.
        language: Language code (e.g., 'pt', 'en'). None for auto-detection.
        quantization: Quantization type ('int8' recommended for CPU).
        sample_rate: Input audio sample rate in Hz.

    Example:
        >>> config = ParakeetConfig(
        ...     model="nemo-parakeet-tdt-0.6b-v3",
        ...     language="pt",
        ...     quantization="int8",
        ... )
        >>> asr = ParakeetProvider(config=config)
    """

    model: str = "nemo-parakeet-tdt-0.6b-v3"
    """Parakeet model: nemo-parakeet-tdt-0.6b-v3 (multilingual) or v2 (English)."""

    language: Optional[str] = None
    """Language code (ISO-639-1). None for auto-detection."""

    quantization: Optional[str] = "int8"
    """Quantization: 'int8' for CPU efficiency, None for full precision."""

    sample_rate: int = 16000
    """Input audio sample rate. Parakeet expects 16kHz."""

    with_timestamps: bool = False
    """Return word-level timestamps."""


@register_asr(
    name="parakeet",
    capabilities=ASRCapabilities(
        streaming=False,
        languages=[
            "en", "pt", "es", "fr", "de", "it", "nl", "pl", "ru", "uk",
            "bg", "hr", "cs", "da", "et", "fi", "el", "hu", "lv", "lt",
            "mt", "ro", "sk", "sl", "sv",
        ],
        real_time=False,
        word_timestamps=True,
        speaker_diarization=False,
    ),
    description="NVIDIA Parakeet ASR via ONNX for fast CPU inference with 25 languages.",
    version="1.0.0",
    aliases=["nvidia-parakeet", "parakeet-tdt"],
    tags=["local", "offline", "cpu-optimized", "fast", "multilingual"],
    default_config={
        "model": "nemo-parakeet-tdt-0.6b-v3",
        "quantization": "int8",
    },
)
class ParakeetProvider(BaseProvider, ASRInterface):
    """NVIDIA Parakeet ASR provider via ONNX.

    Uses ONNX Runtime for efficient CPU inference with NVIDIA's
    state-of-the-art Parakeet model.

    Features:
    - Industry-leading accuracy (~6% WER)
    - 25 European languages including Portuguese
    - INT8 quantization for fast CPU inference
    - Small model size (~600MB quantized)

    Example:
        >>> asr = ParakeetProvider(
        ...     model="nemo-parakeet-tdt-0.6b-v3",
        ...     language="pt",
        ...     quantization="int8",
        ... )
        >>> await asr.connect()
        >>>
        >>> # Transcribe audio
        >>> result = await asr.transcribe(audio_bytes)
        >>> print(result.text)

    Attributes:
        provider_name: "parakeet"
        name: "NVIDIAParakeet"
    """

    provider_name: str = "parakeet"
    name: str = "NVIDIAParakeet"

    def __init__(
        self,
        config: Optional[ParakeetConfig] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        quantization: Optional[str] = None,
        **kwargs,
    ):
        """Initialize Parakeet provider.

        Args:
            config: Full configuration object.
            model: Model variant (shortcut).
            language: Language code (shortcut): pt, en, es, etc.
            quantization: Quantization type (shortcut): int8 or None.
            **kwargs: Additional configuration options.
        """
        if config is None:
            config = ParakeetConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if language is not None:
            config.language = language
        if quantization is not None:
            config.quantization = quantization

        super().__init__(config=config, **kwargs)

        self._asr_config: ParakeetConfig = config
        self._model = None

    @property
    def sample_rate(self) -> int:
        """Expected input sample rate (16000 Hz)."""
        return self._asr_config.sample_rate

    async def connect(self) -> None:
        """Load Parakeet model via onnx-asr."""
        await super().connect()

        try:
            import onnx_asr
        except ImportError:
            raise ImportError(
                "onnx-asr is required. "
                "Install with: pip install onnx-asr soundfile"
            )

        logger.info(f"Loading Parakeet model: {self._asr_config.model}")
        logger.info(f"Quantization: {self._asr_config.quantization}")

        # Load model in thread pool (blocking operation - downloads model on first use)
        loop = asyncio.get_event_loop()
        self._model = await loop.run_in_executor(
            None,
            self._load_model,
        )

        logger.info(f"Parakeet model loaded: {self._asr_config.model}")

    def _load_model(self):
        """Load model (blocking)."""
        import onnx_asr

        load_kwargs = {}
        if self._asr_config.quantization:
            load_kwargs["quantization"] = self._asr_config.quantization

        return onnx_asr.load_model(self._asr_config.model, **load_kwargs)

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
            await loop.run_in_executor(
                None,
                lambda: self._model.recognize(test_audio, sample_rate=self.sample_rate),
            )

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"Parakeet ready. Model: {self._asr_config.model}",
                details={
                    "model": self._asr_config.model,
                    "quantization": self._asr_config.quantization,
                    "language": self._asr_config.language,
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

            # Run transcription in thread pool
            loop = asyncio.get_event_loop()

            if self._asr_config.with_timestamps:
                result = await loop.run_in_executor(
                    None,
                    lambda: self._model.recognize_with_timestamps(
                        audio_np,
                        sample_rate=self.sample_rate,
                    ),
                )
                text = result.text if hasattr(result, 'text') else str(result)
            else:
                text = await loop.run_in_executor(
                    None,
                    lambda: self._model.recognize(
                        audio_np,
                        sample_rate=self.sample_rate,
                    ),
                )

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

            effective_language = language or self._asr_config.language

            return TranscriptionResult(
                text=text.strip() if text else "",
                is_final=True,
                confidence=None,
                language=effective_language,
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

        Note: Parakeet via onnx-asr is batch-only, so this accumulates audio
        and transcribes periodically.

        Args:
            audio_stream: Async iterator of audio chunks (PCM16, 16kHz, mono).
            language: Language code (overrides default).

        Yields:
            TranscriptionResult objects.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call connect() first.")

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
            f"ParakeetProvider("
            f"model={self._asr_config.model!r}, "
            f"language={self._asr_config.language!r}, "
            f"quantization={self._asr_config.quantization!r}, "
            f"connected={self._connected})"
        )
