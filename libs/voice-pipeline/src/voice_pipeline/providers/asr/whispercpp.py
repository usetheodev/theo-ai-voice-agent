"""whisper.cpp ASR provider.

High-performance local ASR using whisper.cpp via pywhispercpp.
Supports multiple models, languages, and GPU acceleration.

Reference: https://github.com/absadiki/pywhispercpp
"""

import asyncio
import io
import os
import tempfile
import time
import wave
from dataclasses import dataclass
from typing import AsyncIterator, Literal, Optional

import numpy as np

from voice_pipeline.interfaces.asr import ASRInterface, TranscriptionResult
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.decorators import register_asr
from voice_pipeline.providers.types import ASRCapabilities


# Available whisper.cpp models
WhisperCppModel = Literal[
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large", "large-v1", "large-v2", "large-v3",
    "distil-large-v3", "distil-medium.en", "distil-small.en",
    "turbo",
]


# Model sizes for download info
WHISPER_MODEL_SIZES = {
    "tiny": "75 MB",
    "tiny.en": "75 MB",
    "base": "142 MB",
    "base.en": "142 MB",
    "small": "466 MB",
    "small.en": "466 MB",
    "medium": "1.5 GB",
    "medium.en": "1.5 GB",
    "large": "2.9 GB",
    "large-v1": "2.9 GB",
    "large-v2": "2.9 GB",
    "large-v3": "2.9 GB",
    "turbo": "1.6 GB",
}


@dataclass
class WhisperCppASRConfig(ProviderConfig):
    """Configuration for whisper.cpp ASR provider.

    Attributes:
        model: Whisper model name (tiny, base, small, medium, large, turbo).
        model_path: Optional path to local model file. If None, downloads from HuggingFace.
        language: Default language code (e.g., "en", "pt", "es"). None for auto-detect.
        n_threads: Number of CPU threads to use. None for auto.
        sample_rate: Expected input sample rate (default 16000).
        translate: If True, translate to English instead of transcribing.
        beam_size: Beam search width. Higher = better quality but slower.
        best_of: Best of N sampling. Higher = better quality but slower.
        word_timestamps: If True, include word-level timestamps.
        temperature: Sampling temperature for decoding.
        initial_prompt: Optional prompt to guide transcription style.

    Example:
        >>> config = WhisperCppASRConfig(
        ...     model="base.en",
        ...     n_threads=8,
        ...     language="en",
        ... )
        >>> asr = WhisperCppASRProvider(config=config)
    """

    model: str = "base"
    """Whisper model name (tiny, base, small, medium, large, turbo)."""

    model_path: Optional[str] = None
    """Path to local model file. If None, downloads automatically."""

    language: Optional[str] = None
    """Default language code (e.g., 'en', 'pt'). None for auto-detect."""

    n_threads: Optional[int] = None
    """Number of CPU threads. None for auto-detection."""

    sample_rate: int = 16000
    """Expected input sample rate in Hz."""

    translate: bool = False
    """If True, translate to English instead of transcribing."""

    beam_size: int = 5
    """Beam search width (higher = better quality, slower)."""

    best_of: int = 5
    """Best of N sampling (higher = better quality, slower)."""

    word_timestamps: bool = False
    """Include word-level timestamps in results."""

    temperature: float = 0.0
    """Sampling temperature (0.0 for deterministic)."""

    initial_prompt: Optional[str] = None
    """Optional prompt to guide transcription style."""

    no_context: bool = False
    """Do not use past transcription as context for next segment."""

    single_segment: bool = False
    """Force single segment output (disable splitting)."""

    print_progress: bool = False
    """Print progress during transcription."""


@register_asr(
    name="whispercpp",
    capabilities=ASRCapabilities(
        streaming=True,
        languages=["en", "pt", "es", "fr", "de", "it", "ja", "ko", "zh", "ru", "ar", "hi"],
        real_time=False,  # Not true realtime, but can process incrementally
        word_timestamps=True,
        speaker_diarization=False,
    ),
    description="Local ASR using whisper.cpp for high-performance speech recognition.",
    version="1.0.0",
    aliases=["whisper-cpp", "local-asr", "whisper-local"],
    tags=["local", "offline", "high-quality", "gpu"],
    default_config={
        "model": "base",
        "n_threads": None,
        "beam_size": 5,
    },
)
class WhisperCppASRProvider(BaseProvider, ASRInterface):
    """whisper.cpp ASR provider for local speech recognition.

    Uses pywhispercpp bindings for high-performance local ASR.
    No API key required - runs entirely on your machine.

    Features:
    - Multiple model sizes (tiny to large)
    - GPU acceleration (CUDA, Metal)
    - Multiple language support
    - Word-level timestamps
    - Translation to English

    Models (auto-downloaded from HuggingFace):
    - tiny: 75 MB, fastest, lowest accuracy
    - base: 142 MB, good balance
    - small: 466 MB, better accuracy
    - medium: 1.5 GB, high accuracy
    - large: 2.9 GB, best accuracy
    - turbo: 1.6 GB, optimized large model

    Example:
        >>> asr = WhisperCppASRProvider(
        ...     model="base.en",
        ...     n_threads=8,
        ... )
        >>> await asr.connect()
        >>>
        >>> # Transcribe audio
        >>> result = await asr.transcribe(audio_bytes)
        >>> print(result.text)
        >>>
        >>> # Or use with pipeline
        >>> chain = asr | llm | tts
        >>> await chain.ainvoke(audio_bytes)

    Attributes:
        provider_name: "whispercpp"
        name: "WhisperCppASR" (for VoiceRunnable)
    """

    provider_name: str = "whispercpp"
    name: str = "WhisperCppASR"

    def __init__(
        self,
        config: Optional[WhisperCppASRConfig] = None,
        model: Optional[str] = None,
        model_path: Optional[str] = None,
        language: Optional[str] = None,
        n_threads: Optional[int] = None,
        translate: Optional[bool] = None,
        beam_size: Optional[int] = None,
        best_of: Optional[int] = None,
        word_timestamps: Optional[bool] = None,
        initial_prompt: Optional[str] = None,
        **kwargs,
    ):
        """Initialize whisper.cpp ASR provider.

        Args:
            config: Full configuration object.
            model: Model name (shortcut).
            model_path: Path to local model (shortcut).
            language: Default language (shortcut).
            n_threads: Number of threads (shortcut).
            translate: Translate to English (shortcut).
            beam_size: Beam search width (shortcut).
            best_of: Best of N sampling (shortcut).
            word_timestamps: Include word timestamps (shortcut).
            initial_prompt: Prompt to guide transcription (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = WhisperCppASRConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if model_path is not None:
            config.model_path = model_path
        if language is not None:
            config.language = language
        if n_threads is not None:
            config.n_threads = n_threads
        if translate is not None:
            config.translate = translate
        if beam_size is not None:
            config.beam_size = beam_size
        if best_of is not None:
            config.best_of = best_of
        if word_timestamps is not None:
            config.word_timestamps = word_timestamps
        if initial_prompt is not None:
            config.initial_prompt = initial_prompt

        super().__init__(config=config, **kwargs)

        self._asr_config: WhisperCppASRConfig = config
        self._model = None
        self._executor = None

    @property
    def sample_rate(self) -> int:
        """Expected input sample rate."""
        return self._asr_config.sample_rate

    async def connect(self) -> None:
        """Initialize whisper.cpp model."""
        await super().connect()

        try:
            from pywhispercpp.model import Model
        except ImportError:
            raise ImportError(
                "pywhispercpp is required for whisper.cpp ASR. "
                "Install with: pip install pywhispercpp"
            )

        # Create model in executor (blocking operation)
        loop = asyncio.get_event_loop()

        def _create_model():
            model_kwargs = {}

            # Model name or path
            model_id = self._asr_config.model_path or self._asr_config.model

            # Thread count
            if self._asr_config.n_threads:
                model_kwargs["n_threads"] = self._asr_config.n_threads

            # Create model (downloads if necessary)
            return Model(model_id, **model_kwargs)

        self._model = await loop.run_in_executor(None, _create_model)

        # Create executor for running sync methods
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    async def disconnect(self) -> None:
        """Close whisper.cpp model and release resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._model = None
        await super().disconnect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if whisper.cpp model is ready."""
        if self._model is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Model not initialized. Call connect() first.",
            )

        try:
            # Create minimal test audio (1 second of silence)
            test_audio = np.zeros(self._asr_config.sample_rate, dtype=np.float32)

            loop = asyncio.get_event_loop()

            def _test_transcribe():
                segments = self._model.transcribe(test_audio)
                return list(segments)

            await loop.run_in_executor(self._executor, _test_transcribe)

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"whisper.cpp ready. Model: {self._asr_config.model}",
                details={
                    "model": self._asr_config.model,
                    "n_threads": self._asr_config.n_threads,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"whisper.cpp error: {e}",
            )

    def _pcm16_to_float32(self, pcm_data: bytes) -> np.ndarray:
        """Convert PCM16 bytes to float32 numpy array.

        Args:
            pcm_data: Raw PCM16 audio data.

        Returns:
            Float32 numpy array normalized to [-1, 1].
        """
        # Convert bytes to int16
        audio_int16 = np.frombuffer(pcm_data, dtype=np.int16)
        # Normalize to float32 [-1, 1]
        return audio_int16.astype(np.float32) / 32768.0

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language: Optional[str] = None,
    ) -> AsyncIterator[TranscriptionResult]:
        """Transcribe audio stream.

        Collects audio chunks and transcribes. For true streaming with
        partial results, consider using smaller chunks and multiple calls.

        Args:
            audio_stream: Async iterator of audio chunks (PCM16, mono).
            language: Optional language code (overrides default).

        Yields:
            TranscriptionResult objects.
        """
        if self._model is None:
            raise RuntimeError("Model not connected. Call connect() first.")

        # Collect all audio chunks
        audio_chunks = []
        async for chunk in audio_stream:
            audio_chunks.append(chunk)

        if not audio_chunks:
            yield TranscriptionResult(
                text="",
                is_final=True,
                confidence=0.0,
            )
            return

        # Combine audio data
        audio_data = b"".join(audio_chunks)

        # Convert to float32
        audio_float = self._pcm16_to_float32(audio_data)

        effective_language = language or self._asr_config.language

        loop = asyncio.get_event_loop()
        start_time = time.perf_counter()

        try:
            def _transcribe():
                # Build transcription kwargs
                kwargs = {}

                if effective_language:
                    kwargs["language"] = effective_language

                if self._asr_config.translate:
                    kwargs["translate"] = True

                if self._asr_config.initial_prompt:
                    kwargs["initial_prompt"] = self._asr_config.initial_prompt

                if self._asr_config.temperature > 0:
                    kwargs["temperature"] = self._asr_config.temperature

                if self._asr_config.beam_size != 5:
                    kwargs["beam_size"] = self._asr_config.beam_size

                if self._asr_config.best_of != 5:
                    kwargs["best_of"] = self._asr_config.best_of

                if self._asr_config.word_timestamps:
                    kwargs["word_timestamps"] = True

                if self._asr_config.no_context:
                    kwargs["no_context"] = True

                if self._asr_config.single_segment:
                    kwargs["single_segment"] = True

                if self._asr_config.print_progress:
                    kwargs["print_progress"] = True

                # Run transcription
                segments = list(self._model.transcribe(audio_float, **kwargs))
                return segments

            segments = await loop.run_in_executor(self._executor, _transcribe)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Yield results for each segment
            for i, segment in enumerate(segments):
                is_final = (i == len(segments) - 1)

                yield TranscriptionResult(
                    text=segment.text.strip(),
                    is_final=is_final,
                    confidence=1.0,  # whisper.cpp doesn't provide confidence
                    language=effective_language,
                    start_time=segment.t0 / 100.0 if hasattr(segment, 't0') else None,
                    end_time=segment.t1 / 100.0 if hasattr(segment, 't1') else None,
                )

            # If no segments, yield empty result
            if not segments:
                yield TranscriptionResult(
                    text="",
                    is_final=True,
                    confidence=0.0,
                )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    async def transcribe(
        self,
        audio_data: bytes,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe complete audio data.

        Args:
            audio_data: Complete audio data (PCM16, mono, 16kHz).
            language: Optional language code.

        Returns:
            Final transcription result with combined text.
        """
        if self._model is None:
            raise RuntimeError("Model not connected. Call connect() first.")

        # Convert to float32
        audio_float = self._pcm16_to_float32(audio_data)

        effective_language = language or self._asr_config.language

        loop = asyncio.get_event_loop()
        start_time = time.perf_counter()

        try:
            def _transcribe():
                kwargs = {}

                if effective_language:
                    kwargs["language"] = effective_language

                if self._asr_config.translate:
                    kwargs["translate"] = True

                if self._asr_config.initial_prompt:
                    kwargs["initial_prompt"] = self._asr_config.initial_prompt

                if self._asr_config.temperature > 0:
                    kwargs["temperature"] = self._asr_config.temperature

                if self._asr_config.beam_size != 5:
                    kwargs["beam_size"] = self._asr_config.beam_size

                if self._asr_config.best_of != 5:
                    kwargs["best_of"] = self._asr_config.best_of

                if self._asr_config.word_timestamps:
                    kwargs["word_timestamps"] = True

                if self._asr_config.no_context:
                    kwargs["no_context"] = True

                if self._asr_config.single_segment:
                    kwargs["single_segment"] = True

                segments = list(self._model.transcribe(audio_float, **kwargs))
                return segments

            segments = await loop.run_in_executor(self._executor, _transcribe)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            # Combine all segments
            if segments:
                full_text = " ".join(seg.text.strip() for seg in segments)
                start_time_audio = segments[0].t0 / 100.0 if hasattr(segments[0], 't0') else None
                end_time_audio = segments[-1].t1 / 100.0 if hasattr(segments[-1], 't1') else None

                return TranscriptionResult(
                    text=full_text.strip(),
                    is_final=True,
                    confidence=1.0,
                    language=effective_language,
                    start_time=start_time_audio,
                    end_time=end_time_audio,
                )
            else:
                return TranscriptionResult(
                    text="",
                    is_final=True,
                    confidence=0.0,
                )

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    def _handle_error(self, error: Exception) -> None:
        """Convert whisper.cpp errors to provider errors.

        Args:
            error: Original exception.

        Raises:
            RetryableError: For transient errors.
            NonRetryableError: For permanent errors.
        """
        error_str = str(error).lower()

        # Retryable errors
        if any(x in error_str for x in [
            "memory",
            "cuda",
            "out of memory",
            "timeout",
            "resource",
        ]):
            raise RetryableError(str(error)) from error

        # Non-retryable errors
        if any(x in error_str for x in [
            "model not found",
            "invalid model",
            "file not found",
            "invalid",
            "unsupported",
        ]):
            raise NonRetryableError(str(error)) from error

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"WhisperCppASRProvider("
            f"model={self._asr_config.model!r}, "
            f"language={self._asr_config.language!r}, "
            f"connected={self._connected})"
        )
