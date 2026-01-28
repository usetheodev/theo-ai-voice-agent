"""Kokoro TTS provider.

Kokoro is a high-quality, open-source text-to-speech system.
Supports multiple languages and voices with natural prosody.

Reference: https://github.com/hexgrad/kokoro
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Optional

import numpy as np

from voice_pipeline.interfaces.tts import AudioChunk, TTSInterface
from voice_pipeline.utils.audio import audio_to_numpy as _to_numpy
from voice_pipeline.providers.base import (
    BaseProvider,
    HealthCheckResult,
    ProviderConfig,
    ProviderHealth,
    RetryableError,
    NonRetryableError,
)
from voice_pipeline.providers.decorators import register_tts
from voice_pipeline.providers.types import TTSCapabilities


# Language codes for Kokoro
KokoroLanguage = Literal["a", "b", "j", "k", "z", "p"]
# a = American English
# b = British English
# j = Japanese
# k = Korean
# z = Chinese
# p = Portuguese


# Popular voices for each language
KOKORO_VOICES = {
    "a": [  # American English
        "af_bella",
        "af_nicole",
        "af_sarah",
        "af_sky",
        "am_adam",
        "am_michael",
    ],
    "b": [  # British English
        "bf_emma",
        "bf_isabella",
        "bm_george",
        "bm_lewis",
    ],
    "p": [  # Portuguese
        "pf_dora",
        "pm_alex",
        "pm_santa",
    ],
}


@dataclass
class KokoroTTSConfig(ProviderConfig):
    """Configuration for Kokoro TTS provider.

    Attributes:
        lang_code: Language code (a=American, b=British, j=Japanese, k=Korean, z=Chinese, p=Portuguese).
        voice: Default voice to use.
        speed: Default speech speed (0.5 to 2.0).
        sample_rate: Output sample rate (default 24000).
        device: Device to use (cpu, cuda, mps, or None for auto).
        split_pattern: Pattern to split text for streaming.

    Example:
        >>> config = KokoroTTSConfig(
        ...     lang_code="a",
        ...     voice="af_bella",
        ...     speed=1.0,
        ... )
        >>> tts = KokoroTTSProvider(config=config)
    """

    lang_code: KokoroLanguage = "a"
    """Language code (a=American, b=British, j=Japanese, k=Korean, z=Chinese, p=Portuguese)."""

    voice: str = "af_bella"
    """Default voice (e.g., af_bella, am_adam, bf_emma)."""

    speed: float = 1.0
    """Default speech speed (0.5 to 2.0)."""

    sample_rate: int = 24000
    """Output sample rate in Hz."""

    device: Optional[str] = None
    """Device to use (cpu, cuda, mps). None for auto-detection."""

    split_pattern: str = r"\n+"
    """Pattern to split text for streaming (default: split on newlines)."""

    repo_id: Optional[str] = None
    """HuggingFace repo ID for model. None uses default."""


@register_tts(
    name="kokoro",
    capabilities=TTSCapabilities(
        streaming=True,
        voices=["af_bella", "af_nicole", "af_sarah", "am_adam", "am_michael"],
        languages=["en", "pt", "ja", "ko", "zh"],
        ssml=False,
        speed_control=True,
        pitch_control=False,
        sample_rates=[24000],
        formats=["pcm16"],
    ),
    description="Kokoro local TTS provider for high-quality voice synthesis.",
    version="1.0.0",
    aliases=["kokoro-tts", "local-tts"],
    tags=["local", "offline", "high-quality", "neural"],
    default_config={
        "lang_code": "a",
        "voice": "af_bella",
        "speed": 1.0,
    },
)
class KokoroTTSProvider(BaseProvider, TTSInterface):
    """Kokoro TTS provider for local voice synthesis.

    Uses Kokoro's neural TTS for high-quality, natural voice synthesis.
    Supports streaming for low-latency voice applications.

    Features:
    - High-quality neural TTS
    - Multiple languages and voices
    - Speed control (0.5x to 2x)
    - No API key required (local inference)
    - GPU acceleration when available

    Languages:
    - a: American English
    - b: British English
    - j: Japanese
    - k: Korean
    - z: Chinese (Mandarin)
    - p: Portuguese

    Voices:
    - af_*: American Female (bella, nicole, sarah, sky)
    - am_*: American Male (adam, michael)
    - bf_*: British Female (emma, isabella)
    - bm_*: British Male (george, lewis)
    - pf_*: Portuguese Female (dora)
    - pm_*: Portuguese Male (alex, santa)

    Example:
        >>> tts = KokoroTTSProvider(
        ...     lang_code="a",
        ...     voice="af_bella",
        ... )
        >>> await tts.connect()
        >>>
        >>> # Synthesize text
        >>> audio = await tts.synthesize("Hello, how are you?")
        >>>
        >>> # Or stream from text stream
        >>> async for chunk in tts.synthesize_stream(text_stream):
        ...     play_audio(chunk.data)

    Attributes:
        provider_name: "kokoro-tts"
        name: "KokoroTTS" (for VoiceRunnable)
    """

    provider_name: str = "kokoro-tts"
    name: str = "KokoroTTS"

    # Warmup text per language (short, natural phrases)
    _WARMUP_TEXTS = {
        "a": "Hello.",          # American English
        "b": "Hello.",          # British English
        "j": "こんにちは。",      # Japanese
        "k": "안녕하세요.",       # Korean
        "z": "你好。",           # Chinese
        "p": "Olá.",            # Portuguese
    }

    def __init__(
        self,
        config: Optional[KokoroTTSConfig] = None,
        lang_code: Optional[str] = None,
        voice: Optional[str] = None,
        speed: Optional[float] = None,
        device: Optional[str] = None,
        **kwargs,
    ):
        """Initialize Kokoro TTS provider.

        Args:
            config: Full configuration object.
            lang_code: Language code (shortcut).
            voice: Default voice (shortcut).
            speed: Default speed (shortcut).
            device: Device to use (shortcut).
            **kwargs: Additional configuration options.
        """
        # Build config from parameters
        if config is None:
            config = KokoroTTSConfig()

        # Apply shortcuts
        if lang_code is not None:
            config.lang_code = lang_code
        if voice is not None:
            config.voice = voice
        if speed is not None:
            config.speed = speed
        if device is not None:
            config.device = device

        super().__init__(config=config, **kwargs)

        self._tts_config: KokoroTTSConfig = config
        self._pipeline = None
        self._executor = None

    @property
    def sample_rate(self) -> int:
        """Sample rate of output audio."""
        return self._tts_config.sample_rate

    @property
    def channels(self) -> int:
        """Number of audio channels (mono)."""
        return 1

    async def connect(self) -> None:
        """Initialize Kokoro pipeline."""
        await super().connect()

        try:
            from kokoro import KPipeline
        except ImportError:
            raise ImportError(
                "kokoro is required for Kokoro TTS. "
                "Install with: pip install kokoro soundfile"
            )

        # Create pipeline (synchronous, so run in executor)
        loop = asyncio.get_event_loop()

        def _create_pipeline():
            return KPipeline(
                lang_code=self._tts_config.lang_code,
                repo_id=self._tts_config.repo_id,
                device=self._tts_config.device,
            )

        self._pipeline = await loop.run_in_executor(None, _create_pipeline)

        # Create executor for running sync methods
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    async def disconnect(self) -> None:
        """Close Kokoro pipeline and release resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._pipeline = None
        self._is_warmed_up = False
        await super().disconnect()

    async def warmup(self, text: Optional[str] = None) -> float:
        """Pre-load the Kokoro TTS model to eliminate cold-start latency.

        Uses language-appropriate warmup text for natural model loading.
        This is especially important for Kokoro as the first synthesis
        often takes 2-3x longer due to model initialization.

        Args:
            text: Custom warmup text. Defaults to language-appropriate phrase.

        Returns:
            Warmup time in milliseconds.

        Example:
            >>> tts = KokoroTTSProvider(lang_code="a", voice="af_heart")
            >>> await tts.connect()
            >>> warmup_ms = await tts.warmup()
            >>> print(f"Kokoro warmed up in {warmup_ms:.1f}ms")
            >>> # First real synthesis is now fast (~100-200ms vs ~500-800ms)
        """
        if self._pipeline is None:
            raise RuntimeError("Pipeline not connected. Call connect() first.")

        # Use language-appropriate warmup text
        warmup_text = text or self._WARMUP_TEXTS.get(
            self._tts_config.lang_code,
            "Hello."
        )

        start = time.perf_counter()

        # Synthesize dummy text to warm up the model
        _ = await self.synthesize(warmup_text)

        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True

        return elapsed_ms

    async def reconnect_with_device(self, device: str) -> None:
        """Reconnect with a different device (e.g., CPU fallback)."""
        import logging
        logging.getLogger(__name__).warning(
            f"Kokoro TTS: switching from {self._tts_config.device} to {device}"
        )
        if self._tts_config.device and "cuda" in self._tts_config.device:
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass

        self._tts_config.device = device
        await self.disconnect()
        await self.connect()

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if Kokoro is ready."""
        if self._pipeline is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Pipeline not initialized. Call connect() first.",
            )

        try:
            # Make a minimal synthesis call
            loop = asyncio.get_event_loop()

            def _test_synth():
                results = list(self._pipeline(
                    "test",
                    voice=self._tts_config.voice,
                    speed=1.0,
                ))
                return len(results) > 0

            success = await loop.run_in_executor(self._executor, _test_synth)

            if success:
                details = {
                    "voice": self._tts_config.voice,
                    "lang_code": self._tts_config.lang_code,
                }

                if self._tts_config.device and "cuda" in self._tts_config.device:
                    from voice_pipeline.utils.gpu import collect_gpu_metrics

                    gpu_metrics = collect_gpu_metrics(self._tts_config.device)
                    if gpu_metrics:
                        details["gpu"] = gpu_metrics.to_dict()

                return HealthCheckResult(
                    status=ProviderHealth.HEALTHY,
                    message=f"Kokoro ready. Voice: {self._tts_config.voice}",
                    details=details,
                )
            else:
                return HealthCheckResult(
                    status=ProviderHealth.DEGRADED,
                    message="Kokoro synthesis returned no results.",
                )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Kokoro error: {e}",
            )

    def list_voices(self, lang_code: Optional[str] = None) -> list[str]:
        """List available voices for a language.

        Args:
            lang_code: Language code. Defaults to configured language.

        Returns:
            List of voice names.
        """
        code = lang_code or self._tts_config.lang_code
        return KOKORO_VOICES.get(code, [])

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize audio from text stream.

        Processes each text chunk and yields audio chunks.

        Args:
            text_stream: Async iterator of text chunks (usually sentences).
            voice: Voice identifier (overrides default).
            speed: Speech speed multiplier (0.5 to 2.0).
            **kwargs: Additional parameters.

        Yields:
            AudioChunk objects with synthesized audio.

        Raises:
            RuntimeError: If pipeline is not connected.
        """
        if self._pipeline is None:
            raise RuntimeError("Pipeline not connected. Call connect() first.")

        effective_voice = voice or self._tts_config.voice
        effective_speed = speed or self._tts_config.speed

        loop = asyncio.get_event_loop()

        async for text in text_stream:
            if not text or not text.strip():
                continue

            # Preprocess text to avoid phonemizer issues
            processed_text = self._preprocess_text(text)

            start_time = time.perf_counter()

            try:
                # Run synthesis in executor (blocking operation)
                def _synthesize():
                    results = list(self._pipeline(
                        processed_text,
                        voice=effective_voice,
                        speed=effective_speed,
                        split_pattern=None,  # Don't split, we already have sentences
                    ))
                    return results

                results = await loop.run_in_executor(self._executor, _synthesize)

                for result in results:
                    # Get audio data from result
                    # Kokoro returns Result objects with .audio attribute (PyTorch Tensor)
                    audio_array = _to_numpy(result.audio)

                    # Convert to PCM16 bytes
                    audio_int16 = (audio_array * 32767).astype(np.int16)
                    audio_data = audio_int16.tobytes()

                    latency_ms = (time.perf_counter() - start_time) * 1000
                    self._metrics.record_success(latency_ms)

                    # Calculate duration
                    samples = len(audio_data) // 2  # PCM16 = 2 bytes per sample
                    duration_ms = (samples / self.sample_rate) * 1000

                    yield AudioChunk(
                        data=audio_data,
                        sample_rate=self.sample_rate,
                        channels=self.channels,
                        format="pcm16",
                        duration_ms=duration_ms,
                    )

            except Exception as e:
                self._metrics.record_failure(str(e))
                self._handle_error(e)
                raise

    def _preprocess_text(self, text: str) -> str:
        """Preprocess text to improve TTS quality and avoid phonemizer warnings.

        Handles common issues like:
        - Time notation (16h29 -> dezesseis horas e vinte e nove)
        - Numbers that phonemizer doesn't handle well
        - Special characters

        Args:
            text: Raw text to preprocess.

        Returns:
            Preprocessed text ready for synthesis.
        """
        import re

        # Handle Portuguese time notation (16h29, 10h, etc.)
        def expand_time(match):
            hours = int(match.group(1))
            minutes = match.group(2)
            if minutes:
                minutes = int(minutes)
                return f"{hours} horas e {minutes} minutos"
            return f"{hours} horas"

        text = re.sub(r'(\d{1,2})h(\d{2})?', expand_time, text)

        # Handle percentage
        text = re.sub(r'(\d+)%', r'\1 por cento', text)

        # Handle temperature (25°C, 30°)
        text = re.sub(r'(\d+)°C?', r'\1 graus', text)

        # Handle common abbreviations that cause issues
        text = text.replace("etc.", "etcetera")
        text = text.replace("Sr.", "Senhor")
        text = text.replace("Sra.", "Senhora")
        text = text.replace("Dr.", "Doutor")
        text = text.replace("Dra.", "Doutora")

        return text

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> bytes:
        """Synthesize complete audio from text.

        Args:
            text: Text to synthesize.
            voice: Voice identifier (overrides default).
            speed: Speech speed multiplier (0.5 to 2.0).
            **kwargs: Additional parameters.

        Returns:
            Complete audio data as PCM16 bytes.
        """
        if self._pipeline is None:
            raise RuntimeError("Pipeline not connected. Call connect() first.")

        effective_voice = voice or self._tts_config.voice
        effective_speed = speed or self._tts_config.speed

        # Preprocess text to avoid phonemizer issues
        processed_text = self._preprocess_text(text)

        loop = asyncio.get_event_loop()
        start_time = time.perf_counter()

        try:
            def _synthesize():
                results = list(self._pipeline(
                    processed_text,
                    voice=effective_voice,
                    speed=effective_speed,
                ))
                # Concatenate all audio results (Kokoro returns PyTorch Tensors)
                audio_chunks = []
                for result in results:
                    audio_array = _to_numpy(result.audio)
                    audio_chunks.append(audio_array)

                if audio_chunks:
                    combined = np.concatenate(audio_chunks)
                    # Convert to PCM16
                    audio_int16 = (combined * 32767).astype(np.int16)
                    return audio_int16.tobytes()
                return b""

            audio_data = await loop.run_in_executor(self._executor, _synthesize)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            return audio_data

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    def _handle_error(self, error: Exception) -> None:
        """Convert Kokoro errors to provider errors.

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
        ]):
            raise RetryableError(str(error)) from error

        # Non-retryable errors
        if any(x in error_str for x in [
            "invalid voice",
            "voice not found",
            "model not found",
            "invalid",
        ]):
            raise NonRetryableError(str(error)) from error

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"KokoroTTSProvider("
            f"lang_code={self._tts_config.lang_code!r}, "
            f"voice={self._tts_config.voice!r}, "
            f"connected={self._connected})"
        )
