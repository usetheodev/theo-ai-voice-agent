"""Qwen3-TTS provider.

Qwen3-TTS is a high-quality TTS model from Alibaba Cloud's Qwen team.
Features ultra-low latency (97ms), native Portuguese support, and voice cloning.

Reference: https://github.com/QwenLM/Qwen3-TTS
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Optional, Union

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
from voice_pipeline.utils.audio import audio_to_numpy as _to_numpy

logger = logging.getLogger(__name__)


# Supported languages
Qwen3Language = Literal[
    "Portuguese", "Chinese", "English", "Japanese", "Korean",
    "German", "French", "Russian", "Spanish", "Italian", "Auto"
]

# Model variants
Qwen3Model = Literal[
    "Qwen/Qwen3-TTS-12Hz-0.6B-Base",      # Smaller, faster (voice clone)
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",      # Larger, higher quality (voice clone)
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",  # Preset voices + instructions
    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",  # Design voices with text
]

# Preset speakers for CustomVoice model
QWEN3_SPEAKERS = {
    "Chinese": ["Vivian", "Serena", "Uncle_Fu"],
    "Chinese-Beijing": ["Dylan"],
    "Chinese-Sichuan": ["Eric"],
    "English": ["Ryan", "Aiden"],
    "Japanese": ["Ono_Anna"],
    "Korean": ["Sohee"],
}


@dataclass
class Qwen3TTSConfig(ProviderConfig):
    """Configuration for Qwen3-TTS provider.

    Attributes:
        model: Model variant to use.
        language: Target language for synthesis.
        speaker: Preset speaker (for CustomVoice model).
        instruct: Voice instruction (emotion, style, etc).
        device: Device to use (cuda, cpu, mps).
        dtype: Model dtype (bfloat16, float16, float32).
        sample_rate: Output sample rate.

    Example:
        >>> config = Qwen3TTSConfig(
        ...     model="Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        ...     language="Portuguese",
        ...     device="cuda",
        ... )
        >>> tts = Qwen3TTSProvider(config=config)
    """

    model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    """Model variant. VoiceDesign is default (no reference audio needed)."""

    language: Qwen3Language = "English"
    """Target language for synthesis."""

    speaker: Optional[str] = None
    """Preset speaker name (for CustomVoice model)."""

    instruct: Optional[str] = "Clear, natural female voice, speaking in a friendly manner."
    """Voice instruction for VoiceDesign model (e.g., 'Speak cheerfully')."""

    device: str = "cpu"
    """Device to use (cuda, cpu, mps)."""

    dtype: str = "float32"
    """Model dtype (bfloat16 for GPU, float32 for CPU)."""

    sample_rate: int = 24000
    """Output sample rate in Hz."""

    use_flash_attention: bool = False
    """Use FlashAttention 2 (requires flash-attn package)."""

    # Voice clone settings
    ref_audio: Optional[str] = None
    """Reference audio path for voice cloning."""

    ref_text: Optional[str] = None
    """Reference text matching the ref_audio."""

    # Voice design settings (for VoiceDesign model)
    voice_description: Optional[str] = None
    """Natural language description of desired voice."""


@register_tts(
    name="qwen3-tts",
    capabilities=TTSCapabilities(
        streaming=False,  # Streaming coming in future vLLM-Omni
        voices=["Ryan", "Aiden", "Vivian", "Serena"],
        languages=["pt", "en", "zh", "ja", "ko", "de", "fr", "ru", "es", "it"],
        ssml=False,
        speed_control=False,
        pitch_control=False,
        sample_rates=[24000],
        formats=["pcm16"],
    ),
    description="Qwen3-TTS with ultra-low latency (97ms) and native Portuguese support.",
    version="1.0.0",
    aliases=["qwen3", "qwen-tts"],
    tags=["local", "offline", "high-quality", "neural", "portuguese", "multilingual"],
    default_config={
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
        "language": "Portuguese",
        "device": "cpu",
    },
)
class Qwen3TTSProvider(BaseProvider, TTSInterface):
    """Qwen3-TTS provider for high-quality multilingual voice synthesis.

    Features:
    - Ultra-low latency (97ms end-to-end)
    - Native Portuguese support (no accent)
    - Voice cloning with 3 seconds of audio
    - Voice design through natural language
    - 10 languages supported

    Models:
    - 0.6B-Base: Faster, good for CPU (voice clone)
    - 1.7B-Base: Higher quality (voice clone)
    - 1.7B-CustomVoice: Preset voices + emotion control
    - 1.7B-VoiceDesign: Create voices from description

    Example:
        >>> tts = Qwen3TTSProvider(
        ...     language="Portuguese",
        ...     device="cuda",
        ... )
        >>> await tts.connect()
        >>> audio = await tts.synthesize("Hello, how are you?")

    Attributes:
        provider_name: "qwen3-tts"
        name: "Qwen3TTS"
    """

    provider_name: str = "qwen3-tts"
    name: str = "Qwen3TTS"

    # Warmup text per language
    _WARMUP_TEXTS = {
        "Portuguese": "Olá.",
        "English": "Hello.",
        "Chinese": "你好。",
        "Japanese": "こんにちは。",
        "Korean": "안녕하세요.",
        "Spanish": "Hola.",
        "French": "Bonjour.",
        "German": "Hallo.",
        "Italian": "Ciao.",
        "Russian": "Привет.",
    }

    def __init__(
        self,
        config: Optional[Qwen3TTSConfig] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        speaker: Optional[str] = None,
        instruct: Optional[str] = None,
        device: Optional[str] = None,
        dtype: Optional[str] = None,
        voice: Optional[str] = None,  # Alias for speaker
        ref_audio: Optional[str] = None,
        ref_text: Optional[str] = None,
        **kwargs,
    ):
        """Initialize Qwen3-TTS provider.

        Args:
            config: Full configuration object.
            model: Model variant (shortcut).
            language: Target language (shortcut).
            speaker: Preset speaker name (shortcut).
            instruct: Voice instruction (shortcut).
            device: Device to use (shortcut).
            dtype: Model dtype (shortcut).
            voice: Alias for speaker (for compatibility).
            ref_audio: Reference audio path for voice cloning (shortcut).
            ref_text: Reference text matching the ref_audio (shortcut).
            **kwargs: Additional configuration options.
        """
        if config is None:
            config = Qwen3TTSConfig()

        # Apply shortcuts
        if model is not None:
            config.model = model
        if language is not None:
            config.language = language
        if speaker is not None:
            config.speaker = speaker
        if voice is not None:
            config.speaker = voice
        if instruct is not None:
            config.instruct = instruct
        if device is not None:
            config.device = device
        if dtype is not None:
            config.dtype = dtype
        if ref_audio is not None:
            config.ref_audio = ref_audio
        if ref_text is not None:
            config.ref_text = ref_text

        # Auto-detect dtype based on device
        if config.device == "cuda" and config.dtype == "float32":
            config.dtype = "bfloat16"  # Better for GPU

        super().__init__(config=config, **kwargs)

        self._tts_config: Qwen3TTSConfig = config
        self._model = None
        self._voice_clone_prompt = None
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
        """Initialize Qwen3-TTS model."""
        await super().connect()

        try:
            from qwen_tts import Qwen3TTSModel
        except ImportError:
            raise ImportError(
                "qwen-tts is required for Qwen3-TTS. "
                "Install with: pip install qwen-tts soundfile"
            )

        import torch

        # Determine dtype
        dtype_map = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "float32": torch.float32,
        }
        dtype = dtype_map.get(self._tts_config.dtype, torch.float32)

        # Build model kwargs
        model_kwargs = {
            "device_map": self._tts_config.device,
            "dtype": dtype,
        }

        # Add flash attention if requested and available
        if self._tts_config.use_flash_attention:
            model_kwargs["attn_implementation"] = "flash_attention_2"

        loop = asyncio.get_event_loop()

        def _load_model():
            logger.info(f"Loading Qwen3-TTS model: {self._tts_config.model}")
            return Qwen3TTSModel.from_pretrained(
                self._tts_config.model,
                **model_kwargs,
            )

        self._model = await loop.run_in_executor(None, _load_model)

        # Prepare voice clone prompt if ref_audio provided
        if self._tts_config.ref_audio and self._tts_config.ref_text:
            await self._prepare_voice_clone()

        # Create executor for running sync methods
        import concurrent.futures
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

        logger.info(f"Qwen3-TTS ready: {self._tts_config.model} on {self._tts_config.device}")

    async def _prepare_voice_clone(self) -> None:
        """Prepare voice clone prompt from reference audio."""
        if self._model is None:
            return

        loop = asyncio.get_event_loop()

        def _create_prompt():
            return self._model.create_voice_clone_prompt(
                ref_audio=self._tts_config.ref_audio,
                ref_text=self._tts_config.ref_text,
            )

        self._voice_clone_prompt = await loop.run_in_executor(None, _create_prompt)
        logger.info("Voice clone prompt prepared")

    async def disconnect(self) -> None:
        """Release Qwen3-TTS model resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._model = None
        self._voice_clone_prompt = None
        self._is_warmed_up = False
        await super().disconnect()

    async def warmup(self, text: Optional[str] = None) -> float:
        """Pre-load the Qwen3-TTS model to eliminate cold-start latency.

        Args:
            text: Custom warmup text. Defaults to language-appropriate phrase.

        Returns:
            Warmup time in milliseconds.
        """
        if self._model is None:
            raise RuntimeError("Model not connected. Call connect() first.")

        warmup_text = text or self._WARMUP_TEXTS.get(
            self._tts_config.language,
            "Hello."
        )

        start = time.perf_counter()
        _ = await self.synthesize(warmup_text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._is_warmed_up = True

        return elapsed_ms

    async def _do_health_check(self) -> HealthCheckResult:
        """Check if Qwen3-TTS is ready."""
        if self._model is None:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message="Model not initialized. Call connect() first.",
            )

        try:
            # Quick synthesis test
            _ = await self.synthesize("Test.")

            return HealthCheckResult(
                status=ProviderHealth.HEALTHY,
                message=f"Qwen3-TTS ready. Model: {self._tts_config.model}",
                details={
                    "model": self._tts_config.model,
                    "language": self._tts_config.language,
                    "device": self._tts_config.device,
                },
            )

        except Exception as e:
            return HealthCheckResult(
                status=ProviderHealth.UNHEALTHY,
                message=f"Qwen3-TTS error: {e}",
            )

    def _determine_generation_method(self):
        """Determine which generation method to use based on model and config."""
        model_name = self._tts_config.model.lower()

        if "customvoice" in model_name:
            return "custom_voice"
        elif "voicedesign" in model_name:
            return "voice_design"
        else:
            return "voice_clone"

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        instruct: Optional[str] = None,
        **kwargs,
    ) -> bytes:
        """Synthesize complete audio from text.

        Args:
            text: Text to synthesize.
            voice: Speaker name (overrides default).
            language: Target language (overrides default).
            instruct: Voice instruction (overrides default).
            **kwargs: Additional parameters.

        Returns:
            Complete audio data as PCM16 bytes.
        """
        if self._model is None:
            raise RuntimeError("Model not connected. Call connect() first.")

        effective_language = language or self._tts_config.language
        effective_speaker = voice or self._tts_config.speaker
        effective_instruct = instruct or self._tts_config.instruct or ""

        loop = asyncio.get_event_loop()
        start_time = time.perf_counter()

        try:
            method = self._determine_generation_method()

            def _synthesize():
                import torch

                with torch.no_grad():
                    if method == "custom_voice" and effective_speaker:
                        # CustomVoice model with preset speakers
                        wavs, sr = self._model.generate_custom_voice(
                            text=text,
                            language=effective_language,
                            speaker=effective_speaker,
                            instruct=effective_instruct,
                        )
                    elif method == "voice_design":
                        # VoiceDesign model
                        voice_desc = self._tts_config.voice_description or effective_instruct
                        wavs, sr = self._model.generate_voice_design(
                            text=text,
                            language=effective_language,
                            instruct=voice_desc or "Natural, clear voice",
                        )
                    else:
                        # Base model with voice clone
                        if self._voice_clone_prompt:
                            wavs, sr = self._model.generate_voice_clone(
                                text=text,
                                language=effective_language,
                                voice_clone_prompt=self._voice_clone_prompt,
                            )
                        else:
                            # No voice clone, use voice design fallback
                            wavs, sr = self._model.generate_voice_clone(
                                text=text,
                                language=effective_language,
                                ref_audio=None,
                                ref_text=None,
                            )

                    # Convert to numpy inside no_grad to free tensors sooner
                    audio_array = _to_numpy(wavs[0])

                    # Explicitly free PyTorch tensors
                    del wavs
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()

                return audio_array, sr

            audio_array, sr = await loop.run_in_executor(self._executor, _synthesize)

            # Normalize if needed
            if audio_array.max() > 1.0 or audio_array.min() < -1.0:
                audio_array = audio_array / max(abs(audio_array.max()), abs(audio_array.min()))

            # Convert to PCM16 bytes
            audio_int16 = (audio_array * 32767).astype(np.int16)
            audio_data = audio_int16.tobytes()

            # Free intermediate arrays
            del audio_array, audio_int16

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._metrics.record_success(latency_ms)

            return audio_data

        except Exception as e:
            self._metrics.record_failure(str(e))
            logger.error(f"Qwen3-TTS synthesis error: {e}")
            raise

    async def synthesize_stream(
        self,
        text_stream: AsyncIterator[str],
        voice: Optional[str] = None,
        language: Optional[str] = None,
        instruct: Optional[str] = None,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Synthesize audio from text stream.

        Note: Qwen3-TTS doesn't support true streaming yet.
        This processes each text chunk and yields audio chunks.

        Args:
            text_stream: Async iterator of text chunks.
            voice: Speaker name (overrides default).
            language: Target language (overrides default).
            instruct: Voice instruction (overrides default).
            **kwargs: Additional parameters.

        Yields:
            AudioChunk objects with synthesized audio.
        """
        if self._model is None:
            raise RuntimeError("Model not connected. Call connect() first.")

        async for text in text_stream:
            if not text or not text.strip():
                continue

            start_time = time.perf_counter()

            try:
                audio_data = await self.synthesize(
                    text=text,
                    voice=voice,
                    language=language,
                    instruct=instruct,
                    **kwargs,
                )

                latency_ms = (time.perf_counter() - start_time) * 1000

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

    async def astream(
        self,
        text: str,
        config=None,
        **kwargs,
    ) -> AsyncIterator[AudioChunk]:
        """Stream audio for a single text (VoiceRunnable interface).

        Args:
            text: Text to synthesize.
            config: Optional configuration (dict or RunnableConfig).
            **kwargs: Additional parameters.

        Yields:
            AudioChunk with synthesized audio.
        """
        # Extract configurable dict from RunnableConfig or use raw dict
        if config is not None and hasattr(config, "configurable"):
            cfg = config.configurable or {}
        elif isinstance(config, dict):
            cfg = config
        else:
            cfg = {}
        voice = cfg.get("voice") or kwargs.get("voice")
        language = cfg.get("language") or kwargs.get("language")
        instruct = cfg.get("instruct") or kwargs.get("instruct")

        audio_data = await self.synthesize(
            text=text,
            voice=voice,
            language=language,
            instruct=instruct,
        )

        samples = len(audio_data) // 2
        duration_ms = (samples / self.sample_rate) * 1000

        yield AudioChunk(
            data=audio_data,
            sample_rate=self.sample_rate,
            channels=self.channels,
            format="pcm16",
            duration_ms=duration_ms,
        )

    def __repr__(self) -> str:
        return (
            f"Qwen3TTSProvider("
            f"model={self._tts_config.model!r}, "
            f"language={self._tts_config.language!r}, "
            f"device={self._tts_config.device!r})"
        )
