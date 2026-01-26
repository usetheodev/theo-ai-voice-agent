"""Piper TTS provider.

Piper is a fast, local neural text-to-speech system optimized for CPU.
Uses VITS architecture with ONNX Runtime for minimal latency.

Key advantages:
- Extremely fast on CPU (20-30ms for short phrases)
- Runs on Raspberry Pi 4
- Multiple languages including Portuguese (pt_BR)
- ONNX Runtime for efficient inference
- No GPU required

Reference: https://github.com/rhasspy/piper
"""

import asyncio
import concurrent.futures
import io
import logging
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

import numpy as np

from voice_pipeline.interfaces.tts import AudioChunk, TTSInterface
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

logger = logging.getLogger(__name__)


# Available pt_BR voices
PIPER_VOICES_PT_BR = [
    "pt_BR-faber-medium",
]

# Popular English voices
PIPER_VOICES_EN = [
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_US-ryan-medium",
    "en_GB-alba-medium",
]


@dataclass
class PiperTTSConfig(ProviderConfig):
    """Configuration for Piper TTS provider.

    Attributes:
        voice: Voice name (e.g., "pt_BR-faber-medium").
        model_path: Path to .onnx model file. If None, auto-downloads.
        data_dir: Directory for model storage. Default: ~/.local/share/piper-voices.
        speaker_id: Speaker ID for multi-speaker models. Default: 0.
        length_scale: Speed control (lower = faster). Default: 1.0.
        noise_scale: Phoneme noise. Default: 0.667.
        noise_w: Phoneme width noise. Default: 0.8.
        sentence_silence: Silence between sentences in seconds. Default: 0.2.
    """

    voice: str = "en_US-lessac-medium"
    model_path: Optional[str] = None
    data_dir: Optional[str] = None
    speaker_id: int = 0
    length_scale: float = 1.0
    noise_scale: float = 0.667
    noise_w: float = 0.8
    sentence_silence: float = 0.2


@register_tts(
    name="piper",
    capabilities=TTSCapabilities(
        streaming=True,
        voices=["pt_BR-faber-medium", "en_US-lessac-medium"],
        languages=["pt", "en", "es", "fr", "de", "it"],
        ssml=False,
        speed_control=True,
        pitch_control=False,
        sample_rates=[22050],
        formats=["pcm16"],
    ),
    description="Piper local TTS - ultra-fast CPU inference with ONNX Runtime.",
    version="1.0.0",
    aliases=["piper-tts", "fast-tts"],
    tags=["local", "offline", "fast", "cpu", "onnx"],
    default_config={
        "voice": "en_US-lessac-medium",
        "length_scale": 1.0,
    },
)
class PiperTTSProvider(BaseProvider, TTSInterface):
    """Piper TTS provider for ultra-fast CPU voice synthesis.

    Uses VITS architecture with ONNX Runtime for the fastest
    possible CPU inference. Ideal for real-time voice agents
    where every millisecond counts.

    Performance:
    - 20-30ms for short phrases on modern CPU
    - Real-time on Raspberry Pi 4
    - ~5-32M parameters depending on voice quality

    Languages:
    - pt_BR: Portuguese (Brazil) - faber voice
    - en_US: American English - lessac, amy, ryan voices
    - en_GB: British English - alba voice
    - And many more (40+ languages)

    Example:
        >>> tts = PiperTTSProvider(voice="en_US-lessac-medium")
        >>> await tts.connect()
        >>> audio = await tts.synthesize("Hello, how are you?")
    """

    provider_name: str = "piper-tts"
    name: str = "PiperTTS"

    _WARMUP_TEXTS = {
        "pt": "Olá.",
        "en": "Hello.",
        "es": "Hola.",
        "fr": "Bonjour.",
        "de": "Hallo.",
        "it": "Ciao.",
    }

    def __init__(
        self,
        config: Optional[PiperTTSConfig] = None,
        voice: Optional[str] = None,
        model_path: Optional[str] = None,
        data_dir: Optional[str] = None,
        speaker_id: Optional[int] = None,
        length_scale: Optional[float] = None,
        **kwargs,
    ):
        """Initialize Piper TTS provider.

        Args:
            config: Full configuration object.
            voice: Voice name (shortcut).
            model_path: Path to .onnx model (shortcut).
            data_dir: Model storage directory (shortcut).
            speaker_id: Speaker ID (shortcut).
            length_scale: Speed control (shortcut). Lower = faster.
            **kwargs: Additional configuration options.
        """
        if config is None:
            config = PiperTTSConfig()

        if voice is not None:
            config.voice = voice
        if model_path is not None:
            config.model_path = model_path
        if data_dir is not None:
            config.data_dir = data_dir
        if speaker_id is not None:
            config.speaker_id = speaker_id
        if length_scale is not None:
            config.length_scale = length_scale

        super().__init__(config=config, **kwargs)

        self._tts_config: PiperTTSConfig = config
        self._voice = None
        self._sample_rate: int = 22050
        self._executor = None

    @property
    def sample_rate(self) -> int:
        """Sample rate of output audio."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Number of audio channels (mono)."""
        return 1

    def _get_language(self) -> str:
        """Extract language code from voice name."""
        voice = self._tts_config.voice
        if voice.startswith("pt"):
            return "pt"
        elif voice.startswith("en"):
            return "en"
        elif voice.startswith("es"):
            return "es"
        elif voice.startswith("fr"):
            return "fr"
        elif voice.startswith("de"):
            return "de"
        elif voice.startswith("it"):
            return "it"
        return "en"

    async def connect(self) -> None:
        """Initialize Piper voice model."""
        await super().connect()

        try:
            from piper import PiperVoice
        except ImportError:
            raise ImportError(
                "piper-tts is required for Piper TTS. "
                "Install with: pip install piper-tts"
            )

        loop = asyncio.get_event_loop()

        def _load_voice():
            if self._tts_config.model_path:
                model_path = Path(self._tts_config.model_path)
                config_path = model_path.with_suffix(".onnx.json")
                return PiperVoice.load(
                    str(model_path),
                    config_path=str(config_path) if config_path.exists() else None,
                )
            else:
                # Auto-download using piper's download mechanism
                return self._download_and_load_voice(PiperVoice)

        self._voice = await loop.run_in_executor(None, _load_voice)

        # Extract sample rate from loaded voice config
        if hasattr(self._voice, 'config') and hasattr(self._voice.config, 'sample_rate'):
            self._sample_rate = self._voice.config.sample_rate

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        logger.info(
            f"Piper TTS loaded: voice={self._tts_config.voice}, "
            f"sample_rate={self._sample_rate}"
        )

    def _download_and_load_voice(self, PiperVoice):
        """Download voice model if not present, then load it."""
        data_dir = Path(
            self._tts_config.data_dir or
            Path.home() / ".local" / "share" / "piper-voices"
        )
        data_dir.mkdir(parents=True, exist_ok=True)

        voice_name = self._tts_config.voice
        model_path = data_dir / f"{voice_name}.onnx"
        config_path = data_dir / f"{voice_name}.onnx.json"

        if model_path.exists():
            return PiperVoice.load(
                str(model_path),
                config_path=str(config_path) if config_path.exists() else None,
            )

        # Download from huggingface
        try:
            from huggingface_hub import hf_hub_download

            # Voice name format: lang_REGION-name-quality
            # e.g., pt_BR-faber-medium
            parts = voice_name.split("-")
            lang_region = parts[0]  # pt_BR
            speaker = parts[1] if len(parts) > 1 else "unknown"
            quality = parts[2] if len(parts) > 2 else "medium"
            lang = lang_region.split("_")[0]  # pt

            repo_id = f"rhasspy/piper-voices"
            onnx_path = f"{lang}/{lang_region}/{speaker}/{quality}/{voice_name}.onnx"
            json_path = f"{lang}/{lang_region}/{speaker}/{quality}/{voice_name}.onnx.json"

            logger.info(f"Downloading Piper voice: {voice_name}...")

            downloaded_model = hf_hub_download(
                repo_id=repo_id,
                filename=onnx_path,
                local_dir=data_dir,
                local_dir_use_symlinks=False,
            )

            downloaded_config = hf_hub_download(
                repo_id=repo_id,
                filename=json_path,
                local_dir=data_dir,
                local_dir_use_symlinks=False,
            )

            return PiperVoice.load(downloaded_model, config_path=downloaded_config)

        except ImportError:
            raise ImportError(
                f"huggingface_hub is required to auto-download Piper voices. "
                f"Install with: pip install huggingface_hub\n"
                f"Or manually download the model to: {model_path}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to download Piper voice '{voice_name}': {e}\n"
                f"You can manually download from: "
                f"https://huggingface.co/rhasspy/piper-voices"
            ) from e

    async def disconnect(self) -> None:
        """Release Piper resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._voice = None
        self._is_warmed_up = False
        await super().disconnect()

    async def warmup(self, text: Optional[str] = None) -> float:
        """Pre-load the Piper model to eliminate cold-start latency.

        Args:
            text: Custom warmup text. Defaults to language-appropriate phrase.

        Returns:
            Warmup time in milliseconds.
        """
        if self._voice is None:
            raise RuntimeError("Voice not connected. Call connect() first.")

        lang = self._get_language()
        warmup_text = text or self._WARMUP_TEXTS.get(lang, "Hello.")

        start = time.perf_counter()
        _ = await self.synthesize(warmup_text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True

        return elapsed_ms

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if Piper is ready."""
        if self._voice is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Voice not loaded. Call connect() first.",
            )

        try:
            loop = asyncio.get_event_loop()

            def _test():
                wav_io = io.BytesIO()
                with wave.open(wav_io, "wb") as wav_file:
                    self._voice.synthesize("test", wav_file)
                return wav_io.tell() > 44  # WAV header is 44 bytes

            success = await loop.run_in_executor(self._executor, _test)

            if success:
                return HealthCheckResult(
                    status=ProviderHealth.HEALTHY,
                    message=f"Piper ready. Voice: {self._tts_config.voice}",
                    details={
                        "voice": self._tts_config.voice,
                        "sample_rate": self._sample_rate,
                    },
                )
            else:
                return HealthCheckResult(
                    status=ProviderHealth.DEGRADED,
                    message="Piper synthesis returned empty audio.",
                )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Piper error: {e}",
            )

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize audio from text stream using Piper.

        Args:
            text_stream: Async iterator of text chunks.
            voice: Not used (voice is set at init). Kept for interface compat.
            speed: Speech speed multiplier (mapped to length_scale).
            **kwargs: Additional parameters.

        Yields:
            AudioChunk objects with synthesized PCM16 audio.
        """
        if self._voice is None:
            raise RuntimeError("Voice not connected. Call connect() first.")

        loop = asyncio.get_event_loop()

        # Map speed to length_scale (inverse: higher speed = lower length_scale)
        length_scale = self._tts_config.length_scale / max(speed, 0.1)

        async for text in text_stream:
            if not text or not text.strip():
                continue

            start_time = time.perf_counter()

            try:
                def _synthesize():
                    audio_chunks = []
                    for audio_bytes in self._voice.synthesize_stream_raw(
                        text,
                        length_scale=length_scale,
                        noise_scale=self._tts_config.noise_scale,
                        noise_w=self._tts_config.noise_w,
                        sentence_silence=self._tts_config.sentence_silence,
                    ):
                        audio_chunks.append(audio_bytes)
                    return b"".join(audio_chunks)

                audio_data = await loop.run_in_executor(self._executor, _synthesize)

                if audio_data:
                    latency_ms = (time.perf_counter() - start_time) * 1000
                    self._metrics.record_success(latency_ms)

                    samples = len(audio_data) // 2  # PCM16
                    duration_ms = (samples / self._sample_rate) * 1000

                    yield AudioChunk(
                        data=audio_data,
                        sample_rate=self._sample_rate,
                        channels=1,
                        format="pcm16",
                        duration_ms=duration_ms,
                    )

            except Exception as e:
                self._metrics.record_failure(str(e))
                self._handle_error(e)
                raise

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
            voice: Not used (voice is set at init).
            speed: Speech speed multiplier.
            **kwargs: Additional parameters.

        Returns:
            Complete audio data as PCM16 bytes.
        """
        if self._voice is None:
            raise RuntimeError("Voice not connected. Call connect() first.")

        loop = asyncio.get_event_loop()
        length_scale = self._tts_config.length_scale / max(speed, 0.1)
        start_time = time.perf_counter()

        try:
            def _synthesize():
                # Use synthesize_stream_raw for raw PCM16 output
                audio_chunks = []
                for audio_bytes in self._voice.synthesize_stream_raw(
                    text,
                    length_scale=length_scale,
                    noise_scale=self._tts_config.noise_scale,
                    noise_w=self._tts_config.noise_w,
                ):
                    audio_chunks.append(audio_bytes)
                return b"".join(audio_chunks)

            audio_data = await loop.run_in_executor(self._executor, _synthesize)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            return audio_data

        except Exception as e:
            self._metrics.record_failure(str(e))
            self._handle_error(e)
            raise

    def _handle_error(self, error: Exception) -> None:
        """Convert Piper errors to provider errors."""
        error_str = str(error).lower()

        if any(x in error_str for x in ["memory", "onnx", "runtime"]):
            raise RetryableError(str(error)) from error

        if any(x in error_str for x in ["model not found", "invalid", "not found"]):
            raise NonRetryableError(str(error)) from error

    def __repr__(self) -> str:
        return (
            f"PiperTTSProvider("
            f"voice={self._tts_config.voice!r}, "
            f"connected={self._connected})"
        )
